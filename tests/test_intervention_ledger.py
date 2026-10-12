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
    entries = [
        {"ts": "2026-09-15T10:00:00+00:00", "type": "constraint-supplied", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-09-20T10:00:00+00:00", "type": "citation-demanded", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-10-02T10:00:00+00:00", "type": "constraint-supplied", "case": "b", "note": "", "source": "operator"},
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    proc = run("trend", "--months", "3")
    assert proc.returncode == 0
    assert "2026-09" in proc.stdout and "2026-10" in proc.stdout
    # September: two open interventions on ONE case (2.00/case); October: one
    # on one case (1.00/case) -> per-case trajectory down.
    assert "down" in proc.stdout
    assert "constraint-supplied:1" in proc.stdout


def test_trend_reports_per_case_not_raw_totals(ledger):
    # Reviewer counterexample (2026-10-12): two months with one intervention
    # per case each must read FLAT, not "down" — the metric is interventions
    # per case, and monthly totals say nothing about per-case performance.
    entries = [
        {"ts": "2026-09-10T10:00:00+00:00", "type": "constraint-supplied", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-09-11T10:00:00+00:00", "type": "citation-demanded", "case": "b", "note": "", "source": "operator"},
        {"ts": "2026-10-05T10:00:00+00:00", "type": "verdict-flipped", "case": "c", "note": "", "source": "operator"},
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    proc = run("trend", "--months", "3")
    assert proc.returncode == 0
    assert "flat" in proc.stdout
    assert "1.00" in proc.stdout


def test_policy_codified_is_not_an_open_intervention(ledger):
    entries = [
        {"ts": "2026-10-01T10:00:00+00:00", "type": "constraint-supplied", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-10-02T10:00:00+00:00", "type": "policy-codified", "case": "a", "note": "", "source": "operator"},
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    proc = run("trend", "--months", "3")
    assert proc.returncode == 0
    # October row: total 2, open 1, one open case -> open/case 1.00.
    row = [l for l in proc.stdout.splitlines() if l.startswith("2026-10")][0]
    fields = row.split()
    assert fields[1] == "2" and fields[2] == "1" and fields[3] == "1"


def test_policy_only_case_never_enters_the_denominator(ledger):
    # Reviewer counterexample (2026-10-12): codifying one case's policy in a
    # later month must not manufacture a downward trend. September: one open
    # intervention on one case. October: one open on another case PLUS a
    # policy-codified-only case. Per-case rate must read flat at 1.00.
    entries = [
        {"ts": "2026-09-10T10:00:00+00:00", "type": "constraint-supplied", "case": "a", "note": "", "source": "operator"},
        {"ts": "2026-10-05T10:00:00+00:00", "type": "verdict-flipped", "case": "b", "note": "", "source": "operator"},
        {"ts": "2026-10-06T10:00:00+00:00", "type": "policy-codified", "case": "c", "note": "", "source": "operator"},
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    proc = run("trend", "--months", "3")
    assert proc.returncode == 0
    assert "flat" in proc.stdout
    row = [l for l in proc.stdout.splitlines() if l.startswith("2026-10")][0]
    fields = row.split()
    assert fields[2] == "1" and fields[3] == "1"  # open=1, open-cases=1


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
