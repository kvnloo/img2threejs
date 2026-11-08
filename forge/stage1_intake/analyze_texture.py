#!/usr/bin/env python3
"""Reference texture analysis → finishClass + PBR recipe (Plan 1.3 texture upgrade).

Pure stdlib. Classifies a reference crop's *finish* from image statistics and emits a
material recipe (MeshPhysicalMaterial scalars + palette + procedural hints) that
`generate_threejs_factory.py`'s procedural texture generator consumes. This replaces the
per-object hand-crafting of albedo/roughness maps with a repeatable analysis→recipe step.

finishClass candidates come from { gem-metal, gemstone, painted-metal, worn-composite, brushed-steel, plastic }.
When a known semantic family is incompatible with that legacy vocabulary, the result is `status=probe`
and no finish class is applied. Recipe scalars are grounded in
grimoire/build/threejs_texture_reference.md (notebooklm/three.js docs).

CLI:  analyze_texture.py <crop.png> [--json]
API:  analyze(path) -> dict
"""
from __future__ import annotations

import argparse
import colorsys
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pbr_evidence import build_foreground_mask, load_image  # noqa: E402

# MeshPhysicalMaterial scalar presets per finish (see grimoire threejs_texture_reference.md)
RECIPES: dict[str, dict[str, Any]] = {
    "gem-metal":      {"metalness": 0.75, "roughness": 0.14, "clearcoat": 0.60, "clearcoatRoughness": 0.06, "transmission": 0.0, "ior": 1.5,  "envMapIntensity": 1.3, "anisotropy": 0.0, "procedural": "gradient-smoke"},
    # candy-coat: anodized / PVD / pigment-dominant doppler coat. Dielectric-led (low metalness) +
    # clearcoat + trimmed envMapIntensity so the environment reflection can't steal the hue — the
    # exact counter-recipe that fixed the M9 Doppler blue-wash (grimoire/feedback/shading_realism.md).
    "candy-coat":     {"metalness": 0.35, "roughness": 0.18, "clearcoat": 0.60, "clearcoatRoughness": 0.15, "transmission": 0.0, "ior": 1.5,  "envMapIntensity": 0.7, "anisotropy": 0.0, "procedural": "gradient-smoke"},
    "gemstone":       {"metalness": 0.0,  "roughness": 0.05, "clearcoat": 1.00, "clearcoatRoughness": 0.0,  "transmission": 0.9, "ior": 1.54, "envMapIntensity": 1.0, "anisotropy": 0.0, "procedural": "gradient-smoke"},
    "painted-metal":  {"metalness": 0.0,  "roughness": 0.5,  "clearcoat": 1.00, "clearcoatRoughness": 0.05, "transmission": 0.0, "ior": 1.5,  "envMapIntensity": 1.0, "anisotropy": 0.0, "procedural": "flat-clearcoat"},
    "worn-composite": {"metalness": 0.0,  "roughness": 0.9,  "clearcoat": 0.0,  "clearcoatRoughness": 0.0,  "transmission": 0.0, "ior": 1.5,  "envMapIntensity": 0.5, "anisotropy": 0.0, "procedural": "mottle"},
    "brushed-steel":  {"metalness": 1.0,  "roughness": 0.35, "clearcoat": 0.0,  "clearcoatRoughness": 0.0,  "transmission": 0.0, "ior": 1.5,  "envMapIntensity": 1.0, "anisotropy": 1.0, "procedural": "brushed"},
    "plastic":        {"metalness": 0.05, "roughness": 0.6,  "clearcoat": 0.2,  "clearcoatRoughness": 0.3,  "transmission": 0.0, "ior": 1.5,  "envMapIntensity": 0.7, "anisotropy": 0.0, "procedural": "flat-clearcoat"},
}

N = 64  # downsample grid for stats

