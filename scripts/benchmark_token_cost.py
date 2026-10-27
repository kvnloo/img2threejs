#!/usr/bin/env python3
"""Report actual provider token usage for complete image-to-Three.js reconstructions.

Input is one JSON object per provider call; this tool never estimates usage.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
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
        if not isinstance(row, dict):
            raise ValueError(f"receipt {index}: expected a JSON object")
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


def compare_paired(baseline_rows: list[dict], candidate_rows: list[dict]) -> dict:
    """Pair measured runs only when reference, camera, evaluator and budget match.

    This compares token usage, NOT reconstruction fidelity. Treat a smaller
    token delta as a cost observation, never automatic quality improvement.
    """
    baseline = aggregate(baseline_rows)
    candidate = aggregate(candidate_rows)
    if baseline["runIds"] != candidate["runIds"]:
        raise ValueError("paired comparison requires exactly matching run IDs")

    def validate_conditions(rows: list[dict], label: str) -> dict[str, tuple]:
        conditions: dict[str, tuple] = {}
        for index, row in enumerate(rows, 1):
            sha_fields = ("reference_sha256", "render_profile_sha256")
            for field in sha_fields:
                value = row.get(field)
                if (not isinstance(value, str) or len(value) != 64
                        or any(char not in "0123456789abcdef" for char in value)):
                    raise ValueError(f"{label} receipt {index}: {field} must be lowercase SHA-256")
            evaluator = row.get("evaluator_revision")
            if not isinstance(evaluator, str) or not evaluator.strip():
                raise ValueError(f"{label} receipt {index}: evaluator_revision is required")
            budget = row.get("render_budget")
            if type(budget) is not int or budget < 1:
                raise ValueError(f"{label} receipt {index}: render_budget must be positive")
            run_id = row["run_id"]
            signature = (row["reference_sha256"], row["render_profile_sha256"],
                         evaluator.strip(), budget)
            if run_id in conditions and conditions[run_id] != signature:
                raise ValueError(f"{label} run {run_id}: inconsistent comparison conditions")
            conditions[run_id] = signature
        return conditions

    base_meta = validate_conditions(baseline_rows, "baseline")
    cand_meta = validate_conditions(candidate_rows, "candidate")
    if base_meta != cand_meta:
        bad_runs = sorted(k for k in base_meta if base_meta[k] != cand_meta[k])
        raise ValueError("paired comparison conditions differ for runs: " + ", ".join(bad_runs))

    def by_run(rows: list[dict]) -> dict[str, dict]:
        sums: dict[str, dict] = {}
        for row in rows:
            stats = sums.setdefault(row["run_id"], {
                "totalTokens": 0, "requests": 0, "costUsd": Decimal(0),
                "allCostsKnown": True,
            })
            stats["totalTokens"] += row["usage"]["total_tokens"]
            stats["requests"] += 1
            if "cost_usd" not in row:
                stats["allCostsKnown"] = False
            else:
                stats["costUsd"] += Decimal(str(row["cost_usd"]))
        return sums

    b, c = by_run(baseline_rows), by_run(candidate_rows)
    run_rows = {}
    for run in baseline["runIds"]:
        left, right = b[run], c[run]
        both_priced = left["allCostsKnown"] and right["allCostsKnown"]
        run_rows[run] = {
            "baselineTokens": left["totalTokens"],
            "candidateTokens": right["totalTokens"],
            "deltaTokens": right["totalTokens"] - left["totalTokens"],
            "baselineRequests": left["requests"],
            "candidateRequests": right["requests"],
            "deltaRequests": right["requests"] - left["requests"],
            "deltaCostUsd": format(right["costUsd"] - left["costUsd"], "f")
            if both_priced else None,
            "conditions": {
                "referenceSha256": base_meta[run][0],
                "renderProfileSha256": base_meta[run][1],
                "evaluatorRevision": base_meta[run][2],
                "renderBudget": base_meta[run][3],
            },
        }
    cost_known = all(x["deltaCostUsd"] is not None for x in run_rows.values())
    return {
        "comparisonKind": "paired-provider-usage",
        "qualityCompared": False,
        "baseline": baseline,
        "candidate": candidate,
        "deltaTokens": candidate["totalTokens"] - baseline["totalTokens"],
        "deltaCostUsd": format(sum(Decimal(x["deltaCostUsd"]) for x in run_rows.values()), "f")
        if cost_known else None,
        "pairedRuns": run_rows,
    }


def write_report_atomically(destination: Path, report: dict) -> None:
    """Leave prior verified receipts intact if writing or publishing fails."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usage_jsonl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-runs", type=int, default=1)
    parser.add_argument("--baseline", type=Path, help="measured JSONL receipts for paired A/B comparison")
    args = parser.parse_args(argv)
    try:
        # Output aliases (including symlinks and relative spellings) would
        # destroy the provider's original measurement evidence on success.
        # Reject them before reading inputs or creating an output directory.
        destination = args.out.expanduser().resolve()
        inputs = [args.usage_jsonl]
        if args.baseline is not None:
            inputs.append(args.baseline)
        if any(destination == source.expanduser().resolve() for source in inputs):
            raise ValueError("--out must differ from provider usage and baseline input files")
        rows = [json.loads(line) for line in args.usage_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        report = aggregate(rows)
        if args.minimum_runs < 1 or report["runCount"] < args.minimum_runs:
            raise ValueError("not enough complete runs for requested minimum")
        if args.baseline is not None:
            baseline = [json.loads(line) for line in args.baseline.read_text(encoding="utf-8").splitlines() if line.strip()]
            if aggregate(baseline)["runCount"] < args.minimum_runs:
                raise ValueError("not enough complete baseline runs for requested minimum")
            report = compare_paired(baseline, rows)
        write_report_atomically(args.out, report)
    except (OSError, ValueError, TypeError) as exc:
        print(f"measured token benchmark: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
