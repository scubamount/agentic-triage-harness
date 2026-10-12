"""Tests for tools/intervention-ledger.py — the mind-the-gap metric."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
LEDGER = TOOLS / "intervention-ledger.py"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "interventions.jsonl"
    monkeypatch.setenv("INTERVENTION_LEDGER", str(path))
    return path


def run(*args):
    return subprocess.run(
        [sys.executable, str(LEDGER), *args],
        capture_output=True, text=True,
    )


def test_add_writes_one_entry_with_all_fields(ledger):
    proc = run("add", "constraint-supplied", "sco-core#91", "version pin came from the human")
    assert proc.returncode == 0, proc.stderr
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["type"] == "constraint-supplied"
    assert entry["case"] == "sco-core#91"
    assert entry["source"] == "operator"
    assert entry["ts"].endswith("+00:00")


def test_add_creates_parent_dirs(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "dir" / "ledger.jsonl"
    monkeypatch.setenv("INTERVENTION_LEDGER", str(path))
    proc = run("add", "citation-demanded", "case-x")
    assert proc.returncode == 0
    assert path.exists()


def test_add_rejects_unknown_type(ledger):
    proc = run("add", "vibes-checked", "case-x")
    assert proc.returncode == 2
    assert not ledger.exists()


def test_trend_buckets_by_month(ledger):
    ts = "2026-09-15T10:00:00+00:00"
    entries = [
        {"ts": ts, "type": "constraint-supplied", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-09-20T10:00:00+00:00", "type": "citation-demanded", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-10-02T10:00:00+00:00", "type": "constraint-supplied", "case": "b", "note": "", "source": "operator"},
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    proc = run("trend", "--months", "3")
    assert proc.returncode == 0
    assert "2026-09" in proc.stdout and "2026-10" in proc.stdout
    # September had two interventions, October one -> trajectory down.
    assert "down" in proc.stdout
    assert "constraint-supplied:1" in proc.stdout


def test_trend_on_empty_ledger_is_not_an_error(ledger):
    proc = run("trend")
    assert proc.returncode == 0
    assert "no interventions" in proc.stdout


def test_list_filters_by_type_and_limit(ledger):
    for i, t in enumerate(["verdict-flipped", "citation-demanded", "verdict-flipped"]):
        run("add", t, f"case-{i}")
    proc = run("list", "--type", "verdict-flipped")
    assert proc.returncode == 0
    assert "case-0" in proc.stdout and "case-2" in proc.stdout
    assert "case-1" not in proc.stdout
    proc = run("list", "--limit", "1")
    assert "case-2" in proc.stdout and "case-0" not in proc.stdout
