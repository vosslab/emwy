# Track runner analyze and encode

This document covers the track runner's `analyze` subcommand and encode pipeline. Use this guide to diagnose crop-path instability before encoding and understand how the encoder processes motion-stabilized crop trajectories.

## Overview

The `analyze` subcommand diagnoses crop-path instability before encoding. It does not modify the crop trajectory or solve for new intervals; it reports on the stability and quality of a solved interval set.

**Philosophy:** diagnose before encoding. If output looks nervous (visible jitter, zoom pumping, or drift), the crop path is the first suspect. The encoder cannot fix a bad crop trajectory.

## Running analyze

Analyze requires solved intervals. Run the `solve` subcommand first.

```bash
source source_me.sh && python emwy_tools/track_runner/cli.py -i VIDEO analyze
source source_me.sh && python emwy_tools/track_runner/cli.py -i VIDEO analyze --aspect 16:9
```

The analyze subcommand outputs:

- Console report with metric summaries and dominant-symptom classification
- YAML diagnostic file saved to `tr_config/{video}.encode_analysis.yaml`

## Motion-stability metrics

The analyzer computes frame-level motion metrics to identify instability causes.

| Metric | What it measures | High values mean | Fix location |
| --- | --- | --- | --- |
| center_jerk_p50/p95 | Frame-to-frame change in crop center velocity (2D vector, px/frame) | Visible lateral jitter | Solver (more seeds) or crop controller smoothing |
| height_jerk_p50/p95 | Frame-to-frame change in crop height velocity | Zoom pumping | Crop controller size smoothing |
| crop_size_cv | Coefficient of variation of crop height | Overall zoom instability | Crop controller or aspect config |
| quantization_chatter_fraction | Fraction of frames with alternating +1/-1 center oscillation at integer boundaries | Subpixel shimmer in stationary sections | Crop controller subpixel smoothing |
| mean_confidence | Mean tracker confidence across all frames | Low = poor tracking overall | More seeds, better detection |
| low_conf_fraction | Fraction of frames with confidence < 0.5 | Coverage gaps causing drift | Add seeds in weak regions |

**Interpretation (informed by [docs/TRACK_RUNNER_CROP_PATH_FINDINGS.md](TRACK_RUNNER_CROP_PATH_FINDINGS.md)):**

- **height_jerk_p95 is the strongest single predictor of perceived output quality.** A value > 15 px/frame warrants investigation for visible zoom pumping. The V4 findings show a clear gap between watchable output (1-7) and unwatchable (9-192).
- **center_jerk_p95 alone does not predict the "seasick" quality.** IMG_3702 (unwatchable) has lower center jerk (2.7) than IMG_3830 (good, 4.7). Center jerk is useful in combination with other metrics but not as a standalone discriminator.
- `crop_size_cv` reflects intrinsic footage characteristics (runner distance range) more than crop controller quality. Telephoto footage has naturally low CV (0.10); wide-angle footage is higher (0.35-0.44). This metric is context-dependent.
- **Quantization chatter is systemic** across all test videos (14-35%), not a clean separator between good and bad output. Canon_60d has the highest chatter (34.7%) but acceptable output. Chatter is a polish issue for the crop controller, not a predictor of watchability.

## Solver-quality metrics

These metrics measure how well the solver performed during interval inference.

- **fwd_bwd_convergence_median/p90:** Forward and backward pass center convergence error, in pixels. Lower is better. Raw pixel values are resolution-dependent; **normalize by crop width** for cross-video comparison. The V4 findings show convergence/width < 2% is acceptable, > 3% shows visible issues, and > 10% indicates serious tracking failures.
- **seed_density:** Seeds per minute. Higher density improves confidence coverage but does not prevent all instability. The V4 findings show IMG_3702 has 368 seeds/min (dense) yet is unwatchable due to solver convergence issues.
- **desert_count:** Number of seedless gaps longer than 5 seconds. Each gap is a region where the crop must interpolate without anchor constraints.
- **identity_score_median:** Per-interval identity model confidence. Values < 0.5 signal weak identity discrimination.
- **competitor_margin_median:** How well the target identity separates from competitor identities. Low values (< 0.3) suggest a crowded or ambiguous scene. Canon_60d telephoto has margin 0.27, confirming telephoto identity difficulty.

