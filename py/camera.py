"""picamera2 wrapper for HQ Camera (IMX477)."""

import io
import threading
from PIL import Image
from picamera2 import Picamera2
from libcamera import Transform

from logger import get_logger

log = get_logger("camera")


class Camera:
    def __init__(self, rotation: bool = True):
        self._picam2 = Picamera2()
        self._rotation = rotation
        self._current_roi = None
        self._lock = threading.Lock()
        self._cached_snapshot = None
        self._snapshot_crop = None
        self._effective_crop = None
        self._configure(rotation)
        self._picam2.start()
        self._capture_full_snapshot()
        # Use actual ISP crop from snapshot as effective crop limits
        # (ScalerCropMaximum is unreliable - reports full sensor but ISP clamps tighter)
        sw, sh = self._picam2.camera_properties["PixelArraySize"]
        self._crop_limits = self._effective_crop or (0, 0, sw, sh)
        log.info("camera started (rotation=%s, crop_limits=%s)", rotation, self._crop_limits)

    def _configure(self, rotation: bool):
        transform = Transform(hflip=rotation, vflip=rotation)
        config = self._picam2.create_preview_configuration(
            main={"size": (1920, 1080), "format": "RGB888"},
            transform=transform,
        )
        self._picam2.configure(config)

    @property
    def sensor_size(self) -> tuple:
        """Return (width, height) of full pixel array."""
        return self._picam2.camera_properties["PixelArraySize"]

    @property
    def crop_limits(self) -> tuple:
        """Return (x, y, w, h) of ScalerCropMaximum (cached at startup)."""
        return self._crop_limits

    @property
    def snapshot_crop(self) -> tuple:
        """Return (x, y, w, h) of the actual visible area in the cached snapshot."""
        if self._snapshot_crop:
            return self._snapshot_crop
        return self._crop_limits

    def get_frame(self):
        """Capture current frame as numpy array (H, W, 3) in BGR order."""
        with self._lock:
            return self._picam2.capture_array("main")

    def get_actual_roi(self) -> tuple | None:
        """Return the actual ScalerCrop (cached from last set_roi)."""
        return self._current_roi

    def _capture_full_snapshot(self):
        """Capture full-sensor JPEG. Called with lock held or during init."""
        sw, sh = self.sensor_size
        self._picam2.set_controls({"ScalerCrop": (0, 0, sw, sh)})
        for _ in range(10):
            self._picam2.capture_array("main")
        # Capture frame, then read metadata for actual visible area
        frame = self._picam2.capture_array("main")
        metadata = self._picam2.capture_metadata()
        actual_crop = metadata.get("ScalerCrop")
        if actual_crop:
            self._effective_crop = tuple(actual_crop)
            log.info("effective crop: %s", self._effective_crop)
        # Restore ROI
        if self._current_roi:
            self._picam2.set_controls({"ScalerCrop": self._current_roi})
        # Build full-sensor preview: place captured 16:9 frame onto 4:3 canvas
        rgb = frame[:, :, ::-1]
        frame_img = Image.fromarray(rgb)
        fw, fh = frame_img.size  # 1920x1080
        # Canvas with sensor aspect ratio
        canvas_w = fw
        canvas_h = round(fw * sh / sw)
        canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
        # Place frame at correct position
        crop = self._effective_crop or (0, 0, sw, sh)
        paste_y = round(crop[1] / sh * canvas_h)
        paste_h = round(crop[3] / sh * canvas_h)
        if paste_h != fh:
            frame_img = frame_img.resize((fw, paste_h), Image.LANCZOS)
        canvas.paste(frame_img, (0, paste_y))
        # Now snapshot represents full sensor
        self._snapshot_crop = (0, 0, sw, sh)
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=70)
        self._cached_snapshot = buf.getvalue()
        log.info("snapshot built: %dx%d canvas, frame at y=%d h=%d", canvas_w, canvas_h, paste_y, paste_h)

    def refresh_snapshot(self):
        """Take a new full-sensor snapshot (called explicitly by user)."""
        with self._lock:
            self._capture_full_snapshot()
        log.info("snapshot refreshed")

    def get_snapshot_jpeg(self) -> bytes:
        """Return cached full-sensor JPEG."""
        if self._cached_snapshot:
            return self._cached_snapshot
        with self._lock:
            frame = self._picam2.capture_array("main")
        rgb = frame[:, :, ::-1]
        img = Image.fromarray(rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return buf.getvalue()

    def set_roi(self, x: int, y: int, w: int, h: int):
        """Set ScalerCrop ROI in sensor coordinates."""
        with self._lock:
            self._current_roi = (x, y, w, h)
            self._picam2.set_controls({"ScalerCrop": (x, y, w, h)})
        log.info("ROI set to (%d,%d,%d,%d)", x, y, w, h)

    def set_rotation(self, enabled: bool):
        """Change rotation (requires camera restart)."""
        if enabled == self._rotation:
            return
        log.info("changing rotation to %s (restarting camera)", enabled)
        with self._lock:
            self._rotation = enabled
            self._picam2.stop()
            self._configure(enabled)
            self._picam2.start()
            if self._current_roi:
                self._picam2.set_controls({"ScalerCrop": self._current_roi})
            self._capture_full_snapshot()
            sw, sh = self.sensor_size
            self._crop_limits = self._effective_crop or (0, 0, sw, sh)

    def stop(self):
        self._picam2.stop()
        log.info("camera stopped")
