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
