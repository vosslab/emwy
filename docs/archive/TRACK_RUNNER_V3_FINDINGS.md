# Track runner v3 findings

Measurements from `tools/analyze_track_runner_json.py` (v1.0.0) run on 2026-03-13 against
three test videos with track runner v3 JSON data (seeds, intervals, diagnostics).

For earlier v1/v2 era measurements using YAML seed files, see
[docs/archive/SEED_VARIABILITY_FINDINGS.md](SEED_VARIABILITY_FINDINGS.md).

## Test videos

| Property | IMG_3629.mkv | IMG_3830.MP4 | canon_60d_600m_zoom.MP4 |
| --- | --- | --- | --- |
| FPS | 30 | 30 | 30 |
| Duration | ~574s | ~141s | ~95s |
| Total seeds | 425 | 1580 | 397 |
| Visible | 278 | 1056 | 351 |
| Partial | 89 | 470 | 45 |
| Approximate | 0 | 54 | 0 |
| Not-in-frame | 10 | 0 | 1 |
| Legacy obstructed | 48 | 0 | 0 |
| Seeds/minute | 44.5 | 674.4 | 250.1 |
| Seeds/1000 frames | 24.7 | 374.7 | 139.0 |
| Max gap | 609 fr (20.3s) | 40 fr (1.33s) | 84 fr (2.8s) |
| Desert regions (>5s) | 24 | 0 | 0 |
| Solved intervals | 45 | 1583 | 412 |
| Diagnostics | NO | YES (1575) | YES (395) |

IMG_3629 is the sparsest dataset: hand-seeded with `initial` mode only, large gaps, and
only 45 solved intervals from an early cache. Its 48 legacy `obstructed` seeds predate
the v3 status vocabulary (migrated to `approximate` during load when `torso_box` is present).

IMG_3830 is the densest: 674 seeds/minute using all seeding modes (target_refine,
interactive_refine, bbox_polish, solve_refine, edit_redraw). Zero desert regions.

canon_60d_600m_zoom is a telephoto video with large subjects. Only two seeding modes
(initial, target_refine) but dense enough to avoid deserts.

## Seed coverage and seeding modes

IMG_3830 demonstrates the v3 refinement workflow: only 113 seeds (7.2%) are `initial`,
while 820 (51.9%) are `target_refine` and 271 (17.2%) are `interactive_refine`. This
iterative refinement drives the high seed density.

canon_60d_600m_zoom shows a simpler pattern: 71 initial seeds (17.9%) plus 326
target_refine seeds (82.1%).

IMG_3629 uses only `initial` mode (425 seeds), reflecting pre-v3 hand annotation.

## Torso area variability

| Video | Min | Max | Mean | Median | Ratio |
| --- | --- | --- | --- | --- | --- |
| IMG_3629.mkv | 600 px^2 | 483,916 px^2 | 15,754 px^2 | 4,140 px^2 | 806.5x |
| IMG_3830.MP4 | 210 px^2 | 18,564 px^2 | 2,138 px^2 | 656 px^2 | 88.4x |
| canon_60d_600m_zoom.MP4 | 2,625 px^2 | 20,819 px^2 | 6,867 px^2 | 6,500 px^2 | 7.9x |

IMG_3629 has the most extreme area ratio (806.5x) because the runner traverses the full
distance range from far-field to near-camera. The median of 4,140 px^2 corresponds to
roughly a 64px linear size.

IMG_3830 has a median of only 656 px^2 (about 25px linear), meaning most seeds are small.
62.3% of seeds fall in the `small` bin (15-30px linear).

canon_60d_600m_zoom is dominated by `large` bin (96.5% of seeds in 60-120px). The 7.9x
area ratio is tight, consistent with telephoto footage where the runner stays at similar
apparent size.

### Size bin distributions

| Bin | IMG_3629 | IMG_3830 | canon_60d_600m |
| --- | --- | --- | --- |
| tiny (<15px) | 0 | 12 | 0 |
| small (15-30px) | 4 | 985 | 0 |
| medium (30-60px) | 158 | 308 | 11 |
| large (60-120px) | 147 | 267 | 382 |
| xlarge (>120px) | 58 | 8 | 3 |

## Jersey color variability by size

