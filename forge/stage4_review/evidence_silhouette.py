"""Experimental single silhouette penalty. Never grants evidence hard-gate authority.

Semantic masks are decoded directly: no photograph estimator, largest-component
filter, alignment, inferred depth, or material signal. The render must contain a
nondegenerate alpha silhouette at the exact reference dimensions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from forge.stage1_intake.extract_pbr_evidence import read_png
from forge.stage1_intake.reconstruction_evidence import ReconstructionEvidenceBundle
# Divine Eye initializes its legacy standalone imports before exposing the primitive.
from forge.stage4_review.divine_eye import silhouette_iou

GRID = 224
THRESHOLD = 128


def _sample(width: int, height: int, pixels: list[tuple[int, int, int, int]], channel: int) -> list[bool]:
    mask = [pixels[(y * height // GRID) * width + x * width // GRID][channel] >= THRESHOLD
            for y in range(GRID) for x in range(GRID)]
    if not 0 < sum(mask) < len(mask):
        raise ValueError('experimental silhouette must be nonempty and not whole-frame')
    return mask


@dataclass(frozen=True)
class SilhouetteEvidence:
    reference_mask: tuple[bool, ...]
    width: int
    height: int
    mask_sha256: str

    def compare(self, render_png: Path, weight: float) -> dict[str, object]:
        width, height, pixels = read_png(render_png)
        if (width, height) != (self.width, self.height):
            raise ValueError('experimental silhouette render/reference dimensions differ')
        mask = _sample(width, height, pixels, 3)
        iou = silhouette_iou(list(self.reference_mask), mask)
        return {'iou': iou, 'weight': weight, 'penalty': weight * (1.0 - iou),
                'maskSha256': self.mask_sha256, 'grid': GRID, 'threshold': THRESHOLD,
                'renderForeground': 'alpha', 'resample': 'nearest-floor',
                'components': 'all', 'referenceCoverage': sum(self.reference_mask) / len(mask),
                'renderCoverage': sum(mask) / len(mask)}


def prepare_silhouette(bundle: ReconstructionEvidenceBundle, reference_png: Path) -> SilhouetteEvidence:
    reference = bundle.by_role('reference')[0]
    if hashlib.sha256(reference_png.read_bytes()).hexdigest() != reference.sha256:
        raise ValueError('experimental silhouette reference hash differs from bundle')
    artifact = bundle.by_role('foreground-mask')[0]
    if hashlib.sha256(artifact.path.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError('experimental silhouette mask hash differs from bundle')
    width, height, pixels = read_png(artifact.path)
    if (width, height) != (reference.width, reference.height):
        raise ValueError('experimental silhouette mask/reference dimensions differ')
    return SilhouetteEvidence(tuple(_sample(width, height, pixels, 0)), width, height, artifact.sha256)
