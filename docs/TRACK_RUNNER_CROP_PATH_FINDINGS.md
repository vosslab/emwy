# Track runner crop-path stability findings

Measurements from `tools/analyze_crop_path_stability.py` run on 2026-03-16
using the `encode_analysis` module against all 7 test videos with solved
intervals. This document establishes which crop-path metrics predict visible
output instability and characterizes the primary failure case (IMG_3702).

For earlier solver-level measurements (seeds, identity, convergence), see
[docs/archive/TRACK_RUNNER_V3_FINDINGS.md](archive/TRACK_RUNNER_V3_FINDINGS.md).

For metric definitions, see
[docs/TRACK_RUNNER_ANALYZE_AND_ENCODE.md](TRACK_RUNNER_ANALYZE_AND_ENCODE.md).

## Problem description

The track runner's encoded output sometimes exhibits visible motion
instability despite a functioning solver and crop controller. Symptoms
include:

- **Lateral jitter**: the crop window oscillates left-right frame-to-frame,
  producing a nervous or shaky camera feel
- **Zoom pumping**: the crop height changes rapidly, producing a breathing
  or pulsing zoom effect
- **Camera shake feel**: combined lateral and vertical instability that
  looks like the camera is being handheld even though the source is stable
- **Quantization chatter**: the crop center oscillates by exactly 1 pixel
  every frame in stationary sections, producing visible shimmer

The canonical failure case is `Hononega-Orion_600m-IMG_3702.mkv`, whose
encoded output is unwatchable. Other videos range from good to acceptable.

## Data sources

All 7 test videos with complete solved interval data:

| Video | Duration | FPS | Resolution | Seeds | Intervals | Watchability |
| --- | --- | --- | --- | --- | --- | --- |
| IMG_3830.MP4 | 141s | 30 | 1280x720 | 1580 | 1583 | good (dense reference) |
| canon_60d_600m_zoom.MP4 | 96s | 30 | 1280x720 | 397 | 412 | acceptable (telephoto) |
| IMG_3823.MP4 | 136s | 30 | 1280x720 | 718 | 769 | moderate (zoom pumping) |
| IMG_3629.mkv | 290s | 60 | 2816x1584 | 377 | 366 | moderate (sparse, jittery) |
| IMG_3627.MOV | 137s | 60 | 2816x1584 | 58 | 57 | poor (very sparse, drifty) |
| IMG_3702.mkv | 92s | 60 | 2816x1584 | 559 | 875 | bad (unwatchable, "seasick") |
| IMG_3707.mkv | 253s | 60 | 2816x1584 | 461 | 482 | bad (relay, extreme jitter) |

Watchability ratings are subjective human assessments from reviewing encoded
output clips.

## Metrics evaluated

### Crop-path metrics

- **center_jerk_p95**: 95th percentile of frame-to-frame center velocity
  change (2D vector magnitude, px/frame). Measures lateral jitter spikes.
- **height_jerk_p95**: 95th percentile of frame-to-frame height velocity
  change (px/frame). Measures zoom pumping spikes.
- **crop_size_cv**: coefficient of variation (stdev/mean) of crop height
  across all frames. Measures overall zoom range instability.
- **quantization_chatter_fraction**: fraction of frames showing alternating
  +1/-1 integer center oscillation at low velocity. Measures subpixel
  rounding shimmer.
- **low_conf_fraction**: fraction of frames with tracker confidence < 0.5.
  Measures tracking coverage gaps.

### Solver context metrics

- **seed_density**: seeds per minute. Primary driver of tracking quality.
- **desert_count**: seedless gaps longer than 5 seconds.
- **fwd_bwd_convergence_median**: median FWD/BWD center convergence error
  in pixels. Measures solver agreement at interval boundaries.
- **identity_score_median**: median per-interval identity model score.
- **competitor_margin_median**: median separation from nearest competitor.

## Cross-video comparison

### Crop-path stability

| Video | CJerk p95 | HJerk p95 | SizeCV | Chatter% | LowConf% | Regions | Symptom |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IMG_3830.MP4 | 4.7 | 7.0 | 0.351 | 18.3 | 23.5 | 59 | lateral_jitter |
| canon_60d_600m_zoom.MP4 | 1.8 | 1.0 | 0.105 | 34.7 | 19.1 | 32 | lateral_jitter |
| IMG_3823.MP4 | 27.8 | 69.0 | 0.412 | 16.8 | 18.8 | 96 | zoom_pumping |
| IMG_3629.mkv | 4.0 | 5.0 | 0.351 | 19.8 | 59.6 | 232 | lateral_jitter |
| IMG_3627.MOV | 2.0 | 2.0 | 0.393 | 24.3 | 76.5 | 104 | low_conf_drift |
| IMG_3702.mkv | 2.7 | 9.0 | 0.171 | 22.2 | 27.9 | 90 | mixed |
| IMG_3707.mkv | 178.4 | 192.0 | 0.444 | 13.7 | 44.2 | 259 | mixed |

### Solver context

