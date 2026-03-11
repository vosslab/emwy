# Seed variability findings

Measurements from `tools/measure_seed_variability.py` run on 2026-03-11 against
two test videos with hand-drawn seed bounding boxes.

## Test videos

| Property | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| Resolution | 1280x720 | 1280x720 |
| FPS | 30 | 30 |
| Duration | ~137s | ~263s |
| Total frames (diagnostics) | 4115 | 7890 |
| Visible seeds | 292 | 296 |
| Absence markers | 11 | 11 |
| Seed density | 7.4% | 3.9% |
| Largest seed gap | 79 frames (2.6s) | 119 frames (4.0s) |
| Desert regions (>5s) | 0 | 0 |

Both videos follow a distance runner on an outdoor track with handheld camera.
The runner circles the track multiple times, creating repeating cycles as the
runner passes through the same field positions at roughly regular intervals.

## 1. Start line static phase

The runner stands at the starting line before the race begins. The current
tracker struggles with this phase.

**Track_Test-1**: 3 seeds over 2.0s (frames 0-59). Center X stays in a tight
826-836 px range (std=4.8), confirming the runner is stationary. Torso area
ranges 338-520 px^2 (mean=407, std=98). Total drift is 39.3 px (1.40x torso
height), most of which is vertical camera shake rather than runner movement.

**Track_Test-3**: Only 1 seed during the static phase. The gap to the second
seed is 116 frames (3.9s), by which time the runner has moved. The plan notes
the runner stays near cx=1100-1130 for 15+ seconds, but seed coverage is too
sparse to measure it. More seeds should be placed during the start-line phase
for Track_Test-3.

**Implication for tracker**: The stationary phase is a distinct operating mode.
A new tracker needs a "stationary lock" that holds position with minimal drift
when the runner is not moving, rather than letting prediction momentum cause
the bbox to wander.

## 2. Runner apparent size

| Statistic | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| Min torso area | 80 px^2 | 242 px^2 |
| Max torso area | 27540 px^2 | 25270 px^2 |
| Mean torso area | 1602 px^2 | 2078 px^2 |
| Median torso area | 676 px^2 | 1221 px^2 |
| Area ratio (max/min) | 344x | 104x |

The runner's apparent size varies by two orders of magnitude as they move
between the near side (large, close) and the far side (small, distant) of the
track. The median is much lower than the mean, indicating the runner spends
more time at moderate-to-far distances.

In Track_Test-1, the 80 px^2 minimum means the torso is roughly 8x10 pixels
at the farthest point. Any tracker must handle a target this small.

**Implication for tracker**: A fixed-size search window or template is
fundamentally wrong for this problem. The tracker must continuously adapt its
scale model. The scale factor between near and far is roughly 18x in linear
dimension (sqrt of 344).

## 3. Frame movement

| Statistic | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| X range | 836 px (65.3% of frame) | 988 px (77.2% of frame) |
| Y range | 400 px (55.5% of frame) | 539 px (74.9% of frame) |
| Mean per-step displacement | 1.0x torso height | 1.4x torso height |
| Median per-step displacement | 0.3x torso height | 0.6x torso height |

The runner covers most of the frame area across a full lap. Horizontal movement
dominates (mean dx ~3x mean dy), which is expected for a runner circling a
track viewed from the side.

The per-step displacement between consecutive seeds has a heavy tail (max 47x
torso height in Test-1) because seeds are not evenly spaced. When seeds are
close together, displacement is small; across gaps, it can be very large.

**Implication for tracker**: The search region for the next frame must cover a
large area, especially after the runner rounds a corner and changes direction.
Camera motion (handheld) adds additional unpredictable displacement that cannot
be separated from runner motion using seeds alone.

## 4. Jersey color variability

### Aggregate statistics (all sizes)

| Statistic | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| Hue range | 169 / 180 (94%) | 161 / 180 (89%) |
| Saturation range | 21-255 | 10-193 |
| Value range | 2-140 | 6-169 |
| Hue std | 35.2 | 25.2 |
| Value std | 20.5 | 22.1 |

At first glance, jersey color looks useless -- hue spans almost the entire HSV
wheel. But the aggregate statistics mask a strong size-dependent trend.

### Color reliability vs runner size

Hue stability by torso height bin (Track_Test-1):

