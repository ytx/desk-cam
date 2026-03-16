"""picamera2 wrapper for HQ Camera (IMX477)."""

import io
from PIL import Image
from picamera2 import Picamera2
from libcamera import Transform

from logger import get_logger

log = get_logger("camera")


class Camera:
    def __init__(self, rotation: bool = True):
        self._picam2 = Picamera2()
        self._rotation = rotation
        self._configure(rotation)
        self._picam2.start()
        log.info("camera started (rotation=%s)", rotation)

    def _configure(self, rotation: bool):
        transform = Transform(hflip=rotation, vflip=rotation)
        config = self._picam2.create_preview_configuration(
            main={"size": (1920, 1080), "format": "RGB888"},
            transform=transform,
        )
        self._picam2.configure(config)

    @property
    def sensor_size(self) -> tuple:
        """Return (width, height) of the sensor pixel array."""
        return self._picam2.camera_properties["PixelArraySize"]

    def get_frame(self):
        """Capture current frame as numpy array (H, W, 3)."""
        return self._picam2.capture_array("main")

    def get_frame_jpeg(self, quality: int = 70) -> bytes:
        """Capture current frame and encode as JPEG bytes."""
        frame = self._picam2.capture_array("main")
        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def set_roi(self, x: int, y: int, w: int, h: int):
        """Set ScalerCrop ROI in sensor coordinates."""
        self._picam2.set_controls({"ScalerCrop": (x, y, w, h)})
        log.info("ROI set to (%d, %d, %d, %d)", x, y, w, h)

    def set_rotation(self, enabled: bool):
        """Change rotation (requires camera restart)."""
        if enabled == self._rotation:
            return
        log.info("changing rotation to %s (restarting camera)", enabled)
        self._rotation = enabled
        self._picam2.stop()
        self._configure(enabled)
        self._picam2.start()

    def stop(self):
        self._picam2.stop()
        log.info("camera stopped")
