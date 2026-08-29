#!/usr/bin/env python3
"""Aggregate JUnit XML test results into a markdown summary.

Used by the CI ``report`` job: parses every JUnit XML file under a directory,
aggregates pass/fail/skip counts across matrix legs, writes a markdown summary,
and exports the counts via ``GITHUB_OUTPUT`` for the PR comment step.

Stdlib-only (Python 3.9+).
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_suite(suite: ET.Element) -> dict[str, Any]:
    """Counts + failed test names for a single ``<testsuite>`` element."""
    tests = int(suite.get("tests", 0) or 0)
    failed = int(suite.get("failures", 0) or 0) + int(suite.get("errors", 0) or 0)
    skipped = int(suite.get("skipped", 0) or 0)
    failures: list[str] = []
    for case in suite.iter("testcase"):
        if any(child.tag in ("failure", "error") for child in case):
            name = case.get("name", "")
            classname = case.get("classname", "")
            failures.append(f"{classname}::{name}" if classname else name)
    return {"tests": tests, "failed": failed, "skipped": skipped, "failures": failures}


def parse_junit(path: Path) -> dict[str, Any]:
    """Parse a JUnit XML file (root ``testsuites`` or ``testsuite``)."""
    root = ET.parse(path).getroot()
    if root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
    elif root.tag == "testsuite":
        suites = [root]
    else:
        raise ValueError(f"{path}: unexpected root element {root.tag!r}")

    agg: dict[str, Any] = {"tests": 0, "failed": 0, "skipped": 0, "failures": []}
    for suite in suites:
        part = _parse_suite(suite)
        agg["tests"] += part["tests"]
        agg["failed"] += part["failed"]
        agg["skipped"] += part["skipped"]
        agg["failures"].extend(part["failures"])
    return agg


def build_summary(paths: list[Path]) -> dict[str, Any]:
    """Aggregate all JUnit files into a single summary dict."""
    total: dict[str, Any] = {"tests": 0, "failed": 0, "skipped": 0, "failures": []}
    for path in paths:
        part = parse_junit(path)
        total["tests"] += part["tests"]
        total["failed"] += part["failed"]
        total["skipped"] += part["skipped"]
        total["failures"].extend(part["failures"])
    total["passed"] = total["tests"] - total["failed"] - total["skipped"]
    total["conclusion"] = "success" if total["failed"] == 0 else "failure"
    return total


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(summary: dict[str, Any]) -> str:
    icon = "✅" if summary["conclusion"] == "success" else "❌"
    lines = [
        "<!-- ci-test-results -->",
        "",
        f"## Test results — {icon} {summary['conclusion']}",
        "",
        f"- **Passed:** {summary['passed']}",
        f"- **Failed:** {summary['failed']}",
        f"- **Skipped:** {summary['skipped']}",
        f"- **Total:** {summary['tests']}",
    ]
    if summary["failures"]:
        lines.append("")
        lines.append("### Failed tests")
        for name in summary["failures"][:20]:
            lines.append(f"- `{name}`")
        remaining = len(summary["failures"]) - 20
        if remaining > 0:
            lines.append(f"- … and {remaining} more")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate JUnit XML results into a markdown summary.")
    parser.add_argument("--junit-dir", required=True, help="directory containing JUnit XML files")
    parser.add_argument("--output", help="write the markdown summary to this file (default: stdout)")
    args = parser.parse_args(argv)

    junit_dir = Path(args.junit_dir)
    paths = sorted(junit_dir.glob("*.xml"))
    if not paths:
        print(f"no JUnit XML files found in {junit_dir}", file=sys.stderr)
        return 1

    summary = build_summary(paths)
    markdown = render_markdown(summary)

    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    outputs = {
        "conclusion": summary["conclusion"],
        "passed": str(summary["passed"]),
        "failed": str(summary["failed"]),
        "skipped": str(summary["skipped"]),
        "tests": str(summary["tests"]),
    }
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.writelines(f"{key}={value}\n" for key, value in outputs.items())
    else:
        for key, value in outputs.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
