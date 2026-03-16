"""Configuration persistence via JSON file."""

import json
import os
import subprocess
from pathlib import Path

from logger import get_logger

log = get_logger("config")

_CONFIG_DIR = Path.home() / ".config" / "desk-cam"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

_DEFAULTS = {
    "roi": {"x": 0, "y": 0, "w": 4056, "h": 3040},
    "rotation": True,
    "presets": {
        "default": {"x": 0, "y": 0, "w": 4056, "h": 3040, "rotation": True}
    },
    "mqtt": {
        "broker": "localhost",
        "port": 1883,
        "ws_port": 9090,
        "topic_prefix": "clients"
    },
    "web_port": 8080,
}

_data: dict = {}


def load() -> dict:
    global _data
    _data = json.loads(json.dumps(_DEFAULTS))  # deep copy
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE) as f:
                saved = json.load(f)
            # merge top-level keys
            for key, value in saved.items():
                if isinstance(value, dict) and isinstance(_data.get(key), dict):
                    _data[key].update(value)
                else:
                    _data[key] = value
            log.info("loaded %s", _CONFIG_FILE)
        except Exception as e:
            log.warning("config load failed: %s", e)
    return _data


_SAVE_SH = Path("/boot/firmware/config/save.sh")


def save():
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w") as f:
            json.dump(_data, f, indent=2)
    except Exception as e:
        log.warning("config save failed: %s", e)


def persist():
    """Persist config to boot partition via config-persistence save.sh."""
    if not _SAVE_SH.exists():
        return
    try:
        subprocess.run(
            ["sudo", str(_SAVE_SH), "--all"],
            timeout=10, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log.info("config persisted to boot partition")
    except Exception as e:
        log.warning("config persist failed: %s", e)


def get(key: str, default=None):
    return _data.get(key, default)


def set(key: str, value):
    _data[key] = value
    save()
