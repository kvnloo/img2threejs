#!/usr/bin/env python3
"""Emit a deterministic hinged-panel scene using the real Three.js code generator.

Test-only file: intentionally invokes generation without production pass gates.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'forge' / 'stage3_build'))
from generate_threejs_factory import generate  # noqa: E402


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: emit_hinge_runtime_fixture.py output.ts')
    output = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as folder:
        spec_path = Path(folder) / 'spec.json'
        subprocess.run(
            [sys.executable, str(ROOT / 'forge' / 'stage2_spec' / 'new_sculpt_spec.py'),
             'Folding Carton', '--out', str(spec_path)],
            check=True, capture_output=True, text=True,
        )
        spec = json.loads(spec_path.read_text(encoding='utf-8'))

    original = spec['componentTree'][0]

    def box(id, name, parent, xyz, dims, hinge=None):
        component = copy.deepcopy(original)
        component.update({
            'id': id,
            'name': name,
            'parent': parent,
            'role': 'panel',
            'primitive': 'box',
            'topologyClass': 'assembled-solid',
            'topologyRationale': 'Visible straight-sided rigid panel with planar folds.',
            'geometryDescriptor': {},
            'level': 'macro',
            'dimensions': {'width': dims[0], 'height': dims[1], 'depth': dims[2]},
            'transform': {'position': xyz, 'rotation': [0, 0, 0], 'scale': dims},
        })
        component.pop('attachment', None)
        component.pop('hinge', None)
        if hinge:
            component['hinge'] = hinge
        return component

    spec['componentTree'] = [
        box('base', 'Bottom', None, [0, 0, 0], [1.5, 0.1, 1.1]),
        box('lid', 'Lid', 'base', [0.5, 0, 0], [1.0, 0.06, 1.0],
            {'axisStart': [0, 0, 0], 'axisEnd': [0, 0, 1], 'restAngleDeg': 0}),
        box('flap', 'Flap', 'lid', [1.5, 0, 0], [1.0, 0.06, 1.0],
            {'axisStart': [1, 0, 0], 'axisEnd': [1, 0, 1], 'restAngleDeg': 0}),
        box('diagonal', 'Diagonal', 'base', [0.8, -0.8, -0.2], [0.25, 0.25, 0.25],
            {'axisStart': [0.2, -0.7, -0.2], 'axisEnd': [1.2, 0.3, 0.8], 'restAngleDeg': 0}),
    ]
    # Force a clean codegen-only fixture; no claim of evidence-based fidelity.
    source = generate(spec, 'blockout')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source, encoding='utf-8')
    print(f'emitted {output} ({len(source)} chars)')


if __name__ == '__main__':
    main()
