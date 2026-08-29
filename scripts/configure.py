#!/usr/bin/env python3
"""Interactive setup configurator for the IMX462 RPi Controller.

Walks the user through the questions needed to deploy to a fresh Raspberry Pi
and generates the local Ansible inventory and host_vars:

    ansible/inventory.ini
    ansible/host_vars/<hostname>.yml

Both files are git-ignored (see .gitignore) and must never be committed: the
host_vars contain the secrets (MQTT credentials, OTel headers).

Stdlib-only (no pip install required). Python 3.9+.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ANSI styling (disabled automatically when stdout is not a TTY)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"

_COLORS_ENABLED = sys.stdout.isatty()


def _style(text: str, *codes: str) -> str:
    if not _COLORS_ENABLED or not codes:
        return text
    return "".join(codes) + text + _RESET


def _box(title: str) -> str:
    """Render a box-drawing banner around ``title``."""
    width = max(52, len(title) + 6)
    inner = width - 2
    pad = inner - len(title)
    left = pad // 2
    right = pad - left
    line = "═" * width
    return (
        _style("╔" + line + "╗", _CYAN, _BOLD)
        + "\n"
        + _style("║" + " " * left + title + " " * right + "║", _CYAN, _BOLD)
        + "\n"
        + _style("╚" + line + "╝", _CYAN, _BOLD)
    )


# ---------------------------------------------------------------------------
# Answer collection
# ---------------------------------------------------------------------------

_INT_KEYS = {
    "camera_count",
    "server_port",
    "mode_width",
    "mode_height",
    "mode_bit_depth",
    "mode_framerate",
    "mqtt_port",
}


def default_answers() -> dict[str, Any]:
    return {
        "target_host": "cam-server",
        "target_ip": "",
        "ssh_user": "root",
        "service_user": "user",
        "camera_count": 1,
        "app_dir": "/opt/imx462-controller",
        "media_dir": "/var/lib/imx462-controller/media",
        "server_host": "0.0.0.0",
        "server_port": 8000,
        "mode_width": 1920,
        "mode_height": 1080,
        "mode_bit_depth": 12,
        "mode_framerate": 60,
        "log_level": "INFO",
        "mqtt_host": "",
        "mqtt_port": 1883,
        "mqtt_username": "",
        "mqtt_password": "",
        "otel_endpoint": "",
        "otel_service_name": "imx462-rpi-controller",
        "otel_headers": "",
        "otel_certificate": "",
    }


def _prompt(label: str, default: Any = "") -> str:
    suffix = f" [{_style(str(default), _DIM)}]" if str(default) else ""
    return _style(f"? {label}", _BOLD) + suffix + " > "


def _ask(
    label: str,
    default: Any = "",
    *,
    secret: bool = False,
    validate: Any = None,
) -> str:
    """Ask one question; returns a string (or int for ``validate=int``)."""
    while True:
        if secret and sys.stdin.isatty():
            raw = getpass.getpass(_prompt(label))
        else:
            raw = input(_prompt(label, default))
        value = raw.strip() or str(default)
        if validate is not None:
            ok, message, value = validate(value)
            if not ok:
                print(_style(f"  ✗ {message}", _RED))
                continue
        return value


def _int_in_range(lo: int, hi: int) -> Any:
    def check(raw: str):
        try:
            n = int(raw)
        except ValueError:
            return False, f"expected a number between {lo} and {hi}", raw
        if not lo <= n <= hi:
            return False, f"expected a number between {lo} and {hi}", raw
        return True, "", n

    return check


def _one_of(choices: dict[str, Any]) -> Any:
    def check(raw: str):
        value = raw.strip()
        if value not in choices:
            return False, f"choose one of: {', '.join(choices)}", value
        return True, "", choices[value]

    return check


def _load_answers_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        supplied = json.load(fh)
    if not isinstance(supplied, dict):
        raise TypeError(f"answers file {path} must contain a JSON object")
    answers = default_answers()
    for key, value in supplied.items():
        if key not in answers:
            raise ValueError(f"unknown answer key: {key}")
        if key in _INT_KEYS:
            answers[key] = int(value)
        else:
            answers[key] = value
    return answers


def collect_answers(answers_file: str | None) -> dict[str, Any]:
    """Return answers, prompting interactively unless an answers file is given."""
    if answers_file:
        answers = _load_answers_file(answers_file)
        print(_style(f"  using answers from {answers_file} (prompts skipped)", _DIM))
        return answers

    a = default_answers()
    print()
    print(_style("── Target ───────────────────────────────────────────────", _CYAN, _BOLD))
    a["target_host"] = _ask("Hostname for this Pi (inventory + host_vars)", a["target_host"])
    a["target_ip"] = _ask("IP or resolvable address (blank = use hostname)", a["target_ip"])
    a["ssh_user"] = _ask("SSH user for Ansible", a["ssh_user"])
    a["service_user"] = _ask("systemd service user", a["service_user"])
    a["camera_count"] = _ask("Number of cameras (1 or 2)", a["camera_count"], validate=_int_in_range(1, 2))

    print()
    print(_style("── Paths ─────────────────────────────────────────────────", _CYAN, _BOLD))
    a["app_dir"] = _ask("App install directory", a["app_dir"])
    a["media_dir"] = _ask("Captured media directory", a["media_dir"])

    print()
    print(_style("── Application ───────────────────────────────────────────", _CYAN, _BOLD))
    a["server_host"] = _ask("Web/API listen host", a["server_host"])
    a["server_port"] = _ask("Web/API port", a["server_port"], validate=_int_in_range(1, 65535))
    resolution = _one_of({"1920x1080": (1920, 1080), "1280x720": (1280, 720)})
    w, h = _ask("Sensor resolution", "1920x1080", validate=resolution)
    a["mode_width"], a["mode_height"] = w, h
    a["mode_bit_depth"] = _ask("RAW bit depth (10 or 12)", a["mode_bit_depth"], validate=_one_of({"10": 10, "12": 12}))
    a["mode_framerate"] = _ask("Framerate (30 or 60)", a["mode_framerate"], validate=_one_of({"30": 30, "60": 60}))
    levels = {"DEBUG": "DEBUG", "INFO": "INFO", "WARNING": "WARNING", "ERROR": "ERROR"}
    a["log_level"] = _ask("Logging level", a["log_level"], validate=_one_of(levels))

    print()
    print(_style("── MQTT (telemetry; blank host disables) ─────────────────", _CYAN, _BOLD))
    a["mqtt_host"] = _ask("MQTT broker host", a["mqtt_host"])
    a["mqtt_port"] = _ask("MQTT broker port", a["mqtt_port"], validate=_int_in_range(1, 65535))
    a["mqtt_username"] = _ask("MQTT username", a["mqtt_username"])
    a["mqtt_password"] = _ask("MQTT password", secret=True)

    print()
    print(_style("── OpenTelemetry (blank endpoint disables) ───────────────", _CYAN, _BOLD))
    a["otel_endpoint"] = _ask("OTLP endpoint (http://host:4318)", a["otel_endpoint"])
    a["otel_service_name"] = _ask("OTel service name", a["otel_service_name"])
    a["otel_headers"] = _ask("OTLP headers (e.g. 'Authorization=Bearer xxx')", a["otel_headers"])
    a["otel_certificate"] = _ask(
        "CA cert path on the Pi for the OTLP endpoint (blank = system CA)",
        a["otel_certificate"],
    )

    return a


# ---------------------------------------------------------------------------
# Rendering (pure functions, unit-tested)
# ---------------------------------------------------------------------------

def _host_vars_dict(answers: dict[str, Any]) -> dict[str, Any]:
    cameras = [{"id": 0, "name": "cam0"}]
    if int(answers["camera_count"]) >= 2:
        cameras.append({"id": 1, "name": "cam1"})
    return {
        "imx462_camera_count": int(answers["camera_count"]),
        "imx462_app_dir": answers["app_dir"],
        "imx462_venv": "{{ imx462_app_dir }}/venv",
        "imx462_media_dir": answers["media_dir"],
        "imx462_service_user": answers["service_user"],
        "imx462_config": {
            "server": {"host": answers["server_host"], "port": int(answers["server_port"])},
            "cameras": cameras,
            "default_mode": {
                "width": int(answers["mode_width"]),
                "height": int(answers["mode_height"]),
                "bit_depth": int(answers["mode_bit_depth"]),
                "framerate": int(answers["mode_framerate"]),
            },
            "capture": {
                "output_dir": answers["media_dir"],
                "photo_format": "jpg",
                "video_format": "mp4",
            },
            "mqtt": {
                "topics": {
                    "events": "imx462/events",
                    "status": "imx462/status",
                    "metrics": "imx462/metrics",
                },
                "heartbeat_interval_seconds": 30,
            },
            "otel": {
                "endpoint": answers["otel_endpoint"],
                "service_name": answers["otel_service_name"],
                "metric_export_interval_ms": 30000,
            },
            "logging": {"level": answers["log_level"]},
        },
        "imx462_env": {
            "MQTT_HOST": answers["mqtt_host"],
            "MQTT_PORT": str(answers["mqtt_port"]),
            "MQTT_USERNAME": answers["mqtt_username"],
            "MQTT_PASSWORD": answers["mqtt_password"],
            "OTEL_EXPORTER_OTLP_HEADERS": answers["otel_headers"],
            "OTEL_EXPORTER_OTLP_CERTIFICATE": answers["otel_certificate"],
        },
    }


_SAFE_SCALAR = re.compile(r"^[A-Za-z0-9_./@+\-]+$")
_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if value == "" or not _SAFE_SCALAR.match(value) or _NUMERIC.match(value):
            return "'" + value.replace("'", "''") + "'"
        return value
    raise TypeError(f"unsupported YAML scalar type: {type(value)}")


def _dump_dict(data: dict[str, Any], indent: int) -> str:
    pad = "  " * indent
    lines = []
    for key, value in data.items():
        k = _scalar(key)
        if isinstance(value, dict):
            if value:
                lines.append(f"{pad}{k}:")
                lines.append(_dump_yaml(value, indent + 1))
            else:
                lines.append(f"{pad}{k}: {{}}")
        elif isinstance(value, list):
            if value:
                lines.append(f"{pad}{k}:")
                lines.append(_dump_yaml(value, indent + 1))
            else:
                lines.append(f"{pad}{k}: []")
        else:
            lines.append(f"{pad}{k}: {_scalar(value)}")
    return "\n".join(lines)


def _dump_list_item(items: list[tuple[str, Any]], indent: int) -> list[str]:
    pad = "  " * indent
    k0, v0 = items[0]
    lines = []
    if isinstance(v0, (dict, list)) and v0:
        lines.append(f"{pad}- {_scalar(k0)}:")
        lines.append(_dump_yaml(v0, indent + 2))
    else:
        lines.append(f"{pad}- {_scalar(k0)}: {_scalar(v0)}")
    for k, v in items[1:]:
        if isinstance(v, (dict, list)) and v:
            lines.append(f"{pad}  {_scalar(k)}:")
            lines.append(_dump_yaml(v, indent + 2))
        else:
            lines.append(f"{pad}  {_scalar(k)}: {_scalar(v)}")
    return lines


def _dump_list(data: list[Any], indent: int) -> str:
    pad = "  " * indent
    lines = []
    for item in data:
        if isinstance(item, dict):
            lines.extend(_dump_list_item(list(item.items()), indent))
        else:
            lines.append(f"{pad}- {_scalar(item)}")
    return "\n".join(lines)


def _dump_yaml(data: Any, indent: int = 0) -> str:
    """Minimal YAML dumper sufficient for the host_vars schema."""
    if isinstance(data, dict):
        return _dump_dict(data, indent)
    if isinstance(data, list):
        return _dump_list(data, indent)
    return "  " * indent + _scalar(data)


def render_inventory(answers: dict[str, Any]) -> str:
    host = answers["target_host"]
    addr = answers["target_ip"] or host
    return (
        "[imx462]\n"
        f"{host} ansible_host={addr} ansible_user={answers['ssh_user']}\n"
        "\n"
        "[imx462:vars]\n"
        "ansible_python_interpreter=/usr/bin/python3\n"
        f"imx462_camera_count={int(answers['camera_count'])}\n"
    )


def render_host_vars(answers: dict[str, Any]) -> str:
    return _dump_yaml(_host_vars_dict(answers)) + "\n"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_outputs(
    answers: dict[str, Any],
    out_dir: Path,
    force: bool,
    interactive: bool,
) -> list[Path]:
    """Write inventory.ini + host_vars/<host>.yml atomically. Returns paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    host_vars_dir = out_dir / "host_vars"
    host_vars_dir.mkdir(parents=True, exist_ok=True)

    files = {
        out_dir / "inventory.ini": render_inventory(answers),
        host_vars_dir / f"{answers['target_host']}.yml": render_host_vars(answers),
    }

    written: list[Path] = []
    for path, content in files.items():
        if path.exists() and not force:
            if interactive:
                answer = input(_style(f"  {path} exists — overwrite? [y/N] ", _YELLOW)).strip().lower()
                if answer not in ("y", "yes"):
                    print(_style(f"  skipping {path}", _DIM))
                    continue
            else:
                raise FileExistsError(f"{path} already exists (use --force to overwrite)")
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(answers: dict[str, Any]) -> None:
    rows = [
        ("hostname", answers["target_host"]),
        ("address", answers["target_ip"] or answers["target_host"]),
        ("ssh user", answers["ssh_user"]),
        ("service user", answers["service_user"]),
        ("cameras", answers["camera_count"]),
        ("mode", f"{answers['mode_width']}x{answers['mode_height']} RAW{answers['mode_bit_depth']} @{answers['mode_framerate']}fps"),
        ("media dir", answers["media_dir"]),
        ("mqtt", answers["mqtt_host"] or "disabled"),
        ("otel", answers["otel_endpoint"] or "disabled"),
    ]
    for label, value in rows:
        print(_style(f"  {label:<14}", _DIM) + _style(str(value), _GREEN))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the local Ansible inventory + host_vars for a fresh Raspberry Pi."
    )
    parser.add_argument(
        "--answers-file",
        help="JSON file with answers (skips prompts; for scripting/CI)",
    )
    parser.add_argument(
        "--out-dir",
        default="ansible",
        help="output directory (default: ansible)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing files without asking",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the final confirmation prompt",
    )
    args = parser.parse_args(argv)

    print()
    print(_box("IMX462 RPi Controller — Setup Configurator"))
    print()

    try:
        answers = collect_answers(args.answers_file)
    except (OSError, ValueError) as exc:
        print(_style(f"  ✗ {exc}", _RED), file=sys.stderr)
        return 1

    print()
    print(_style("── Summary ──────────────────────────────────────────────", _CYAN, _BOLD))
    _print_summary(answers)

    if not args.yes and sys.stdin.isatty():
        confirm = input(_style("Write these files? [y/N] ", _BOLD)).strip().lower()
        if confirm not in ("y", "yes"):
            print(_style("Aborted.", _YELLOW))
            return 0

    try:
        written = write_outputs(answers, Path(args.out_dir), args.force, sys.stdin.isatty())
    except FileExistsError as exc:
        print(_style(f"  ✗ {exc}", _RED), file=sys.stderr)
        return 1

    if not written:
        print(_style("Nothing written.", _YELLOW))
        return 0
    print(_style("  ✓ wrote:", _GREEN))
    for path in written:
        print(_style(f"    {path}", _GREEN))
    print()
    print(_style("  Next:", _CYAN, _BOLD))
    print(_style("    ansible-playbook -i ansible/inventory.ini ansible/playbook.yml", _GREEN))
    print(_style("    ssh <host> sudo reboot   # activates the camera overlay", _GREEN))
    return 0


if __name__ == "__main__":
    sys.exit(main())
