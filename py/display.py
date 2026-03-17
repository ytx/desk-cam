"""pygame kmsdrm display output."""

import os
import pygame

from logger import get_logger

log = get_logger("display")

_last_roi_aspect = None
_roi_aspect = 16 / 9


def init():
    """Initialize pygame with kmsdrm backend."""
    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.display.init()
    screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN)
    screen.fill((0, 0, 0))
    log.info("display initialized (kmsdrm, 1920x1080)")
    return screen


def set_roi_aspect(w, h):
    """Update the ROI aspect ratio (called when ROI changes)."""
    global _roi_aspect, _last_roi_aspect
    if h > 0:
        _roi_aspect = w / h


def show_frame(screen, frame):
    """Blit frame with correct ROI aspect ratio, black bars for padding.

    ISP always outputs 1920x1080 (16:9). If the ROI is not 16:9,
    the ISP center-crops the ROI to 16:9. We scale the frame to
    show it at the ROI's true aspect ratio with letterbox/pillarbox.
    """
    global _last_roi_aspect

    frame = frame[:, :, ::-1]
    fh, fw = frame.shape[0], frame.shape[1]
    sw, sh = screen.get_size()

    # Display size for the ROI aspect ratio
    if _roi_aspect >= sw / sh:
        dw = sw
        dh = int(sw / _roi_aspect)
    else:
        dh = sh
        dw = int(sh * _roi_aspect)

    x = (sw - dw) // 2
    y = (sh - dh) // 2

    # Clear when aspect changes
    if _roi_aspect != _last_roi_aspect:
        screen.fill((0, 0, 0))
        _last_roi_aspect = _roi_aspect

    surf = pygame.image.frombuffer(frame.tobytes(), (fw, fh), "RGB")
    if dw != fw or dh != fh:
        surf = pygame.transform.scale(surf, (dw, dh))
    screen.blit(surf, (x, y))


def flip():
    pygame.display.flip()


def quit():
    pygame.display.quit()
    log.info("display quit")
