"""Tests for tools/matrix.py — the hypotheses-by-fact matrix.

Red-arm discipline: the latency case pins the article's exact teaching (the
P99 signal is weak because every hypothesis fits it; the DNS delta is strong
because only one does). The memory-leak case pins the split-then-combine path.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
MATRIX = TOOLS / "matrix.py"

LATENCY_CASE = {
    "case_id": "latency-p99-regression",
    "variable": "feature flag enabled on client and server (5000-host cluster)",
    "control": "same code with feature flag disabled on client and server",
    "facts": [
        {"id": "f1", "observation": "client DNS lookup returns ~400 addresses",
         "seen_in": "variable"},
        {"id": "f2", "observation": "TCP handshake time equal in variable and control",
         "seen_in": "both"},
        {"id": "f3", "observation": "server-side P99 latency regressed",
         "seen_in": "variable"},
    ],
    "hypotheses": [
        {"id": "h1", "text": "server reloads TLS cert on every RPC",
         "consistent_with": ["f2", "f3"]},
        {"id": "h2", "text": "new mTLS codepath bypasses the sharded client",
         "consistent_with": ["f1", "f2", "f3"]},
    ],
}

MEMLEAK_CASE = {
    "case_id": "memory-leak-no-auth",
    "variable": "tool run with no valid auth credentials in a container",
    "control": "last known good version, same invocation",
    "facts": [
        {"id": "f1", "observation": "leak first appeared in a recent version",
         "seen_in": "variable"},
        {"id": "f2", "observation": "amortization is opt-in and the user left it off",
         "seen_in": "variable"},
        {"id": "f3", "observation": "heap profile points at the plain recursive call",
         "seen_in": "variable"},
        {"id": "f4", "observation": "leak only when no credentials are supplied up front",
         "seen_in": "variable"},
    ],
    "hypotheses": [
        {"id": "h1", "text": "long-standing state machine bug; bound the retries",
         "consistent_with": ["f3", "f4"]},
        {"id": "h2", "text": "amortization work caused the leak",
         "consistent_with": ["f1", "f3"]},
        {"id": "h3", "text": "process-wide cache re-enters a single-use state machine",
         "consistent_with": ["f1", "f2", "f3", "f4"]},
    ],
}


def run_matrix(case, *extra):
    path = Path(str(id(case)) + ".json")
    path.write_text(json.dumps(case), encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(MATRIX), str(path), *extra],
            capture_output=True, text=True,
        )
    finally:
        path.unlink(missing_ok=True)
    return proc


def test_latency_dns_is_strong_p99_is_weak():
    proc = run_matrix(LATENCY_CASE, "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    # DNS delta: only the routing hypothesis fits it -> strong.
    assert out["signal_strength"]["f1"] == 1
    assert "f1" in out["strong_signals"]
    # P99: both hypotheses fit it -> weak, cannot steer.
    assert out["signal_strength"]["f3"] == 2
    assert "f3" not in out["strong_signals"]
    # The all-consistent row is the routing hypothesis.
    assert out["candidates"] == ["h2"]


def test_latency_noise_is_marked_elimination_only():
    proc = run_matrix(LATENCY_CASE, "--json")
    out = json.loads(proc.stdout)
    assert out["noise"] == ["f2"]
    assert out["unexplained_facts"] == []


def test_control_only_fact_is_never_a_strong_signal():
    # Reviewer counterexample (2026-10-12): a fact seen only in the control was
    # reported as both noise and a strong signal. Strength means "steers the
    # investigation", and only variable-present facts can steer.
    case = json.loads(json.dumps(LATENCY_CASE))
    case["facts"].append(
        {"id": "f5", "observation": "something only the control shows", "seen_in": "control"}
    )
    # No hypothesis is consistent with f5 (it discriminates nothing about the
    # variable), so it is also unexplained.
    proc = run_matrix(case, "--json")
    out = json.loads(proc.stdout)
    assert "f5" in out["noise"]
    assert "f5" not in out["strong_signals"]
    assert "f5" in out["unexplained_facts"]


def test_memleak_combined_hypothesis_is_the_only_candidate():
    proc = run_matrix(MEMLEAK_CASE, "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["candidates"] == ["h3"]
    # The two earlier theories each miss facts; h1 misses f1+f2, h2 misses f2+f4.
    assert "f1" in out["contradicted_facts"]["h1"]
    assert "f4" in out["contradicted_facts"]["h2"]
    assert "split" in out["hint"] or "candidate" in out["hint"]


def test_memleak_split_halves_alone_leave_no_candidate():
    case = json.loads(json.dumps(MEMLEAK_CASE))
    case["hypotheses"] = [
        {"id": "h4", "text": "process-wide cache, default on", "consistent_with": ["f1", "f2", "f4"]},
        {"id": "h5", "text": "single-use state machine piles up frames", "consistent_with": ["f3", "f4"]},
    ]
    proc = run_matrix(case, "--json")
    out = json.loads(proc.stdout)
    assert out["candidates"] == []
    assert "split" in out["hint"]
    assert "combine" in out["hint"]


def test_human_readable_output_runs_clean():
    proc = run_matrix(LATENCY_CASE)
    assert proc.returncode == 0
    assert "STRONG" in proc.stdout
    assert "h2" in proc.stdout


def test_human_readable_labels_match_json_strong_signals():
    # Reviewer counterexample (2026-10-12): the default CLI printed STRONG for
    # a control-only fact while the JSON correctly excluded it. The display
    # must derive its labels from strong_signals, not recompute them.
    case = json.loads(json.dumps(LATENCY_CASE))
    case["facts"].append(
        {"id": "f5", "observation": "something only the control shows", "seen_in": "control"}
    )
    proc = run_matrix(case)
    assert proc.returncode == 0
    f5_line = [l for l in proc.stdout.splitlines() if l.strip().startswith("f5:")][0]
    assert "STRONG" not in f5_line
    assert "weak" in f5_line


def test_unknown_fact_reference_is_rejected():
    case = json.loads(json.dumps(LATENCY_CASE))
    case["hypotheses"][0]["consistent_with"].append("f99")
    proc = run_matrix(case, "--json")
    assert proc.returncode == 2
    assert "f99" in proc.stderr


def test_duplicate_fact_ids_rejected():
    case = json.loads(json.dumps(LATENCY_CASE))
    case["facts"].append(dict(case["facts"][0]))
    proc = run_matrix(case, "--json")
    assert proc.returncode == 2
    assert "unique" in proc.stderr
