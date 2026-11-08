"""Tiny PNG unit fixtures only; these are not reconstruction experiment receipts."""
import hashlib
import inspect
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from forge.stage4_review.fit_params import FitConfig, fit_against_divine_eye
from forge.tests.test_reconstruction_evidence import _chunk, _valid_bundle


def pixels_png(path, pixels, channels):
    color = {1: 0, 4: 6}[channels]
    ihdr = struct.pack('>IIBBBBB', 2, 2, 8, color, 0, 0, 0)
    rows = b''.join(b'\0' + bytes(pixels[y * 2 * channels:(y + 1) * 2 * channels]) for y in range(2))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', zlib.compress(rows)) + _chunk(b'IEND', b''))


class ExperimentalSilhouetteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = _valid_bundle(self.root)
        pixels_png(self.root / 'foreground-mask.png', [255, 0, 0, 255], 1)
        manifest = json.loads(self.manifest.read_text())
        manifest['artifacts'][2]['sha256'] = hashlib.sha256((self.root / 'foreground-mask.png').read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(manifest))
        self.render = self.root / 'render.png'
        pixels_png(self.render, [100, 80, 60, 255] + [0, 0, 0, 0] * 3, 4)

    def run_fit(self, **kwargs):
        return fit_against_divine_eye([1], [[0, 2]], lambda _: self.render,
                                     self.root / 'reference.png',
                                     evaluator=lambda _r, _p: {'fidelity': .8, 'hardGateFailures': [], 'action': 'continue', 'verdict': 'pass'},
                                     config=FitConfig(max_evaluations=1, seed=7),
                                     evidence_manifest=self.manifest, **kwargs)

    def test_opt_in_penalizes_approved_objective_but_preserves_raw_fidelity(self):
        self.assertIn('experimental_silhouette_weight', inspect.signature(fit_against_divine_eye).parameters,
                      'explicit opt-in must exist; default receipt path stays unchanged')
        result = self.run_fit(experimental_silhouette_weight=.05)
        self.assertEqual(result.best_raw_fidelity, .8)
        self.assertAlmostEqual(result.fit_result.best_score, .8 - .05 * (1 - .5))
        term = result.divine_eye_results[0]['fitEvidenceSilhouette']
        self.assertEqual(term['iou'], .5)  # Both disconnected reference components retained.
        self.assertEqual(term['grid'], 224)
        self.assertEqual(term['threshold'], 128)
        self.assertEqual(term['maskSha256'], json.loads(self.manifest.read_text())['artifacts'][2]['sha256'])
        self.assertEqual(result.divine_eye_results[0]['fidelity'], .8)

    def test_default_and_explicit_zero_are_identical_without_mask_decoding(self):
        # A valid receipt-only bundle can have an empty semantic mask.
        pixels_png(self.root / 'foreground-mask.png', [0, 0, 0, 0], 1)
        manifest = json.loads(self.manifest.read_text())
        manifest['artifacts'][2]['sha256'] = hashlib.sha256((self.root / 'foreground-mask.png').read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(manifest))
        default = self.run_fit().to_json()
        zero = self.run_fit(experimental_silhouette_weight=0).to_json()
        self.assertEqual(default, zero)
        self.assertNotIn('fitEvidenceSilhouette', default['divineEyeResults'][0])
        self.assertEqual(default['bestObjectiveScore'], .8)

    def test_hard_failures_and_probe_cannot_be_rescued(self):
        for gates, verdict, action in ((['scale'], 'pass', 'continue'), ([], 'low-confidence', 'probe'),
                                       ([], 'reject', 'refine-code')):
            with self.subTest(gates=gates, action=action):
                result = fit_against_divine_eye([1], [[0, 2]], lambda _: self.render,
                    self.root / 'reference.png', evaluator=lambda _r, _p: {
                        'fidelity': 1.0, 'hardGateFailures': gates, 'verdict': verdict, 'action': action},
                    config=FitConfig(max_evaluations=1), evidence_manifest=self.manifest,
                    experimental_silhouette_weight=.05)
                self.assertEqual(result.fit_result.best_score, -1.0)
                self.assertIsNone(result.best_raw_fidelity)
                self.assertEqual(result.divine_eye_results[0]['hardGateFailures'], gates)
                self.assertEqual(result.divine_eye_results[0]['fitEvidenceSilhouette']['objectiveScore'], -1)
                self.assertTrue(result.correction_history[0]['pendingReview'])

    def test_invalid_weights_refuse_before_any_render(self):
        for weight in (True, -1, .10001, float('nan'), float('inf'), '0.05', None):
            with self.subTest(weight=weight), self.assertRaisesRegex(ValueError, 'experimental_silhouette_weight'):
                fit_against_divine_eye([1], [[0, 2]], lambda _: self.fail('must not render'),
                                      self.root / 'reference.png', experimental_silhouette_weight=weight)

    def test_positive_weight_requires_bundle_and_matching_reference(self):
        with self.assertRaisesRegex(ValueError, 'requires an evidence bundle'):
            fit_against_divine_eye([1], [[0, 2]], lambda _: self.fail('must not render'),
                                  self.root / 'reference.png', experimental_silhouette_weight=.05)
        wrong = self.root / 'different.png'
        wrong.write_bytes(self.render.read_bytes())
        with self.assertRaisesRegex(ValueError, 'reference hash'):
            fit_against_divine_eye([1], [[0, 2]], lambda _: self.fail('must not render'), wrong,
                                  evidence_manifest=self.manifest, experimental_silhouette_weight=.05)

    def test_empty_or_opaque_render_refused_without_heuristic(self):
        for alpha in (0, 255):
            pixels_png(self.render, [70, 80, 60, alpha] * 4, 4)
            with self.subTest(alpha=alpha), self.assertRaisesRegex(ValueError, 'nonempty and not whole-frame'):
                self.run_fit(experimental_silhouette_weight=.05)

    def test_dimension_mismatch_refused(self):
        from forge.tests.test_reconstruction_evidence import _png
        self.render.write_bytes(_png(3, 2, 8, 2))
        with self.assertRaisesRegex(ValueError, 'dimensions differ'):
            self.run_fit(experimental_silhouette_weight=.05)

    def test_empty_or_full_reference_mask_refused(self):
        for value in (0, 255):
            pixels_png(self.root / 'foreground-mask.png', [value] * 4, 1)
            manifest = json.loads(self.manifest.read_text())
            manifest['artifacts'][2]['sha256'] = hashlib.sha256((self.root / 'foreground-mask.png').read_bytes()).hexdigest()
            self.manifest.write_text(json.dumps(manifest))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'nonempty and not whole-frame'):
                self.run_fit(experimental_silhouette_weight=.05)

    def test_term_changes_approved_ranking_not_evaluator_history(self):
        matching = self.root / 'matching.png'
        pixels_png(matching, [100, 80, 60, 255] + [0, 0, 0, 0] * 2 + [100, 80, 60, 255], 4)
        def render(parameters):
            return matching if parameters[0] < 1 else self.render
        def evaluator(_r, _p):
            return {'fidelity': .8, 'hardGateFailures': [], 'verdict': 'pass', 'action': 'continue'}
        args = ([1], [[0, 2]], render, self.root / 'reference.png')
        options = dict(evaluator=evaluator, config=FitConfig(max_evaluations=3), evidence_manifest=self.manifest)
        baseline = fit_against_divine_eye(*args, **options)
        experiment = fit_against_divine_eye(*args, **options, experimental_silhouette_weight=.05)
        self.assertEqual(baseline.fit_result.parameters, (1.0,))
        self.assertEqual(experiment.fit_result.parameters, (.5,))
        self.assertEqual(experiment.best_raw_fidelity, baseline.best_raw_fidelity)
        self.assertTrue(all(r['fidelity'] == .8 for r in experiment.divine_eye_results))
        self.assertEqual(experiment.correction_history[1]['divineEye'], experiment.divine_eye_results[1])


if __name__ == '__main__':
    unittest.main()
