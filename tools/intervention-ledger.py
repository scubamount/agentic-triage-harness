#!/usr/bin/env python3
"""Intervention ledger for agentic debugging/triage workflows.

Framework (from "How to effectively debug when you no longer understand the
code", Cindy Sridharan, 2026): every human intervention in an agent-run
investigation is a gap in the process. The number of interventions per case is
the most honest measure of how agent-native a workflow is; the goal is for it
to trend toward zero, and each intervention should become policy so it never
repeats.

This tool records interventions and reports the trend.

Entry shape (one JSON object per line):
    {"ts": "<ISO-8601>", "type": "<type>", "case": "<id>", "note": "...",
     "source": "operator|reviewer|other"}

Types (closed set; unknown types are rejected so the trend stays countable):
    control-supplied       a human supplied the control/variable comparison
    constraint-supplied    a human supplied a constraint (a fact, a version, a
                           config state) the agent should have gathered
    citation-demanded      a human demanded citations for claims
    hypothesis-rejected    a human rejected a hypothesis the agent was pursuing
    repro-parity-demand    a human demanded repro-vs-report signal parity
    verdict-flipped        a human overturned an agent verdict
    policy-codified        an intervention was turned into standing policy
                           (the desired terminal state for every intervention)

Usage:
    python3 intervention-ledger.py add <type> <case> [note] [--source SRC]
    python3 intervention-ledger.py list [--type T] [--limit N]
    python3 intervention-ledger.py trend [--months N]

Ledger location: $INTERVENTION_LEDGER, else ./interventions.jsonl in the
current working directory.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

TYPES = {
    "control-supplied",
    "constraint-supplied",
    "citation-demanded",
    "hypothesis-rejected",
    "repro-parity-demand",
    "verdict-flipped",
    "policy-codified",
}

DEFAULT_LEDGER = Path.cwd() / "interventions.jsonl"


def ledger_path():
    return Path(os.environ.get("INTERVENTION_LEDGER", DEFAULT_LEDGER))


def add(entry_type, case, note="", source="operator"):
    if entry_type not in TYPES:
        print(
            f"intervention-ledger: unknown type '{entry_type}'; "
            f"allowed: {', '.join(sorted(TYPES))}",
            file=sys.stderr,
        )
        return 2
    if not case:
        print("intervention-ledger: case id is required", file=sys.stderr)
        return 2
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "type": entry_type,
        "case": case,
        "note": note,
        "source": source,
    }
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")
    print(f"logged {entry_type} for case {case} -> {path}")
    return 0


def load_entries():
    path = ledger_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def list_entries(entry_type=None, limit=None):
    entries = load_entries()
    if entry_type:
        entries = [e for e in entries if e.get("type") == entry_type]
    if limit:
        entries = entries[-limit:]
    for e in entries:
        print(f"{e['ts']}  {e['type']:<22} {e['case']:<28} {e.get('note', '')}")
    print(f"({len(entries)} entr{'y' if len(entries) == 1 else 'ies'})")
    return 0


def trend(months=6):
    entries = load_entries()
    buckets = {}
    for e in entries:
        try:
            ts = dt.datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        key = ts.strftime("%Y-%m")
        b = buckets.setdefault(key, {"total": 0, "open": 0, "codified": 0,
                                     "open_cases": set(), "types": {}})
        b["total"] += 1
        if e.get("type") == "policy-codified":
            b["codified"] += 1
        else:
            b["open"] += 1
            # Only cases with at least one OPEN intervention count in the
            # denominator: a policy-only case has nothing left to steer and
            # must not dilute the per-case rate.
            b["open_cases"].add(e.get("case", ""))
        b["types"][e["type"]] = b["types"].get(e["type"], 0) + 1
    recent = sorted(buckets)[-months:]
    if not recent:
        print("no interventions recorded; nothing to trend")
        return 0

    def per_case(b):
        return b["open"] / len(b["open_cases"]) if b["open_cases"] else 0.0

    print(f"{'month':<9} {'total':>5} {'open':>5} {'cases':>6} {'open/case':>10}  breakdown")
    for key in recent:
        b = buckets[key]
        breakdown = ", ".join(f"{t}:{n}" for t, n in sorted(b["types"].items()))
        print(f"{key:<9} {b['total']:>5} {b['open']:>5} {len(b['open_cases']):>6} "
              f"{per_case(b):>10.2f}  {breakdown}")
    # The autonomy metric is open interventions PER CASE, not raw monthly
    # totals: two months can each log one intervention per case and be flat
    # even when one month covered more work.
    first, last = recent[0], recent[-1]
    if first != last:
        delta = per_case(buckets[last]) - per_case(buckets[first])
        direction = "down" if delta < 0 else "up" if delta > 0 else "flat"
        print(f"trend (open interventions per case): {direction} "
              f"({first} {per_case(buckets[first]):.2f} -> {last} {per_case(buckets[last]):.2f})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="append an intervention")
    p_add.add_argument("type", choices=sorted(TYPES))
    p_add.add_argument("case")
    p_add.add_argument("note", nargs="?", default="")
    p_add.add_argument("--source", default="operator")

    p_list = sub.add_parser("list", help="show entries")
    p_list.add_argument("--type", choices=sorted(TYPES))
    p_list.add_argument("--limit", type=int)

    p_trend = sub.add_parser("trend", help="monthly totals and trajectory")
    p_trend.add_argument("--months", type=int, default=6)

    args = ap.parse_args(argv)
    if args.cmd == "add":
        return add(args.type, args.case, args.note, args.source)
    if args.cmd == "list":
        return list_entries(args.type, args.limit)
    return trend(args.months)


if __name__ == "__main__":
    sys.exit(main())
