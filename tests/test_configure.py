from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import configure


def test_default_answers():
    a = configure.default_answers()
    assert a["camera_count"] == 1
    assert a["ssh_user"] == "root"
    assert a["mode_bit_depth"] == 12


def test_render_inventory():
    a = configure.default_answers()
    a.update(target_host="cam-server", target_ip="192.168.1.50", camera_count=2)
    inv = configure.render_inventory(a)
    assert "[imx462]" in inv
    assert "cam-server ansible_host=192.168.1.50 ansible_user=root" in inv
    assert "imx462_camera_count=2" in inv


def test_render_inventory_uses_hostname_when_no_ip():
    a = configure.default_answers()
    a.update(target_host="cam-server", target_ip="")
    inv = configure.render_inventory(a)
    assert "cam-server ansible_host=cam-server" in inv


def test_render_host_vars_yaml_valid_two_cameras():
    a = configure.default_answers()
    a.update(
        camera_count=2,
        mqtt_host="broker.example.com",
        otel_endpoint="http://otel:4318",
        mqtt_password="s3cret",
    )
    doc = yaml.safe_load(configure.render_host_vars(a))
    assert doc["imx462_camera_count"] == 2
    assert [c["name"] for c in doc["imx462_config"]["cameras"]] == ["cam0", "cam1"]
    assert [c["id"] for c in doc["imx462_config"]["cameras"]] == [0, 1]
    assert doc["imx462_config"]["default_mode"]["bit_depth"] == 12
    assert doc["imx462_config"]["server"]["port"] == 8000
    assert doc["imx462_config"]["otel"]["endpoint"] == "http://otel:4318"
    assert doc["imx462_env"]["MQTT_HOST"] == "broker.example.com"
    assert doc["imx462_env"]["MQTT_PORT"] == "1883"
    assert doc["imx462_env"]["MQTT_PASSWORD"] == "s3cret"
    assert doc["imx462_venv"] == "{{ imx462_app_dir }}/venv"


def test_render_host_vars_single_camera():
    a = configure.default_answers()
    doc = yaml.safe_load(configure.render_host_vars(a))
    assert [c["name"] for c in doc["imx462_config"]["cameras"]] == ["cam0"]
    assert doc["imx462_camera_count"] == 1


def test_scalar_quoting():
    assert configure._scalar("INFO") == "INFO"
    assert configure._scalar("broker.example.com") == "broker.example.com"
    assert configure._scalar("http://otel:4318") == "'http://otel:4318'"
    assert configure._scalar("1883") == "'1883'"
    assert configure._scalar("") == "''"
    assert configure._scalar(8000) == "8000"


def test_cli_with_answers_file(tmp_path):
    answers = configure.default_answers()
    answers.update(
        target_host="cam-server",
        target_ip="192.168.1.50",
        camera_count=2,
        mqtt_password="s3cret",
    )
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps(answers))
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "configure.py"),
            "--answers-file",
            str(answers_file),
            "--yes",
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    inv = (out / "inventory.ini").read_text()
    assert "cam-server" in inv
    assert "imx462_camera_count=2" in inv

    hv = yaml.safe_load((out / "host_vars" / "cam-server.yml").read_text())
    assert hv["imx462_camera_count"] == 2
    assert hv["imx462_env"]["MQTT_PASSWORD"] == "s3cret"


def test_cli_refuses_overwrite_without_force(tmp_path):
    answers = configure.default_answers()
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps(answers))
    out = tmp_path / "out"
    out.mkdir()
    (out / "inventory.ini").write_text("existing")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "configure.py"),
            "--answers-file",
            str(answers_file),
            "--yes",
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert (out / "inventory.ini").read_text() == "existing"