| Size bin | N | Hue std | Hue range | Notes |
| --- | --- | --- | --- | --- |
| xlarge (>120px) | 11 | 0.8 | 3 | Rock-solid at H=112-113 |
| large (60-120px) | 32 | 5.9 | 29 | Usable, tight cluster 111-127 |
| medium (30-60px) | 136 | 30.2 | 169 | Unreliable, nearly full range |
| small (15-30px) | 106 | 42.1 | 163 | Noise dominates signal |
| tiny (<15px) | 7 | 52.7 | 112 | Pure noise |

Track_Test-3 shows the same pattern: large seeds have hue std=17.3, small
seeds have std=45.7.

When the runner is close (torso >60px), the true jersey color is clearly
hue ~112 (blue-green) with std under 6. The apparent "wild variability" in
the aggregate is almost entirely caused by small/distant runner pixels where
the jersey samples only a handful of pixels mixed with background.

### Causes of color instability at small sizes

- At 8-15px torso height, the jersey is only 3-5 pixels wide. A single
  background pixel sampled into the region shifts the average color drastically.
- Camera auto-exposure shifts brightness across the full track cycle.
- Shadow/sun transitions on the track cause real lighting changes, but these
  affect large seeds much less (std=0.8 vs 52.7).

### Saturation and value trends

Saturation increases with size (mean 89 at small, 157 at xlarge in Test-1),
which is expected -- small distant objects desaturate toward gray. Value
(brightness) is more stable across sizes (std ~13-18 at all sizes), suggesting
it tracks camera exposure more than target distance.

### Hue classification by color family

Using OpenCV hue ranges (0-180 scale): blue=85-130, violet=130-170,
red=0-10/170-180, orange=10-25, yellow=25-35, green=35-85.

Percentage of seeds classified as blue hue, by torso size:

| Size bin | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| All sizes | 72.3% blue | 80.7% blue |
| Tiny+small (<30px) | 56.6% blue | 52.6% blue |
| Medium (30-60px) | 77.2% blue | 82.8% blue |
| Large+xlarge (>60px) | **97.7% blue** | **92.6% blue** |

At large sizes, the jersey is almost always correctly identified as blue
(97.7% in Test-1, 92.6% in Test-3). The non-blue readings at large sizes
are mostly violet (adjacent hue), suggesting slight lighting shifts rather
than outright misclassification.

At small sizes, nearly half the readings are wrong -- landing in violet
(25%), orange (11-16%), or red (3-8%) due to background pixel contamination
in the tiny sampling region.

**Implication for tracker**: Color is a distance-dependent feature.
- When the runner is close (torso >60px), hue is a reliable discriminator.
  The jersey is definitively blue (H ~112) and can distinguish this runner
  from non-blue-jersey people.
- When distant (<30px), color should be ignored or given near-zero weight.
- A tracker could use a size-gated color model: apply color matching only when
  the predicted bbox is above a minimum size threshold.

## 5. Torso box vs full person box

| Statistic | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| Mean area ratio (full/torso) | 4.5x | 4.7x |
| Std area ratio | 1.3 | 1.7 |
| Range | 2.4x - 9.6x | 1.4x - 9.9x |
| Torso center inside full box | 4.1% | 7.1% |

The full_person_box is estimated from the user-drawn torso_box using a fixed
multiplier heuristic. The area ratio is fairly stable (mean ~4.5x) but the
containment test is alarming: the torso center falls inside the full person
box only 4-7% of the time. This means the full_person_box is systematically
offset from the torso, likely due to the estimation assuming the torso is
centered in the full body box when it is actually in the upper portion.

**Implication for tracker**: The full_person_box estimation algorithm needs
reworking. The torso-to-full-person expansion should place the torso in the
upper third of the full box, not the center.

## 6. Diagnostics bbox vs seed area (tracker accuracy)

| Statistic | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| Mean diag/seed area ratio | 13.0x | 8.5x |
| Median diag/seed area ratio | 8.8x | 7.5x |
| Max diag/seed area ratio | 86.8x | 30.8x |
| Seed area (% of frame) | 0.01-2.99% (mean 0.17%) | 0.03-2.74% (mean 0.23%) |
| Diag area (% of frame) | 0.03-13.48% (mean 1.29%) | 0.12-17.40% (mean 1.75%) |

The current tracker's bounding box is 9-13x larger than the actual runner on
average, and up to 87x larger at worst. The tracker thinks the runner occupies
1-2% of the frame when the actual runner is closer to 0.2%.

