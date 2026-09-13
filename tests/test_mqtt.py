from __future__ import annotations

import json

from imx462_controller.config import MqttConfig, Secrets
from imx462_controller.mqtt.client import MqttPublisher


class FakeMqttClient:
    def __init__(self):
        self.published = []
        self._connected = True

    def publish(self, topic, payload):
        self.published.append((topic, payload))

    def is_connected(self):
        return self._connected


def make_publisher():
    config = MqttConfig(heartbeat_interval_seconds=30)
    secrets = Secrets(mqtt_host="localhost", mqtt_port=1883)
    return MqttPublisher(config, secrets)


def test_start_without_host_is_noop():
    config = MqttConfig()
    secrets = Secrets(mqtt_host="")
    pub = MqttPublisher(config, secrets)
    pub.start()
    assert pub._client is None


def test_publish_event_serializes_json():
    pub = make_publisher()
    fake = FakeMqttClient()
    pub._client = fake
    pub.publish_event("photo_captured", camera_id=0, path="/tmp/x.jpg")

    topic, payload = fake.published[0]
    assert topic == "imx462/events"
    data = json.loads(payload)
    assert data["operation"] == "photo_captured"
    assert data["camera_id"] == 0


def test_publish_status_and_metrics_topics():
    pub = make_publisher()
    fake = FakeMqttClient()
    pub._client = fake
    pub.publish_status(uptime=10)
    pub.publish_metrics(fps=60)

    assert fake.published[0][0] == "imx462/status"
    assert fake.published[1][0] == "imx462/metrics"


def test_publish_with_no_client_is_noop():
    pub = make_publisher()
    pub.publish_event("op")  # no client set -> should not raise


def test_connected_reflects_client():
    pub = make_publisher()
    assert pub.connected is False
    pub._client = FakeMqttClient()
    assert pub.connected is True


def test_start_uses_async_connect_for_retries(monkeypatch):
    # A synchronous connect() would fail once and leave telemetry dead when the
    # broker is down at startup; the async connect lets paho's network loop keep
    # retrying with the configured backoff.
    import sys
    import types

    calls = {}

    class FakePahoClient:
        def __init__(self, api_version, client_id=None):
            self.api_version = api_version

        def username_pw_set(self, username, password):
            calls["credentials"] = (username, password)

        def reconnect_delay_set(self, min_delay, max_delay):
            calls["reconnect_delay"] = (min_delay, max_delay)

        def connect_async(self, host, port, keepalive=60):
            calls["connect_async"] = (host, port, keepalive)

        def loop_start(self):
            calls["loop_start"] = True

        def is_connected(self):
            return False

    class FakeCallbackAPIVersion:
        VERSION2 = object()

    module = types.ModuleType("paho.mqtt.client")
    module.Client = FakePahoClient
    module.CallbackAPIVersion = FakeCallbackAPIVersion
    paho = types.ModuleType("paho")
    paho.mqtt = types.ModuleType("paho.mqtt")
    monkeypatch.setitem(sys.modules, "paho", paho)
    monkeypatch.setitem(sys.modules, "paho.mqtt", paho.mqtt)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", module)

    pub = make_publisher()
    pub.start()
    assert pub._client is not None
    assert calls["connect_async"] == ("localhost", 1883, 60)
    assert calls["loop_start"] is True
    assert calls["reconnect_delay"] == (1, 60)
