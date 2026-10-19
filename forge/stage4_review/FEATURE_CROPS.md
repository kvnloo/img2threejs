# Aligned feature crops

Use this optional, review-only helper after generating a comparison sheet.
It samples the *finished sheet pixels*, so it shares exactly the same cover
(or contain) mapping as the actual comparison, without a second resize or
manually reconstructed crop transform.

1. Generate the sheet and its manifest:

   ```bash
   python3 forge/stage4_review/make_comparison_sheet.py \
     --reference ref.png --render front.png \
     --out comparison.png --json > comparison.json
   ```

2. On **each sheet panel**, identify at least two corresponding landmarks
   inside the desired feature ROI. Coordinates are normalized relative to
   the **panel** (not the original images). Example `landmarks.json`:

   ```json
   [
     {"reference": [0.30, 0.30], "render": [0.30, 0.30]},
     {"reference": [0.70, 0.70], "render": [0.70, 0.70]}
   ]
   ```

3. Extract the matching region:

   ```bash
   python3 forge/stage4_review/make_feature_crops.py \
     --sheet comparison.png --manifest comparison.json \
     --roi 0.25 0.25 0.75 0.75 \
     --landmarks-json landmarks.json --max-alignment-px 8 \
     --out feature.png --json > feature-evidence.json
   ```

The ROI is `x0 y0 x1 y1`, normalized in both panel coordinate systems.
The script rejects malformed ROIs, mismatched sheet dimensions, missing or
duplicated landmarks, and landmark displacement beyond the threshold.
It does not write a new feature image when alignment fails.

**Limits:** Manually declared 2D correspondences are not independent image
registration, camera pose validation, or proof of 3D reconstruction fidelity.
Check actual camera/landmark calibration before treating a feature comparison
as review evidence. A passing crop check never advances a reconstruction gate.
