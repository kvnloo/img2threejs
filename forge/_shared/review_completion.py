#!/usr/bin/env python3
"""One source of truth for crediting an evidence-backed sculpt build pass.

The review writer, orchestrator, spec validator and TypeScript generator MUST
agree about which reviewHistory entries unlock later passes. This module is
stdlib-only apart from the existing shared feature acceptance policy.
"""

from __future__ import annotations

import math
from typing import Any

from feature_acceptance_policy import feature_gate_failures


VISUAL_PASS_IDS = frozenset({
    "blockout",
    "structural-pass",
    "form-refinement",
    "material-pass",
    "surface-pass",
    "lighting-pass",
    "interaction-pass",
})


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def review_completes_pass(spec: dict[str, Any], entry: dict[str, Any], pass_id: str) -> bool:
    """Only credit 'continue' reviews with all required evidence and passing gates."""
    if entry.get("passId") != pass_id or entry.get("action") != "continue":
        return False
    # The unlit/map-free blockout is a hard admission gate, not merely a screenshot.
    if pass_id == "blockout" and not entry.get("mapStrippedRender"):
        return False
    if pass_id not in VISUAL_PASS_IDS:
        return True

    viewpoints = entry.get("reviewViewpoints")
    if isinstance(viewpoints, list):
        supplied = {item for item in viewpoints if isinstance(item, str)}
        if not {"thickness-axis", "long-axis"}.issubset(supplied):
            return False
    visual = entry.get("visualEvidence")
    if not isinstance(visual, dict) or not visual.get("renderScreenshot") or not visual.get("comparisonImage"):
        return False
    score = entry.get("aiVisionScore")
    threshold = entry.get("visualAcceptanceThreshold", 0.7)
    if not _finite_number(score) or not _finite_number(threshold) or float(score) < float(threshold):
        return False
    if feature_gate_failures(spec, entry, pass_id):
        return False
    return True
