"""MQTT telemetry publisher (operation events, heartbeat/status, metrics)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from ..config import MqttConfig, Secrets

logger = logging.getLogger(__name__)


class MqttPublisher:
    """Publishes events/status/metrics to an external broker with auto-reconnect.

    ``paho.mqtt`` is imported lazily so the module is importable without it.
    """

    def __init__(
        self, mqtt_config: MqttConfig, secrets: Secrets, client_id: str | None = None
    ) -> None:
        self._topics = mqtt_config.topics
        self._host = secrets.mqtt_host
        self._port = secrets.mqtt_port
        self._username = secrets.mqtt_username
        self._password = secrets.mqtt_password
        self._client_id = client_id
        self._client = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()

    def start(self) -> None:
        if not self._host:
            logger.info("MQTT disabled (no host configured)")
            return
        try:
            import paho.mqtt.client as mqtt

            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._client_id)
            if self._username:
                self._client.username_pw_set(self._username, self._password)
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.reconnect_delay_set(min_delay=1, max_delay=60)
            self._client.connect(self._host, self._port, keepalive=60)
            self._client.loop_start()
            logger.info("MQTT connected to %s:%s", self._host, self._port)
        except Exception as exc:  # noqa: BLE001 - never crash the app on MQTT errors
            logger.warning("MQTT connect failed: %s", exc)
            self._client = None

    def stop(self) -> None:
        self._heartbeat_stop.set()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                logger.debug("MQTT disconnect error", exc_info=True)
            self._client = None

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        logger.info("MQTT connected (rc=%s)", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        logger.warning("MQTT disconnected (rc=%s); reconnecting", reason_code)

    def publish_event(self, operation: str, **fields: Any) -> None:
        self._publish(self._topics.events, {"operation": operation, **fields})

    def publish_status(self, **fields: Any) -> None:
        self._publish(self._topics.status, fields)

    def publish_metrics(self, **fields: Any) -> None:
        self._publish(self._topics.metrics, fields)

    def start_heartbeat(
        self, interval_seconds: int, status_fn: Callable[[], dict[str, Any]]
    ) -> None:
        """Publish a status message every ``interval_seconds`` via a daemon thread."""

        def _loop() -> None:
            while not self._heartbeat_stop.wait(interval_seconds):
                try:
                    self.publish_status(**(status_fn() or {}))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Heartbeat failed: %s", exc)

        self._heartbeat_thread = threading.Thread(target=_loop, daemon=True, name="mqtt-heartbeat")
        self._heartbeat_thread.start()

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._client is None:
            return
        try:
            self._client.publish(topic, json.dumps(payload, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.warning("MQTT publish failed: %s", exc)

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected()