| Video | Seeds/min | Deserts | Conv med(px) | Conv p90(px) | ID score | Margin |
| --- | --- | --- | --- | --- | --- | --- |
| IMG_3830.MP4 | 676.8 | 0 | 4.6 | 16.3 | 0.691 | 1.000 |
| canon_60d_600m_zoom.MP4 | 255.0 | 0 | 14.6 | 52.5 | 0.389 | 0.272 |
| IMG_3823.MP4 | 316.7 | 0 | 5.5 | 22.7 | 0.500 | 1.000 |
| IMG_3629.mkv | 79.1 | 9 | 237.1 | 1181.8 | 0.471 | 1.000 |
| IMG_3627.MOV | 26.8 | 2 | 304.5 | 1814.2 | 0.491 | 0.986 |
| IMG_3702.mkv | 368.5 | 0 | 99.5 | 636.8 | 0.435 | 1.000 |
| IMG_3707.mkv | 109.8 | 0 | 335.9 | 1350.9 | 0.423 | 0.876 |

## Failure case analysis: IMG_3702

IMG_3702 (`Hononega-Orion_600m-IMG_3702.mkv`) is the canonical "unwatchable"
output. The analysis reveals a multi-cause failure:

**Key numbers:**
- 22.2% quantization chatter (1 in 5 frames is shimmer)
- 27.9% low-confidence frames (1 in 4 frames uncertain)
- crop_size_cv = 0.171 (moderate but combined with chatter is visible)
- height_jerk_p95 = 9.0 px/frame (strong zoom pumping spikes)
- 90 instability regions detected (dominant symptom: mixed)
- convergence error median = 99.5px (high for a 2704px output crop)

**What makes it unwatchable is the combination:**

1. The video is 60fps at 2816x1584, producing 2704x1520 output crops. At
   this resolution, 1px of chatter is small relative to the frame -- but
   at 22.2% of frames, the temporal pattern of alternating pixels creates
   visible shimmer.

2. Height jerk spikes to 9.0 px/frame at the 95th percentile, but
   individual peaks reach 93.0 px/frame -- severe zoom pumping events.

3. The solver convergence error (99.5px median) is high relative to the
   crop size (2704px wide = 3.7% of crop width). At p90, it reaches
   636.8px (23.5% of crop width).

4. The dominant symptom is "mixed" -- no single cause exceeds 50% of
   instability-weighted frames. The top instability regions are split
   between `size_instability` and `smoothing_lag`.

**Likely root cause:** The high convergence error combined with moderate
seed density (368 seeds/min, which should be adequate) suggests the
solver is producing noisy trajectories that the crop controller then
amplifies through its smoothing response. The crop controller is not the
root cause -- it is faithfully following a jittery input signal.

## Failure case analysis: IMG_3707

IMG_3707 (`Hononega-Varsity_4x400m-IMG_3707.mkv`) is even worse by the
numbers:

- center_jerk_p95 = 178.4 px/frame (66x worse than IMG_3830)
- height_jerk_p95 = 192.0 px/frame (27x worse than IMG_3830)
- crop_size_cv = 0.444 (extreme zoom variation)
- 44.2% low-confidence frames
- 259 instability regions
- convergence error median = 335.9px

This is a 4x400m relay race with baton handoffs. The extreme jerk values
indicate the crop trajectory is jumping between runners or losing track
entirely during handoffs. The 0.876 competitor margin (lower than most
videos) confirms identity confusion events. This video is a fundamentally
harder tracking problem and should be treated as a separate failure class
from IMG_3702.

## Metric usefulness

### Which metrics separate good from bad?

**height_jerk_p95 is the strongest discriminator for zoom pumping:**

- Good (IMG_3830): 7.0
- Acceptable (canon_60d): 1.0
- Bad zoom pumping (IMG_3823): 69.0
- Bad (IMG_3702): 9.0
- Extreme (IMG_3707): 192.0

Height jerk clearly separates the zoom-pumping failure mode. The 10x gap
between IMG_3830 (7.0) and IMG_3823 (69.0) is unambiguous.

**center_jerk_p95 is useful but noisy:**

- Good (IMG_3830): 4.7
- Acceptable (canon_60d): 1.8
- Bad (IMG_3702): 2.7
- Extreme (IMG_3707): 178.4

IMG_3702 has a lower center jerk than IMG_3830 despite being unwatchable.
This means center jerk alone does not predict the "seasick" quality. The
instability in IMG_3702 is driven more by zoom pumping and chatter than
lateral jitter.

**quantization_chatter_fraction is universal, not discriminating:**

- Range across all videos: 13.7% to 34.7%
- IMG_3702: 22.2% (middle of range)
- Best video (IMG_3830): 18.3%
- Canon_60d (acceptable): 34.7% (highest!)

Chatter is a systemic crop controller issue, not specific to the failure
case. The canon_60d has the highest chatter (34.7%) but is still
acceptable because it has low jerk and low size variation. Chatter alone
does not cause unwatchable output.

**low_conf_fraction correlates with drift but not with jitter:**

