from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ci_summary

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3" failures="1" errors="0" skipped="1" time="0.1">
    <testcase classname="tests.test_foo" name="test_ok" time="0.01"/>
    <testcase classname="tests.test_foo" name="test_fail" time="0.02">
      <failure message="boom">traceback</failure>
    </testcase>
    <testcase classname="tests.test_foo" name="test_skip" time="0.0">
      <skipped message="skip"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def _write_sample(tmp_path, content=SAMPLE):
    path = tmp_path / "a.xml"
    path.write_text(content)
    return path


def test_parse_junit(tmp_path):
    path = _write_sample(tmp_path)
    part = ci_summary.parse_junit(path)
    assert part["tests"] == 3
    assert part["failed"] == 1
    assert part["skipped"] == 1
    assert part["failures"] == ["tests.test_foo::test_fail"]


def test_parse_junit_counts_errors_as_failed(tmp_path):
    path = _write_sample(
        tmp_path,
        SAMPLE.replace('<failure message="boom">traceback</failure>', '<error message="boom"/>'),
    )
    part = ci_summary.parse_junit(path)
    assert part["failed"] == 1
    assert part["failures"] == ["tests.test_foo::test_fail"]


def test_build_summary_failure(tmp_path):
    summary = ci_summary.build_summary([_write_sample(tmp_path)])
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["conclusion"] == "failure"


def test_build_summary_success(tmp_path):
    content = SAMPLE.replace('failures="1"', 'failures="0"').replace(
        '<failure message="boom">traceback</failure>', ""
    )
    summary = ci_summary.build_summary([_write_sample(tmp_path, content)])
    assert summary["conclusion"] == "success"
    assert summary["passed"] == 2
    assert summary["failures"] == []


def test_build_summary_aggregates_multiple_files(tmp_path):
    a = _write_sample(tmp_path)
    b = tmp_path / "b.xml"
    b.write_text(SAMPLE.replace('failures="1"', 'failures="0"').replace(
        '<failure message="boom">traceback</failure>', ""
    ))
    summary = ci_summary.build_summary([a, b])
    assert summary["tests"] == 6
    assert summary["passed"] == 3
    assert summary["failed"] == 1
    assert summary["skipped"] == 2


def test_render_markdown():
    summary = {"passed": 2, "failed": 1, "skipped": 1, "tests": 4, "failures": ["a::b"], "conclusion": "failure"}
    md = ci_summary.render_markdown(summary)
    assert "<!-- ci-test-results -->" in md
    assert "❌" in md
    assert "- **Passed:** 2" in md
    assert "- **Failed:** 1" in md
    assert "`a::b`" in md


def test_render_markdown_success_icon():
    summary = {"passed": 3, "failed": 0, "skipped": 0, "tests": 3, "failures": [], "conclusion": "success"}
    md = ci_summary.render_markdown(summary)
    assert "✅" in md
    assert "Failed tests" not in md


def test_main_writes_summary(tmp_path, monkeypatch):
    _write_sample(tmp_path)
    out = tmp_path / "summary.md"
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    rc = ci_summary.main(["--junit-dir", str(tmp_path), "--output", str(out)])
    assert rc == 0
    assert out.exists()
    assert "Test results" in out.read_text()


def test_main_errors_without_xml(tmp_path, capsys):
    rc = ci_summary.main(["--junit-dir", str(tmp_path)])
    assert rc == 1
    assert "no JUnit XML files" in capsys.readouterr().err
