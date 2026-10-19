#!/usr/bin/env python3
"""Report actual provider token usage for complete image-to-Three.js reconstructions.

Input is one JSON object per provider call; this tool never estimates usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED = {"assessment", "spec", "codegen", "render-review"}


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("no measured provider usage receipts")
    stages: dict[str, set[str]] = defaultdict(set)
    seen: set[tuple[str, str]] = set()
    totals: dict[str, dict] = {}
    for index, row in enumerate(rows, 1):
        for name in ("run_id", "event_id", "stage", "model", "provider"):
            if not isinstance(row.get(name), str) or not row[name].strip():
                raise ValueError(f"receipt {index}: missing {name}")
        if row.get("usage_source") != "provider":
            raise ValueError(f"receipt {index}: usage is not provider-measured")
        run, event, stage = row["run_id"], row["event_id"], row["stage"]
        if (run, event) in seen:
            raise ValueError(f"duplicate receipt {run}/{event}")
        seen.add((run, event))
        usage = row.get("usage")
        if not isinstance(usage, dict):
            raise ValueError(f"receipt {index}: missing usage")
        counts = [usage.get(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError(f"receipt {index}: counts must be nonnegative provider integers")
        prompt, completion, total = counts
        if total < prompt + completion:
            raise ValueError(f"receipt {index}: total_tokens is inconsistent")
        cost = None
        if "cost_usd" in row:
            try:
                cost = Decimal(str(row["cost_usd"]))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"receipt {index}: invalid cost_usd") from exc
            if isinstance(row["cost_usd"], bool) or not cost.is_finite() or cost < 0:
                raise ValueError(f"receipt {index}: invalid cost_usd")
        stages[run].add(stage)
        stats = totals.setdefault(stage, {
            "requests": 0, "promptTokens": 0, "completionTokens": 0,
            "totalTokens": 0, "knownCostUsd": Decimal(0), "unpricedRequests": 0
        })
        stats["requests"] += 1
        stats["promptTokens"] += prompt
        stats["completionTokens"] += completion
        stats["totalTokens"] += total
        if cost is None:
            stats["unpricedRequests"] += 1
        else:
            stats["knownCostUsd"] += cost
    missing = {run: sorted(REQUIRED - present) for run, present in stages.items() if REQUIRED - present}
    if missing:
        raise ValueError("incomplete reconstruction stages: " + json.dumps(missing, sort_keys=True))
    output = {}
    for stage, stats in sorted(totals.items()):
        output[stage] = dict(stats, knownCostUsd=format(stats["knownCostUsd"], "f"))
    return {
        "schemaVersion": 1,
        "evidence": "provider-reported-tokens",
        "runIds": sorted(stages),
        "runCount": len(stages),
        "requestCount": len(seen),
        "byStage": output,
        "totalTokens": sum(stat["totalTokens"] for stat in totals.values()),
        "unpricedRequests": sum(stat["unpricedRequests"] for stat in totals.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usage_jsonl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-runs", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        rows = [json.loads(line) for line in args.usage_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        report = aggregate(rows)
        if args.minimum_runs < 1 or report["runCount"] < args.minimum_runs:
            raise ValueError("not enough complete runs for requested minimum")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError) as exc:
        print(f"measured token benchmark: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
