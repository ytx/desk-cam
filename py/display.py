"""pygame kmsdrm display output."""

import os
import pygame

from logger import get_logger

log = get_logger("display")


def init():
    """Initialize pygame with kmsdrm backend."""
    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.display.init()
    screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN)
    log.info("display initialized (kmsdrm, 1920x1080)")
    return screen


def show_frame(screen, frame):
    """Blit a numpy RGB frame (H, W, 3) onto the screen."""
    h, w = frame.shape[0], frame.shape[1]
    surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
    screen.blit(surf, (0, 0))


def flip():
    """Flip the display buffer."""
    pygame.display.flip()


def quit():
    pygame.display.quit()
    log.info("display quit")