| Video | Bin | Count | Hue mean | Hue std | Hue range |
| --- | --- | --- | --- | --- | --- |
| IMG_3629 | small | 4 | 69.0 | 58.4 | 106 |
| IMG_3629 | medium | 158 | 88.5 | 48.8 | 153 |
| IMG_3629 | large | 147 | 113.4 | 25.1 | 118 |
| IMG_3629 | xlarge | 58 | 112.0 | 23.3 | 104 |
| IMG_3830 | tiny | 12 | 120.1 | 6.7 | 20 |
| IMG_3830 | small | 972 | 114.1 | 22.1 | 162 |
| IMG_3830 | medium | 275 | 117.6 | 7.8 | 69 |
| IMG_3830 | large | 259 | 114.8 | 10.6 | 112 |
| IMG_3830 | xlarge | 8 | 115.0 | 0.8 | 2 |
| canon_60d_600m | medium | 11 | 15.4 | 5.1 | 18 |
| canon_60d_600m | large | 382 | 52.5 | 52.6 | 167 |

The size-gated color finding from the v1/v2 study is confirmed for IMG_3629: hue std drops
from 48.8 at medium to 25.1 at large, and the mean converges to ~113 (blue).

IMG_3830 shows a surprising result: the `tiny` bin (n=12) has hue std of only 6.7, much
lower than `small` (std=22.1). This is likely sample size artifact (only 12 tiny seeds).
At medium and above, hue stabilizes around 115-118 with std 7.8-10.6.

canon_60d_600m_zoom has very high hue std (52.6) even at the `large` bin. This video tracks
a different jersey color (hue ~52, orange/yellow) and the wide hue range (167) suggests
lighting variation or color shifts across the telephoto field of view.

## Interval solver quality

### Confidence breakdown

| Tier | IMG_3629 | IMG_3830 | canon_60d_600m |
| --- | --- | --- | --- |
| high | 77.8% | 75.6% | 38.6% |
| good | 0.0% | 17.9% | 40.0% |
| fair | 11.1% | 4.8% | 19.2% |
| low | 11.1% | 1.7% | 2.2% |

IMG_3830 achieves the lowest failure rate (1.7% low), matching its high seed density.
IMG_3629 has the highest low-confidence rate (11.1%), but only 45 intervals total (5 low).
canon_60d_600m_zoom has only 2.2% low but the lowest high-confidence rate (38.6%) because
most intervals land in good/fair tiers.

### Failure reasons

| Reason | IMG_3629 | IMG_3830 | canon_60d_600m |
| --- | --- | --- | --- |
| low_agreement | 6 | 320 | 67 |
| low_separation | 0 | 234 | 292 |
| weak_appearance | 0 | 1 | 251 |
| likely_identity_swap | 0 | 68 | 106 |

IMG_3629 failures are exclusively `low_agreement` (6 out of 45 intervals, 13%).

IMG_3830 failures are dominated by `low_agreement` (320) and `low_separation` (234). The
68 `likely_identity_swap` events suggest multi-runner confusion in some segments.

canon_60d_600m_zoom is dominated by `low_separation` (292) and `weak_appearance` (251).
The weak_appearance rate is very high (61% of intervals flagged). This correlates with the
high hue std noted above: the identity scorer reports low confidence because the appearance
model is unreliable for this video's lighting conditions.

### Score distributions

| Score | IMG_3629 p25/median/p75 | IMG_3830 p25/median/p75 | canon_60d p25/median/p75 |
| --- | --- | --- | --- |
| agreement | 0.56 / 0.73 / 0.83 | 0.57 / 0.80 / 0.90 | 0.61 / 0.78 / 0.87 |
| identity | 0.76 / 0.86 / 0.92 | 0.50 / 0.69 / 0.84 | 0.37 / 0.39 / 0.41 |
| margin | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 0.20 / 0.27 / 0.42 |

Agreement scores are reasonably similar across all three videos (medians 0.73-0.80).

Identity scores vary dramatically: IMG_3629 median 0.86 (good), IMG_3830 median 0.69
(moderate), canon_60d_600m_zoom median 0.39 (poor). The telephoto video's low identity
scores explain the high weak_appearance rate.

