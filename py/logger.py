"""Tagged logger with in-memory ring buffer."""

import logging
import collections
import sys

_LOG_BUFFER = collections.deque(maxlen=500)


class _BufferHandler(logging.Handler):
    def emit(self, record):
        _LOG_BUFFER.append(self.format(record))


def get_logger(tag: str) -> logging.Logger:
    """Return a logger with the given tag prefix."""
    name = f"desk-cam.{tag}"
    logger = logging.getLogger(name)
    if not logger.handlers:
        fmt = logging.Formatter(f"[{tag}] %(levelname)s %(message)s")
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        bh = _BufferHandler()
        bh.setFormatter(fmt)
        logger.addHandler(bh)
        logger.setLevel(logging.DEBUG)
    return logger


def get_log_lines():
    """Return recent log lines."""
    return list(_LOG_BUFFER)
