#!/usr/bin/env python3
"""Hypotheses-by-fact matrix for agentic debugging.

Framework (from "How to effectively debug when you no longer understand the
code", Cindy Sridharan, 2026): debugging is a constraint-satisfaction problem.
The factual tier holds immutable gathered facts; the derivative tier holds
hypotheses. A hypothesis is valid only if it is consistent with EVERY fact.

This tool loads a triage-case.json and reports:
  - per-fact signal strength: how many hypotheses remain consistent with the
    fact (few = strong; a fact almost any hypothesis satisfies is weak and
    cannot steer an investigation)
  - candidate hypotheses: rows consistent with all facts
  - unexplained facts: no hypothesis is consistent with them (the agent must
    split/merge/combine hypotheses or gather more facts, never discard a fact)
  - contradicted facts per hypothesis

Fact semantics (seen_in):
  "variable"  -> high-fidelity signal (present in the broken case, absent from
                 the control)
  "both"      -> noise: present in variable and control; useful for elimination
                 only, never for steering
  "control"   -> recorded for completeness; treated as noise

Hypothesis semantics:
  consistent_with lists the fact ids the hypothesis does not contradict. Every
  fact NOT listed counts as contradicted. A hypothesis is a candidate only when
  it is consistent with all facts.

Usage:
    python3 matrix.py case.json [--json]
"""
import argparse
import json
import sys

NOISE = {"both", "control"}


def load_case(path):
    with open(path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    _validate(case)
    return case


def _validate(case):
    for key in ("facts", "hypotheses"):
        if key not in case or not isinstance(case[key], list):
            raise ValueError(f"case is missing list field '{key}'")
    fact_ids = [f.get("id") for f in case["facts"]]
    if any(not fid for fid in fact_ids) or len(set(fact_ids)) != len(fact_ids):
        raise ValueError("fact ids must be non-empty and unique")
    hyp_ids = [h.get("id") for h in case["hypotheses"]]
    if any(not hid for hid in hyp_ids) or len(set(hyp_ids)) != len(hyp_ids):
        raise ValueError("hypothesis ids must be non-empty and unique")
    for hyp in case["hypotheses"]:
        for fid in hyp.get("consistent_with", []):
            if fid not in fact_ids:
                raise ValueError(
                    f"hypothesis {hyp['id']} references unknown fact {fid}"
                )


def analyze(case):
    facts = {f["id"]: f for f in case["facts"]}
    all_fact_ids = list(facts)
    hyps = case["hypotheses"]

    def consistent(hyp, fid):
        return fid in hyp.get("consistent_with", [])

    # Per-fact strength: hypotheses remaining consistent with the fact.
    strength = {}
    for fid in all_fact_ids:
        strength[fid] = sum(1 for h in hyps if consistent(h, fid))

    # Candidates: consistent with every fact.
    candidates = [h["id"] for h in hyps if all(consistent(h, fid) for fid in all_fact_ids)]

    # Facts no hypothesis explains.
    unexplained = [fid for fid in all_fact_ids if strength[fid] == 0]

    # Per-hypothesis contradicted facts.
    contradicted = {
        h["id"]: [fid for fid in all_fact_ids if not consistent(h, fid)]
        for h in hyps
    }

    return {
        "case_id": case.get("case_id", ""),
        "signal_strength": strength,
        "strong_signals": [
            fid for fid, n in strength.items()
            if n <= 1 and facts[fid].get("seen_in") == "variable"
        ],
        "noise": [fid for fid in all_fact_ids if facts[fid].get("seen_in") in NOISE],
        "candidates": candidates,
        "unexplained_facts": unexplained,
        "contradicted_facts": contradicted,
        "hint": (
            "no all-consistent hypothesis: split coarse hypotheses, merge "
            "over-fine ones, or combine complementary ones (each strictly "
            "necessary) before proposing a new one"
            if not candidates else
            "candidate hypothesis(es) satisfy every fact; validate against "
            "the noise too before acting"
        ),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case", help="path to triage-case.json")
    ap.add_argument("--json", action="store_true", help="emit raw JSON")
    args = ap.parse_args(argv)
    try:
        result = analyze(load_case(args.case))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"matrix: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"case: {result['case_id'] or '(unnamed)'}")
    strong = set(result["strong_signals"])
    print("signal strength (hypotheses consistent; <=1 is strong):")
    for fid, n in result["signal_strength"].items():
        tag = "STRONG" if fid in strong else "weak"
        noise = " (noise: elimination only)" if fid in result["noise"] else ""
        print(f"  {fid}: {n} hypotheses [{tag}]{noise}")
    print(f"candidates (consistent with every fact): {result['candidates'] or 'none'}")
    if result["unexplained_facts"]:
        print(f"unexplained facts: {result['unexplained_facts']}")
    for hid, bad in result["contradicted_facts"].items():
        if bad:
            print(f"hypothesis {hid} contradicts: {bad}")
    print(f"hint: {result['hint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
