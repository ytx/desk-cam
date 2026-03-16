"""MQTT client for online/away status and preset switching."""

import socket
import paho.mqtt.client as mqtt

from logger import get_logger

log = get_logger("mqtt")


class MqttClient:
    def __init__(self, broker: str, port: int, topic_prefix: str, on_preset_request=None):
        self._broker = broker
        self._port = port
        self._hostname = socket.gethostname()
        self._base_topic = f"{topic_prefix}/{self._hostname}"
        self._on_preset_request = on_preset_request
        self._client = None
        self._current_preset = None

    def start(self):
        try:
            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self._client.will_set(self._base_topic, "away", qos=1, retain=True)
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
            self._client.on_disconnect = self._on_disconnect
            self._client.connect(self._broker, self._port, keepalive=60)
            self._client.loop_start()
            log.info("connecting to %s:%d", self._broker, self._port)
        except Exception as e:
            log.warning("MQTT connection failed: %s (continuing without MQTT)", e)
            self._client = None

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        log.info("connected (rc=%s)", rc)
        client.publish(self._base_topic, "online", qos=1, retain=True)
        client.subscribe(f"{self._base_topic}/preset/set")
        if self._current_preset:
            client.publish(f"{self._base_topic}/preset", self._current_preset, qos=1, retain=True)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        if rc != 0:
            log.warning("unexpected disconnect (rc=%s)", rc)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8")
        log.info("received: %s = %s", msg.topic, payload)
        if msg.topic.endswith("/preset/set") and self._on_preset_request:
            self._on_preset_request(payload)

    def publish_preset(self, name: str):
        self._current_preset = name
        if self._client and self._client.is_connected():
            self._client.publish(f"{self._base_topic}/preset", name, qos=1, retain=True)

    def stop(self):
        if self._client:
            self._client.publish(self._base_topic, "away", qos=1, retain=True)
            self._client.loop_stop()
            self._client.disconnect()
            log.info("disconnected")