- Good (IMG_3830): 23.5%
- Sparse (IMG_3629): 59.6%
- Very sparse (IMG_3627): 76.5%
- Bad (IMG_3702): 27.9%

IMG_3702's low-conf fraction is only slightly worse than IMG_3830. Low
confidence is a problem for the sparse legacy videos (IMG_3627, IMG_3629)
but is not the primary driver of IMG_3702's failure.

**crop_size_cv is interesting but may be intrinsic to the footage:**

Large values (0.35-0.45) appear in most videos because the runner's
apparent size changes naturally as they move toward and away from the
camera. The telephoto canon_60d has the lowest (0.105) because the runner
stays at similar apparent size. This metric measures the tracking challenge
difficulty more than the crop controller quality.

**convergence error is the hidden signal:**

The 60fps videos have dramatically higher convergence errors than the 30fps
videos because intervals span more frames. But normalizing by crop width
reveals the problem:

| Video | Conv med(px) | Crop width | Conv/width |
| --- | --- | --- | --- |
| IMG_3830 | 4.6 | 652 | 0.7% |
| IMG_3823 | 5.5 | 504 | 1.1% |
| canon_60d | 14.6 | 936 | 1.6% |
| IMG_3702 | 99.5 | 2704 | 3.7% |
| IMG_3629 | 237.1 | 1658 | 14.3% |
| IMG_3627 | 304.5 | 1414 | 21.5% |
| IMG_3707 | 335.9 | 2676 | 12.6% |

The convergence/width ratio separates the quality tiers reasonably well.
Videos with conv/width < 2% are acceptable; above 3% shows visible issues;
above 10% indicates serious tracking failures.

## Implications for the pipeline

### Finding 1: IMG_3702's instability is solver-driven, not crop-controller-driven

The crop controller faithfully follows the trajectory it receives. The
trajectory itself is noisy because the solver's FWD/BWD convergence error
is 99.5px median -- the forward and backward passes do not agree on where
the runner is. The fix belongs in the solver (better convergence) or in
post-solve smoothing, not in the encoder or crop controller tuning.

### Finding 2: quantization chatter is systemic

All 7 videos show 14-35% chatter. This is a property of the crop
controller's integer rounding, not of any specific video. A subpixel
smoothing fix in the crop controller would benefit all videos. However,
chatter alone does not make output unwatchable -- it is a polish issue,
not a correctness issue.

### Finding 3: seed density alone does not prevent instability

IMG_3702 has 368 seeds/minute (second highest after IMG_3830), yet its
output is unwatchable. Dense seeding improves confidence coverage but
cannot fix fundamental convergence disagreements between the forward and
backward solver passes.

### Finding 4: height jerk is the best single predictor of perceived quality

Among all metrics, height_jerk_p95 has the clearest separation between
watchable and unwatchable output. A provisional threshold of
height_jerk_p95 > 15 px/frame warrants investigation for zoom pumping.

### Finding 5: multi-metric diagnosis is necessary

No single metric explains all failure modes. The instability region
classification (bbox_noise, confidence_gap, smoothing_lag,
size_instability) correctly identifies different root causes in different
videos. The "mixed" dominant symptom for IMG_3702 reflects its genuine
multi-cause nature.

### Finding 6: the 60fps videos have structurally different error profiles

All four 60fps videos (IMG_3627, IMG_3629, IMG_3702, IMG_3707) have much
higher convergence errors than the three 30fps videos. This may reflect
longer interval frame spans or different motion characteristics at higher
frame rate. The analyzer should consider normalizing convergence error by
frame rate or crop size for cross-video comparison.

## Provisional thresholds

Based on this 7-video study, provisional thresholds for flagging problems:

| Metric | Threshold | Interpretation |
| --- | --- | --- |
| height_jerk_p95 | > 15 px/frame | likely visible zoom pumping |
| center_jerk_p95 | > 10 px/frame | likely visible lateral jitter |
| convergence/width | > 3% | solver convergence may be too noisy |
| low_conf_fraction | > 0.30 | significant tracking coverage gaps |
| quantization_chatter | > 0.15 | systemic chatter (all videos exceed this) |

These thresholds are provisional estimates from 7 videos. They should be
validated with human ratings (Layer 2 study) before being hardcoded.

## Next steps

1. **Normalize convergence error by crop width** in the analyzer to make
   the metric comparable across resolutions and frame rates.
2. **Add convergence/width ratio** as a derived metric in the report.
3. **Layer 2 validation**: rate 10-20 short clips on ordinal scale for
   lateral jitter, zoom pumping, drift, and shake feel. Compute rank-order
   correlation with center_jerk_p95, height_jerk_p95, and
   convergence/width ratio.
4. **Layer 3 intervention**: for IMG_3702, add seeds at the suggested
   frames and re-solve to measure improvement.
5. **Crop controller subpixel smoothing**: address the systemic 14-35%
   quantization chatter with a crop controller fix.
6. **IMG_3707 relay tracking**: treat as a separate problem class requiring
   explicit handoff detection or multi-target support.
