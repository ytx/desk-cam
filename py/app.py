#!/usr/bin/env python3
"""Desk-Cam: HQ Camera HDMI viewer with Web UI and MQTT control."""

import signal
import sys

import pygame

import config
import display
from camera import Camera
from mqtt_client import MqttClient
import web_server
from logger import get_logger

log = get_logger("app")

running = True


def signal_handler(sig, frame):
    global running
    log.info("received signal %d, shutting down", sig)
    running = False


class App:
    def __init__(self):
        config.load()
        self._camera = Camera(rotation=config.get("rotation", True))
        self._screen = display.init()
        self._mqtt = None
        self._setup_mqtt()
        self._setup_web()
        self._apply_roi()

    def _setup_mqtt(self):
        mqtt_cfg = config.get("mqtt", {})
        self._mqtt = MqttClient(
            broker=mqtt_cfg.get("broker", "localhost"),
            port=mqtt_cfg.get("port", 1883),
            topic_prefix=mqtt_cfg.get("topic_prefix", "clients"),
            on_preset_request=self.load_preset,
        )
        self._mqtt.start()

    def _setup_web(self):
        web_server.set_app(self)
        web_server.start(config.get("web_port", 8080))

    def _apply_roi(self):
        roi = config.get("roi", {})
        w, h = roi.get("w", 4056), roi.get("h", 3040)
        self._camera.set_roi(roi.get("x", 0), roi.get("y", 0), w, h)
        display.set_roi_aspect(w, h)

    # --- Public API (called by web_server and mqtt) ---

    def set_roi(self, x: int, y: int, w: int, h: int):
        self._camera.set_roi(x, y, w, h)
        display.set_roi_aspect(w, h)
        config.set("roi", {"x": x, "y": y, "w": w, "h": h})

    def set_rotation(self, enabled: bool):
        self._camera.set_rotation(enabled)
        config.set("rotation", enabled)

    def load_preset(self, name: str) -> bool:
        presets = config.get("presets", {})
        if name not in presets:
            log.warning("preset '%s' not found", name)
            return False
        preset = presets[name]
        self._camera.set_roi(preset["x"], preset["y"], preset["w"], preset["h"])
        if "rotation" in preset:
            self._camera.set_rotation(preset["rotation"])
            config.set("rotation", preset["rotation"])
        config.set("roi", {"x": preset["x"], "y": preset["y"], "w": preset["w"], "h": preset["h"]})
        if self._mqtt:
            self._mqtt.publish_preset(name)
        log.info("loaded preset '%s'", name)
        return True

    def save_preset(self, name: str):
        roi = config.get("roi", {})
        x, y = roi.get("x", 0), roi.get("y", 0)
        w, h = roi.get("w", 4056), roi.get("h", 3040)
        presets = config.get("presets", {})
        presets[name] = {
            "x": x, "y": y, "w": w, "h": h,
            "rotation": config.get("rotation", True),
        }
        config.set("presets", presets)
        log.info("saved preset '%s': (%d,%d,%d,%d)", name, x, y, w, h)

    def delete_preset(self, name: str) -> bool:
        presets = config.get("presets", {})
        if name not in presets:
            return False
        del presets[name]
        config.set("presets", presets)
        log.info("deleted preset '%s'", name)
        return True

    def get_snapshot_jpeg(self) -> bytes:
        return self._camera.get_snapshot_jpeg()

    def refresh_snapshot(self):
        self._camera.refresh_snapshot()

    def get_status(self) -> dict:
        sensor_w, sensor_h = self._camera.sensor_size
        cl = self._camera.crop_limits
        sc = self._camera.snapshot_crop
        return {
            "roi": config.get("roi"),
            "rotation": config.get("rotation"),
            "presets": config.get("presets", {}),
            "sensor": {"w": sensor_w, "h": sensor_h},
            "crop_limits": {"x": cl[0], "y": cl[1], "w": cl[2], "h": cl[3]},
            "snapshot_crop": {"x": sc[0], "y": sc[1], "w": sc[2], "h": sc[3]},
        }

    # --- Main loop ---

    def run(self):
        global running
        clock = pygame.time.Clock()
        log.info("main loop started")
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
            frame = self._camera.get_frame()
            display.show_frame(self._screen, frame)
            display.flip()
            clock.tick(5)

    def shutdown(self):
        if self._mqtt:
            self._mqtt.stop()
        self._camera.stop()
        display.quit()
        config.persist()
        log.info("shutdown complete")


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app = App()
    try:
        app.run()
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
