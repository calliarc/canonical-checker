from __future__ import annotations

import csv
import json

import pytest
from typer.testing import CliRunner

from canonical_checker import __version__, cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_network(monkeypatch, fake_site):
    monkeypatch.setattr(cli, "TRANSPORT", fake_site.transport)


def invoke(*args: str):
    return runner.invoke(cli.app, ["https://example.com/", "--delay", "0", *args])


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_default_exit_code_is_zero_and_table_printed():
    result = invoke("--max-rows", "5")
    assert result.exit_code == 0, result.output
    assert "doubled-host-path" in result.output
    assert "Summary" in result.output


def test_fail_on_error_exits_1():
    assert invoke("--fail-on", "error", "--quiet").exit_code == 1


def test_fail_on_respects_threshold(fake_site):
    # A clean one-page site only has nothing to report.
    fake_site.routes["https://example.com/"] = (
        200,
        {"content-type": "text/html"},
        b'<html><head><link rel="canonical" href="https://example.com/"></head></html>',
    )
    assert invoke("--fail-on", "info").exit_code == 0


def test_csv_and_json_outputs(tmp_path):
    csv_file = tmp_path / "out" / "report.csv"
    json_file = tmp_path / "report.json"
    result = invoke("--csv", str(csv_file), "--json", str(json_file), "--quiet")
    assert result.exit_code == 0, result.output

    rows = list(csv.DictReader(csv_file.open(encoding="utf-8")))
    assert {"severity", "code", "url", "source", "detail", "fix"} <= set(rows[0])
    assert any(r["code"] == "raw-host-href" and r["source"] == "https://example.com/" for r in rows)

    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["version"] == __version__
    assert data["summary"]["error"] > 0
    assert len(data["issues"]) == len(rows)


def test_json_to_stdout():
    result = invoke("--json", "-", "--quiet")
    assert json.loads(result.stdout)["site"] == "https://example.com"


def test_min_severity_filters_output(tmp_path):
    out = tmp_path / "r.json"
    invoke("--json", str(out), "--min-severity", "error", "--quiet")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["issues"] and {i["severity"] for i in data["issues"]} == {"error"}


def test_unreachable_start_exits_2(fake_site):
    fake_site.routes["https://example.com/robots.txt"] = (500, {}, b"")
    result = invoke()
    assert result.exit_code == 2