## Instability region classification

The analyzer applies heuristic rules to classify instability causes. These are diagnostic hints, not oracle truth.

Four heuristic categories:

- **bbox_noise:** High jerk + high confidence. The tracker is confident but produces noisy detections. Fix: increase post-smooth weight or anchor strength in the crop controller.
- **confidence_gap:** Low confidence + moderate jerk. The tracker lost lock, and the crop drifts to compensate. Fix: add seeds in the affected time range.
- **smoothing_lag:** High velocity + jerk spikes at direction changes. The crop controller is overshooting turns. Fix: tune lag-compensation weights.
- **size_instability:** High height_jerk + low center_jerk. Zoom pumps without lateral motion, often from aspect-ratio mismatch or identity flicker. Fix: adjust aspect config or crop smoothing.

## Dominant symptom summary

The analyzer also emits a dominant-symptom label summarizing the most common cause:

- **lateral_jitter_dominated:** Most instability is frame-to-frame horizontal/vertical shimmer.
- **zoom_pumping_dominated:** Most instability is height oscillation.
- **low_confidence_drift_dominated:** Confidence gaps are the primary issue.
- **mixed:** Multiple causes present at similar intensity.

## Quantization chatter

Crop rectangles are integer tuples `(x, y, width, height)`. When a floating-point crop center or size value lands near `x.5`, it alternates between floor and ceil across frames, causing visible shimmer.

**Detection:** The analyzer uses a pattern-based detector over a sliding window. It looks for alternating +1/-1 center shifts in consecutive frames (e.g., x goes 100, 101, 100, 101, ...). This is more specific than simple magnitude thresholding, reducing false positives.

**Fix:** The crop controller's subpixel smoothing (planned feature) will round smoothly across frame boundaries instead of alternating. For now, use post-smooth filtering or accept light shimmer on stationary scenes.

## Diagnostic YAML format

The analyze subcommand writes a YAML file containing detailed metrics. This file is **diagnostic only** and does not automatically configure the solver or encoder.

Example structure (from real IMG_3830 analysis):

```yaml
# auto-generated by track_runner analyze
# this is a diagnostic report, not an encode settings file
track_runner_encode_analysis: 1
summary:
  frames: 4217
  duration_s: 140.57
  fps: 30.0
  output_size: [652, 366]
motion_stability:
  center_jerk_p50: 0.5
  center_jerk_p95: 4.743
  center_jerk_max: 22.0
  height_jerk_p50: 0.0
  height_jerk_p95: 7.0
  height_jerk_max: 42.0
  crop_size_cv: 0.3513
  quantization_chatter_fraction: 0.183
confidence:
  mean: 0.716
  low_conf_fraction: 0.235
instability_regions:
  - start_frame: 1200
    end_frame: 1206
    cause: size_instability
    mean_confidence: 0.45
    jerk_p95: 5.1
    height_jerk_p95: 12.0
    mean_instability: 8.5
dominant_symptom: lateral_jitter_dominated
solver_context:
  seed_density: 676.8
  desert_count: 0
  fwd_bwd_convergence_median: 4.6
  fwd_bwd_convergence_p90: 16.3
  identity_score_median: 0.691
  competitor_margin_median: 1.0
seed_suggestions: [1203, 2450, 3100]
diagnosis:
  primary_issue: size_instability (heuristic)
  affected_frames: 6
  suggestion_method: instability_region_max_frame
```

## Acting on the diagnosis

Use these recommendations based on the instability classification.

**confidence_gap:** The tracker lost lock in this region.

- Action: Re-solve with additional seeds at the `suggested_seed_frames` listed in the diagnostic YAML.
- Check: Are there occlusions, lighting changes, or scene cuts in this range? If yes, more seeds help.

**size_instability:** Zoom pumping (height oscillation).