This is the single most damning metric. The tracker is not tracking the runner
so much as tracking a large region that happens to contain the runner somewhere
inside it. The crop output from such a bbox will have the runner as a small
figure in a large, mostly irrelevant frame.

**Implication for tracker**: The size estimation is fundamentally broken. A new
tracker must use seed-calibrated size priors rather than letting the Kalman
filter's size state drift unchecked.

## 7. Cyclical lap patterns

### Close-pass cluster analysis (most accurate)

The runner passes close to the camera (torso height >80px) at regular
intervals. Grouping these into clusters (seeds within 5s of each other)
gives a direct measurement of the close-pass period:

| Statistic | Track_Test-1 | Track_Test-3 |
| --- | --- | --- |
| Close-pass clusters | 4 | 8 |
| Mean close-pass period | 31.7s | 29.9s |
| Individual periods | 30.9, 31.7, 32.5s | 28.9, 28.9, 29.4, 30.3, 29.8, 32.2, 30.0s |

**The lap period is ~30-32 seconds**, consistent with a 200m indoor track
at a moderate running pace. Each close-pass cluster corresponds to one full
lap where the runner passes the camera on the near straightaway.

### Smoothed signal analysis

The 15s running-averaged center-x signal also shows periodicity, though the
smoothing window merges some adjacent half-lap peaks, inflating the apparent
period to ~38-41s. The close-pass cluster method above is more reliable.

### Cyclical structure in the plots

The plots clearly show:
- **Area**: sharp spikes when the runner is on the near side, flat low values
  when on the far side. Spikes come ~30s apart (one per lap).
- **Center X**: quasi-sinusoidal oscillation as the runner moves left-to-right
  and back.
- **Center Y**: less periodic because vertical position depends more on camera
  tilt than runner position on the track.
- **Jersey HSV**: hue and value show some cyclical structure (correlating with
  sun/shade zones on the track) but with high variance.

**Implication for tracker**: The ~30-second lap period is very stable
(individual periods vary only 29-33s) and can be used as a prior for
prediction. After tracking for 1-2 laps, the tracker can anticipate where
the runner will be in the cycle and narrow its search region. The close
pass is the easiest phase to track (large target, reliable color).

## Summary of parameter ranges for a new tracker

| Parameter | Range | Notes |
| --- | --- | --- |
| Torso area | 80 - 27540 px^2 | 344x ratio, median ~700-1200 |
| Torso linear size | ~8px to ~166px | sqrt of area range |
| Horizontal range | 65-77% of frame width | runner crosses most of the frame |
| Vertical range | 55-75% of frame height | includes camera shake |
| Per-frame displacement | 0-47x torso height | heavy tail, median 0.3-0.6x |
| Jersey hue (all sizes) | spans 89-94% of HSV range | noise at small sizes |
| Jersey hue (>60px) | std=0.8-5.9, range 3-29 | reliable when close |
| Lap period (200m track) | ~30-32 seconds | very regular (std ~1s) |
| Current tracker size error | 9-13x too large | must be fixed |

## Recommendations for the rewrite

1. **Scale adaptation is the top priority.** The tracker must handle 344x area
   variation. Use seed-calibrated size priors indexed by frame position.
2. **Use color as a size-gated feature.** When torso >60px, hue is reliable
   (std<6). When <30px, disable color matching entirely.
3. **Add a stationary-lock mode.** Detect when the runner is not moving and
   hold the bbox with minimal drift.
4. **Fix full_person_box estimation.** Place the torso in the upper third of
   the full body box, not centered.
5. **Use cyclical priors after 1-2 laps.** The ~30s lap period is very
   stable and can narrow search regions.
6. **Seed the start-line phase densely.** The first 15 seconds of each video
   need more seeds to calibrate the stationary baseline.

## Output files

- Plots: `output_smoke/seed_variability_Track_Test-1.mov.png`, `output_smoke/seed_variability_Track_Test-3.mov.png`
- CSV (raw): `output_smoke/seed_variability_*_raw.csv` -- one row per visible seed with all measurements
- CSV (smoothed): `output_smoke/seed_variability_*_smoothed.csv` -- raw and 15s running-averaged signals at each seed time
- Generated by: `tools/measure_seed_variability.py` (text report + CSV), `tools/plot_seed_variability.py` (matplotlib plots)
