/** Segmentation-threshold sensitivity for one *fixed* pair of RGBA frames.
 * No fitting and no geometry change: a diagnostic of mask calibration only.
 */
export const THRESHOLD_PAIRS = Object.freeze([
  [8,15], [8,22], [8,29],
  [13,15], [13,22], [13,29],
  [18,15], [18,22], [18,29],
]);

export function measureThresholdSensitivity(referenceRGBA, renderedRGBA,
  thresholdPairs = THRESHOLD_PAIRS) {
  if (!referenceRGBA || !renderedRGBA ||
      referenceRGBA.length !== renderedRGBA.length ||
      referenceRGBA.length === 0 || referenceRGBA.length % 4 !== 0) {
    throw new RangeError('reference and render must contain equal nonempty RGBA buffers');
  }
  if (!Array.isArray(thresholdPairs) || thresholdPairs.length < 1 ||
      thresholdPairs.length > 40) {
    throw new RangeError('requires 1-40 deterministic threshold pairs');
  }
  const results = [];
  for (const pair of thresholdPairs) {
    if (!Array.isArray(pair) || pair.length !== 2 ||
        !pair.every(Number.isFinite) || pair.some(v => v < 0 || v > 255)) {
      throw new RangeError('invalid RG/RB thresholds');
    }
    const [rg, rb] = pair;
    let intersection = 0, union = 0, refArea = 0, renderArea = 0;
    for (let i = 0; i < referenceRGBA.length; i += 4) {
      const rr = referenceRGBA[i], rgc = referenceRGBA[i + 1],
        rbv = referenceRGBA[i + 2];
      const sr = renderedRGBA[i], sg = renderedRGBA[i + 1],
        sb = renderedRGBA[i + 2];
      const refMask = rr > 48 && rr - rgc > rg && rr - rbv > rb;
      const renderMask = sr > 48 && sr - sg > rg && sr - sb > rb;
      if (refMask) refArea++;
      if (renderMask) renderArea++;
      if (refMask && renderMask) intersection++;
      if (refMask || renderMask) union++;
    }
    if (union === 0) throw new Error('empty segmentation union at RG/RB=' + pair);
    results.push({
      redGreen:rg, redBlue:rb,
      iou:Number((intersection/union).toFixed(6)),
      referencePixels:refArea,
      renderedPixels:renderArea,
    });
  }
  return results;
}
