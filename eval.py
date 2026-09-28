"""Run every test case through the triage pipeline and score it.

Usage:
    python eval.py                 # auto: AI if a key is configured, else rules
    python eval.py --engine rules  # force the keyword fallback
    python eval.py --set mock      # only the six challenge requests
    python eval.py --out results/eval_ai.md

Scoring per field: ✓ preferred answer, ~ acceptable alternative, ✗ wrong.
"""

import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from triage.llm import get_provider
from triage.pipeline import triage
from triage.rules import MONEY

CASES = Path(__file__).parent / "data" / "cases.json"


def load_cases(which: str = "all") -> list[dict]:
    cases = json.loads(CASES.read_text())["cases"]
    return [c for c in cases if which == "all" or c["set"] == which]


def grade(value: str, accepted: list[str]) -> str:
    if value == accepted[0]:
        return "✓"
    return "~" if value in accepted else "✗"


def check_must(case: dict, outcome) -> list[str]:
    r, failures = outcome.result, []
    must = case.get("must", {})
    for flag in must.get("flags_include", []):
        if flag not in [f.value for f in r.flags]:
            failures.append(f"missing flag {flag}")
    for text in must.get("details_mention", []):
        if text not in " ".join(r.key_details) + r.summary:
            failures.append(f"key details miss {text}")
    if must.get("no_invented_amounts") and MONEY.search(r.draft_response):
        failures.append("draft invents an amount")
    return failures


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["auto", "rules"], default="auto")
    ap.add_argument("--set", choices=["all", "mock", "edge"], default="all")
    ap.add_argument("--out", help="also write the markdown report to this file")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between calls (free-tier rate limits)")
    args = ap.parse_args()

    provider = None if args.engine == "rules" else get_provider()
    engine_name = provider.label if provider else "rules"
    cases = load_cases(args.set)

    lines = [
        f"# Triage eval - engine: `{engine_name}`",
        "",
        "| # | Case | Category | Priority | Owner | Checks | Engine |",
        "|---|---|---|---|---|---|---|",
    ]
    totals = {"fields": 0, "ok": 0, "exact": 0, "checks": 0, "checks_ok": 0, "cases_ok": 0}

    for i, case in enumerate(cases):
        if i and args.pause:
            time.sleep(args.pause)
        out = triage(case["text"], case["channel"], provider=provider)
        r, exp = out.result, case["expected"]
        marks = {
            "category": grade(r.category.value, exp["category"]),
            "priority": grade(r.priority.value, exp["priority"]),
            "owner": grade(r.owner.value, exp["owner"]),
        }
        failures = check_must(case, out)
        n_checks = sum(len(v) if isinstance(v, list) else 1 for v in case.get("must", {}).values())

        totals["fields"] += 3
        totals["ok"] += sum(m != "✗" for m in marks.values())
        totals["exact"] += sum(m == "✓" for m in marks.values())
        totals["checks"] += n_checks
        totals["checks_ok"] += n_checks - len(failures)
        totals["cases_ok"] += all(m != "✗" for m in marks.values()) and not failures

        checks = "—" if not n_checks else ("✓" if not failures else "✗ " + "; ".join(failures))
        lines.append(
            f"| {case['id']} | {case['title']} "
            f"| {marks['category']} {r.category.value} "
            f"| {marks['priority']} {r.priority.value} "
            f"| {marks['owner']} {r.owner.value} "
            f"| {checks} | {out.engine.split(':')[0]} |"
        )

    t = totals
    lines += [
        "",
        f"**Cases fully correct:** {t['cases_ok']}/{len(cases)}  ",
        f"**Labels acceptable:** {t['ok']}/{t['fields']} ({t['ok'] / t['fields']:.0%}), "
        f"preferred answer: {t['exact']}/{t['fields']} ({t['exact'] / t['fields']:.0%})  ",
        f"**Extra checks passed:** {t['checks_ok']}/{t['checks']}",
        "",
        "✓ preferred answer · ~ acceptable alternative · ✗ wrong",
    ]
    report = "\n".join(lines)
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report + "\n")


if __name__ == "__main__":
    main()