Competitor margin tells the starkest story: IMG_3629 and IMG_3830 have median 1.0 (no
competitors), while canon_60d_600m_zoom has median 0.27. This means other detected objects
frequently score nearly as well as the target in the telephoto video.

### Meeting point error

| Metric | IMG_3629 median/p90 | IMG_3830 median/p90 | canon_60d median/p90 |
| --- | --- | --- | --- |
| center_err_px | 10.5 / 48.5 | 4.6 / 16.3 | 14.6 / 52.5 |
| scale_err_pct | 0.16 / 0.37 | 0.09 / 0.34 | 0.18 / 0.49 |

IMG_3830 has the tightest meeting point agreement (median 4.6px center error), reflecting
high seed density driving accurate convergence. canon_60d_600m_zoom has the largest errors
(median 14.6px, p90 52.5px).

### Fused track quality

| Metric | IMG_3629 | IMG_3830 | canon_60d_600m |
| --- | --- | --- | --- |
| Total points | 431 | 5,918 | 3,604 |
| Merged % | 91.4% | 94.8% | 95.2% |
| Fuse flag % | 8.6% | 5.2% | 4.8% |

Merged rates are high across all three videos (91-95%), meaning forward and backward
tracks agree at most frames. Fuse flag rates (frames where forward/backward disagreed
enough to require special handling) are low (5-9%).

## Cross-video comparison

| Video | Median area | Seeds/min | High% | Low% |
| --- | --- | --- | --- | --- |
| IMG_3629.mkv | 4,140 | 44.5 | 77.8% | 11.1% |
| IMG_3830.MP4 | 656 | 674.4 | 75.6% | 1.7% |
| canon_60d_600m.MP4 | 6,500 | 250.1 | 38.6% | 2.2% |

**Seed density vs low-confidence rate**: IMG_3830 has the highest seed density (674/min)
and the lowest low-confidence rate (1.7%). IMG_3629 has the lowest density (44.5/min) and
the highest low-confidence rate (11.1%). This supports the expectation that denser seeding
produces more reliable interval solving.

**Subject size vs confidence**: canon_60d_600m_zoom has the largest median subject (6,500
px^2) but the lowest high-confidence rate (38.6%). This breaks the naive assumption that
bigger subjects are easier to track. The telephoto video's challenge is not size but
appearance discrimination: low competitor margins and unreliable identity scores dominate.

## Implications

1. **Seed density is the primary driver of low-confidence prevention.** IMG_3830's 674
   seeds/minute achieves 1.7% low-confidence vs 11.1% at 44.5 seeds/minute (IMG_3629).
   The v3 refinement workflow (target_refine, interactive_refine) is the mechanism for
   achieving this density.

2. **Appearance identity scoring is the main bottleneck for telephoto video.** The
   canon_60d_600m_zoom video has 61% weak_appearance flags and identity scores clustered
   at 0.37-0.41 (near random). The HSV histogram scorer is unreliable when lighting
   shifts across the telephoto field and when competitors are similar in appearance.

3. **Competitor margin is a strong discriminator.** Videos with median margin 1.0
   (IMG_3629, IMG_3830) have high-confidence rates of 76-78%, while canon_60d_600m_zoom
   (median 0.27) drops to 39%. This suggests the interval solver works well when the
   target is the only plausible detection, and struggles with multi-target scenes.

4. **Legacy sparse annotations (IMG_3629) still produce usable intervals.** 78% high
   confidence from only initial-mode seeds at 44.5/min density. The intervals are few
   (45) but mostly good. Adding refinement modes would fill the 24 desert gaps.

5. **Meeting point error tracks seed density.** IMG_3830's 4.6px median center error
   vs canon_60d_600m_zoom's 14.6px correlates with seed density, not subject size.
   Denser seeding constrains the forward/backward propagators to converge tighter.

## Data sources

- Seeds JSON: human annotations with status, mode, torso_box, jersey_hsv
- Intervals JSON: fused FWD/BWD tracking with per-interval scoring
- Diagnostics JSON: per-frame agreement, identity, margin scores (where available)
- Analysis script: [tools/analyze_track_runner_json.py](../../tools/analyze_track_runner_json.py)
- Output artifacts: `output_smoke/track_runner_analysis_*.csv`,
  `output_smoke/track_runner_analysis_summary.json`
