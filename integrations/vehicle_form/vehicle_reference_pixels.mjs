/** Deterministic, opt-in measurements of a synthetic orthographic Three.js top view.
 * These are pixel measurements, not a proxy for measured automotive reference photos.
 */
export const STATIONS = Object.freeze([
  {id: 'nose', localX: -2},
  {id: 'front-fender', localX: -1},
  {id: 'door', localX: 0},
  {id: 'rear-hip', localX: 1},
  {id: 'tail', localX: 2},
]);
export const REFERENCE_PROFILE = Object.freeze([0.6, 1.0, 0.8, 1.0, 0.5]);
export const STADIUM_PROFILE = Object.freeze([1, 1, 1, 1, 1]);
export const VIEW = Object.freeze({width: 960, height: 480, left: -4.8, right: 4.8, top: 2.4, bottom: -2.4});
export const MODEL_X_SCALE = 1.25;
export const MODEL_X_OFFSET = 0.7;

export function worldX(localX) {
  if (!Number.isFinite(localX)) throw new Error('invalid longitudinal station');
  return MODEL_X_OFFSET + MODEL_X_SCALE * localX;
}

export function pixelColumn(worldPosition, view = VIEW) {
  if (!(view.right > view.left) || !Number.isSafeInteger(view.width) || view.width < 1)
    throw new Error('invalid orthographic camera width');
  const projected = (worldPosition - view.left) / (view.right - view.left) * view.width;
  const pixel = Math.round(projected);
  if (pixel < 0 || pixel >= view.width) throw new Error('reference station outside image');
  return pixel;
}

/** Take a pixel just inside each end cap: boundary pixels at the exact x extent
 * can be outside the rasterized silhouette due to pixel-center sampling. */
export function referencePixelColumn(stationIndex, view = VIEW) {
  if (!Number.isSafeInteger(stationIndex) || stationIndex < 0 || stationIndex >= STATIONS.length)
    throw new Error('invalid reference station index');
  const nominal = pixelColumn(worldX(STATIONS[stationIndex].localX), view);
  return nominal + (stationIndex === 0 ? 2 : stationIndex === STATIONS.length - 1 ? -2 : 0);
}

// The fixture paints the vehicle body green, whereas tires, roof, and studio are not.
function bodyPixel(r, g, b, alpha) {
  return alpha > 240 && g > 100 && g > r * 1.35 && g > b * 1.2;
}

/** Accepts one vertically sampled RGBA column, not a full image; reduce transport. */
export function widthFromPixelColumn(rgba, {height = VIEW.height, top = VIEW.top, bottom = VIEW.bottom} = {}) {
  if (!(rgba instanceof Uint8Array || Array.isArray(rgba)) || rgba.length !== height * 4 ||
      !Number.isSafeInteger(height) || height < 1 || !(top > bottom)) {
    throw new Error('invalid image column evidence');
  }
  let start = height, finish = -1, matches = 0;
  for (let y = 0; y < height; y++) {
    const index = 4 * y;
    if (bodyPixel(rgba[index], rgba[index + 1], rgba[index + 2], rgba[index + 3])) {
      start = Math.min(start, y);
      finish = Math.max(finish, y);
      matches++;
    }
  }
  if (matches < 2) throw new Error('reference column contains no measurable body silhouette');
  return {width: (finish - start + 1) * (top - bottom) / height, bodyPixels: matches};
}

/** This table is derived from browser-rendered reference pixels, not truth widths. */
export function referenceTableFromColumns(rgbaColumns, source, view = VIEW) {
  if (!Array.isArray(rgbaColumns) || rgbaColumns.length !== STATIONS.length) {
    throw new Error('expected a pixel column for every vehicle station');
  }
  if (typeof source !== 'string' || !source.trim()) throw new Error('reference image provenance is required');
  return {
    schemaVersion: 1,
    axis: 'x', lateralAxis: 'z',
    reference: {kind: 'measured-top-view', source},
    maxNormalizedWidthError: 0.08,
    maxTaperLoss: 0.12,
    stations: STATIONS.map((station, i) => {
      const x = worldX(station.localX);
      const width = widthFromPixelColumn(rgbaColumns[i], view);
      return {id: station.id, x, referenceWidth: width.width, referencePixelColumn: referencePixelColumn(i, view), referenceBodyPixelCount: width.bodyPixels};
    }),
  };
}