FINISH_FAMILIES: dict[str, set[str]] = {
    "gem-metal": {"metal", "coating"},
    "candy-coat": {"metal", "coating"},
    "gemstone": {"gemstone", "glass"},
    "painted-metal": {"metal", "coating"},
    "worn-composite": {"rubber", "plastic", "composite"},
    "brushed-steel": {"metal"},
    "plastic": {"plastic"},
}


def _sample(pixels, w, h, mask):
    minx = miny = 1 << 30
    maxx = maxy = -1
    for y in range(h):
        r = y * w
        for x in range(w):
            if mask[r + x]:
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    if maxx < 0:
        minx, miny, maxx, maxy = 0, 0, w - 1, h - 1
    bw = max(1, maxx - minx + 1); bh = max(1, maxy - miny + 1)
    grid = []
    for j in range(N):
        sy = min(h - 1, miny + j * bh // N)
        for i in range(N):
            sx = min(w - 1, minx + i * bw // N)
            p = pixels[sy * w + sx]
            grid.append((p[0], p[1], p[2]))
    return grid


def _lum(p):
    return (p[0] * 30 + p[1] * 59 + p[2] * 11) / 100.0


def analyze(path: str | Path, *, expected_family: str | None = None) -> dict[str, Any]:
    w, h, pixels, _ = load_image(Path(path))
    mask, _diag, _warn = build_foreground_mask(w, h, pixels)
    g = _sample(pixels, w, h, mask)
    n = len(g)
    lums = [_lum(p) for p in g]
    mean_lum = sum(lums) / n

    # saturation + hue (HSV) — chromatic vs neutral, and hue SPREAD (gem shifts hue, paint doesn't)
    hsv = [colorsys.rgb_to_hsv(p[0] / 255, p[1] / 255, p[2] / 255) for p in g]
    sats = [s for _h, s, _v in hsv]
    mean_sat = sum(sats) / n
    # circular hue spread (robust to wraparound + outliers): 1 - mean resultant length,
    # saturation-weighted. ~0 for a single paint hue, larger for a blue→purple gem shift.
    import math as _m
    sc = ss = wsum = 0.0
    for _h, s, _v in hsv:
        if s > 0.2:
            sc += s * _m.cos(2 * _m.pi * _h)
            ss += s * _m.sin(2 * _m.pi * _h)
            wsum += s
    hue_spread = (1.0 - _m.hypot(sc, ss) / wsum) if wsum > 2.0 else 0.0

    # luminance gradient along rows vs cols (a strong axis gradient = doppler-like finish)
    row_means = [sum(lums[j * N:(j + 1) * N]) / N for j in range(N)]
    col_means = [sum(lums[i + j * N] for j in range(N)) / N for i in range(N)]
    horiz_grad = (max(col_means) - min(col_means)) / 255.0
    vert_grad = (max(row_means) - min(row_means)) / 255.0
    gradient_strength = max(horiz_grad, vert_grad)
    gradient_axis = "horizontal" if horiz_grad >= vert_grad else "vertical"

    # local mottle: mean abs difference to 4-neighbours (worn/patchy surfaces are high)
    diffs = 0.0
    cnt = 0
    for j in range(1, N - 1):
        for i in range(1, N - 1):
            c = lums[j * N + i]
            diffs += abs(c - lums[j * N + i - 1]) + abs(c - lums[j * N + i + 1])
            cnt += 2
    mottle = (diffs / cnt) / 255.0 if cnt else 0.0

    # directional streaks: horizontal high-freq >> vertical high-freq ⇒ brushed metal
    hf_h = sum(abs(lums[j * N + i] - lums[j * N + i - 1]) for j in range(N) for i in range(1, N)) / (N * (N - 1))
    hf_v = sum(abs(lums[j * N + i] - lums[(j - 1) * N + i]) for j in range(1, N) for i in range(N)) / (N * (N - 1))
    streak_ratio = hf_h / (hf_v + 1e-6)
    anisotropy = max(streak_ratio, 1.0 / (streak_ratio + 1e-6))  # directional either axis

    # specular fraction → metalness proxy
    spec_frac = sum(1 for lv in lums if lv > 235) / n

    # ---- classify ----
    if mean_sat < 0.18:  # near-neutral / grey → metal or worn
        if anisotropy > 1.9 and (mean_lum > 95 or spec_frac > 0.03):  # bright directional = brushed metal
            finish = "brushed-steel"
        elif spec_frac > 0.05 and mean_lum > 140:   # bright smooth specular = polished steel
            finish = "brushed-steel"
        elif mottle > 0.02 or mean_lum < 120:       # dark / textured neutral = worn composite/rubber grip
            finish = "worn-composite"
        else:                                        # mid-bright smooth neutral = plastic
            finish = "plastic"
    else:  # chromatic
        # gem/candy/doppler family = a chromatic surface with a strong gradient AND smoky internal
        # variance (the swirl); flat paint has the gradient from lighting only, so low mottle.
        if gradient_strength > 0.18 and mottle > 0.038:
            if spec_frac > 0.05:
                # bright chrome-like specular hotspots → genuinely metallic doppler (high metalness)
                finish = "gem-metal"
            elif mean_lum > 150 and spec_frac < 0.005:
                # bright + clean, no specular blowout → transmissive gemstone (quartz/glass)
                finish = "gemstone"
            else:
                # saturated PIGMENT-DOMINANT coat (colour survives into mid-tones, little chrome)
                # → anodized/PVD/doppler candy-coat, rendered as a dielectric so the env can't
                # steal the hue. This is the M9-Doppler case (was mis-classed high-metalness).
                finish = "candy-coat"
        else:
            finish = "painted-metal"

    # ---- palette stops along the dominant gradient axis (ordered low→high lum) ----
    stops = []
    for k in range(5):
        idx = int(k / 4 * (N - 1))
        if gradient_axis == "horizontal":
            col = [g[j * N + idx] for j in range(N)]
        else:
            col = g[idx * N:(idx + 1) * N]
        r = sum(c[0] for c in col) // len(col)
        gg = sum(c[1] for c in col) // len(col)
        b = sum(c[2] for c in col) // len(col)
        stops.append(f"#{r:02X}{gg:02X}{b:02X}")

    # Hue-survival annotation: flag any saturated blue-leaning violet/blue
    # palette stop (B > R) that would collapse to flat blue under ACES/Reinhard tone-mapping, and
    # suggest a magenta-lean correction (R >= B + a little green). Same rule as extract_gradient_stops.
    palette_risk = []
    for hexs in stops:
        r_ = int(hexs[1:3], 16)
        g_ = int(hexs[3:5], 16)
        b_ = int(hexs[5:7], 16)
        hh, ss, _vv = colorsys.rgb_to_hsv(r_ / 255, g_ / 255, b_ / 255)
        if b_ > r_ and ss > 0.15 and 0.54 <= hh <= 0.83:  # violet/blue hue band on the HSV circle
            palette_risk.append({
                "stop": hexs,
                "hueRisk": "blue-collapse",
                "suggestedRgb": [min(255, b_), max(g_, int(b_ * 0.25)), r_],
            })

    recipe = dict(RECIPES[finish])
    normalized_family = expected_family.strip().lower() if isinstance(expected_family, str) and expected_family.strip() else None
    compatible = FINISH_FAMILIES[finish]
    status = "proceed"
    reason = None
    finish_class: str | None = finish
    if normalized_family is not None and normalized_family not in compatible:
        status = "probe"
        reason = (
            f"legacy finish classifier has no compatible {normalized_family!r} class for "
            f"candidate {finish!r}; preserve authored material semantics"
        )
        finish_class = None
    return {
        "status": status,
        "reason": reason,
        "expectedFamily": normalized_family,
        "finishClass": finish_class,
        "finishClassCandidate": finish,
        "recipe": recipe,
        "palette": stops,
        "paletteHueRisk": palette_risk,
        "gradientAxis": gradient_axis,
        "stats": {
            "meanLum": round(mean_lum, 1),
            "meanSaturation": round(mean_sat, 3),
            "gradientStrength": round(gradient_strength, 3),
            "mottle": round(mottle, 3),
            "streakRatio": round(streak_ratio, 2),
            "hueSpread": round(hue_spread, 3),
            "specularFraction": round(spec_frac, 3),
        },
    }


def apply_to_material(material: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Apply only missing inferred fields; authored material scalars remain authoritative."""
    if result.get("status", "proceed") != "proceed" or not result.get("finishClass"):
        raise ValueError(result.get("reason") or "texture analysis is not applicable to this material family")
    r = result["recipe"]
    preserved: list[str] = []
    applied: list[str] = []

    def set_missing(key: str, value: Any) -> None:
        if key in material:
            preserved.append(key)
            return
        material[key] = value
        applied.append(key)

    set_missing("finishClass", result["finishClass"])
    set_missing("texturePalette", result["palette"])
    set_missing("proceduralTexture", r["procedural"])
    for key in ("metalness", "roughness", "clearcoat", "clearcoatRoughness", "transmission"):
        set_missing(key, {"base": r[key], "variation": 0.0})
    set_missing("ior", {"base": r["ior"], "value": r["ior"]})
    set_missing("envMapIntensity", r["envMapIntensity"])
    if r["anisotropy"] > 0:
        set_missing("anisotropy", {"base": r["anisotropy"]})
    material["textureAnalysis"] = {
        "status": result.get("status", "proceed"),
        "finishClass": result.get("finishClass"),
        "finishClassCandidate": result.get("finishClassCandidate"),
        "expectedFamily": result.get("expectedFamily"),
        "appliedFields": applied,
        "preservedAuthoredFields": preserved,
    }
    return material


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Analyze a reference crop → finishClass + PBR recipe")
    ap.add_argument("image")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--spec", type=Path, help="ObjectSculptSpec to patch a material in")
    ap.add_argument("--material-id", help="material id to apply the recipe to (with --spec)")
    ap.add_argument("--in-place", action="store_true", help="write the spec back")
    ap.add_argument("--family", help="Known semantic material family; incompatible legacy finish classes are refused")
    args = ap.parse_args(argv)
    has_patch_target = args.spec is not None and args.material_id is not None
    if (args.spec is None) != (args.material_id is None):
        ap.error("--spec and --material-id must be used together")
    if args.in_place and not has_patch_target:
        ap.error("--in-place requires --spec and --material-id")
    spec = None
    material = None
    expected_family = args.family
    if has_patch_target:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        mats = [m for m in spec.get("materials", []) if m.get("id") == args.material_id]
        if not mats:
            print(f"material {args.material_id!r} not found in spec", file=sys.stderr)
            return 2
        material = mats[0]
        if expected_family is None:
            expected_family = material.get("materialFamily") or material.get("family")
        if expected_family is None:
            reference_material_id = material.get("referenceMaterialId")
            if isinstance(reference_material_id, str) and "." in reference_material_id:
                expected_family = reference_material_id.split(".", 1)[0]
    result = analyze(args.image, expected_family=expected_family)

    if has_patch_target:
        if result.get("status") != "proceed":
            print(f"refused: {result.get('reason')}", file=sys.stderr)
            return 2
        apply_to_material(material, result)
        if args.in_place:
            args.spec.write_text(json.dumps(spec, indent=2), encoding="utf-8")
            print(f"applied {result['finishClass']} recipe to material {args.material_id!r} in {args.spec.name}")
        else:
            print(json.dumps(mats[0], indent=2))
        return 0

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"status:      {result['status']}")
        print(f"finishClass: {result['finishClass']}")
        if result.get("reason"):
            print(f"reason:      {result['reason']}")
        print(f"palette:     {result['palette']}")
        print(f"stats:       {result['stats']}")
    return 0 if result.get("status") == "proceed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