- Action: Adjust aspect-ratio config (`--aspect` flag) or increase crop controller smoothing.
- Check: Does the dominant identity appear/disappear? If identity model is weak, zoom oscillates to fit the bounding box.

**bbox_noise:** Confident but noisy detections.

- Action: Increase crop controller post-smooth weight or anchor strength.
- Check: Are detections flickering slightly? Higher smoothing reduces shimmer but increases lag.

**quantization_chatter:** Subpixel oscillation.

- Action: Not yet fixable in the crop controller. Use encoder-level post-process filtering (bilateral, hqdn3d) to smooth output.
- Check: Is shimmer visible only on stationary scenes? If yes, it is subpixel oscillation.

## Encode pipeline overview

The encoder processes a solved crop trajectory through these steps:

1. **Load trajectory:** Read solved intervals from YAML.
2. **Anchor to seeds:** Tie trajectory waypoints to known seed detections.
3. **Compute crop rects:** Interpolate crop bounding boxes for each frame.
4. **Per-frame crop:** Extract the crop region from each video frame.
5. **Adaptive resize:** Rescale cropped frames to target output resolution using context-aware interpolation.
6. **Filter:** Apply optional denoise/smooth filters.
7. **FFmpeg:** Encode to output format.

### Adaptive interpolation

The encoder chooses interpolation based on scaling direction:

- **Downscaling:** INTER_AREA (high-quality area resampling, best for reducing artifacts).
- Upscaling: INTER_LANCZOS4 (sharpness preservation, minimal ringing).

This reduces blur on downscaled content and improves sharpness on modest upscaling.

## Available filters

Filters are applied after cropping and resizing, before FFmpeg encoding.

### Bilateral filter

Edge-preserving denoise. Smooths flat regions while preserving edges.

```yaml
filters:
  - kind: bilateral
    diameter: 9
    color_sigma: 75
    space_sigma: 75
```

**Use case:** Handheld footage with camera noise but sharp edges (subjects, text).

### HQDN3D filter

Temporal denoise via FFmpeg. Reduces flicker and noise across time.

```yaml
filters:
  - kind: hqdn3d
    luma_spatial: 5
    chroma_spatial: 5
    luma_temporal: 8
    chroma_temporal: 8
```

**Use case:** Noisy sensor or low-light footage.

See [docs/TRACK_RUNNER_YAML_CONFIG.md](docs/TRACK_RUNNER_YAML_CONFIG.md) for full filter configuration reference.

## Recommended presets

### Handheld footage

- Run solve with higher seed density (target 100+ seeds per minute based on V4 findings).
- Apply bilateral filter to reduce camera noise.
- Use moderate CRF (18-21 for 1080p).
- Run analyze first; if height_jerk_p95 > 15, investigate solver convergence before encoding.

### Tripod or stationary

- Fewer seeds needed but quantization chatter will be most visible.
- Run analyze to check chatter fraction (expect 15-35% is normal for all footage).
- Chatter alone does not make output unwatchable; it is a polish issue.
- Very low jerk metrics expected; if height_jerk_p95 > 5, check detection model quality.

### Telephoto or narrow FoV

- Identity discrimination is hard (V4 findings: canon_60d competitor margin = 0.27).
- Use higher seed density (250+ per minute) and manually review seed selections.
- If competitor_margin < 0.3, expect identity confusion events.
- Run analyze and check convergence/width ratio; > 3% warrants more seeds.

### Interpreting analyze output

- **First, check height_jerk_p95.** This is the strongest predictor of watchability.
- **Then check convergence/width ratio.** Divide fwd_bwd_convergence_median by crop width. > 3% suggests solver is producing noisy trajectories.
- **Low confidence alone is not a death sentence.** IMG_3830 (good) has 23.5% low-conf frames. Low confidence correlates with drift, not with jitter.
- **Chatter is universal.** All 7 test videos show 14-35% chatter. Do not treat it as the primary failure indicator.
- See [docs/TRACK_RUNNER_CROP_PATH_FINDINGS.md](TRACK_RUNNER_CROP_PATH_FINDINGS.md) for the empirical basis of these guidelines.

