# Track runner crop experiment history

This document records all crop-path stabilization experiments run on the track
runner tool, from the first axis-isolation study through the current composition
and smoothing work. Each entry states what was tested, what was found, and what
it led to.

For the crop algorithm specification, see
[docs/TRACK_RUNNER_V3_SPEC.md](TRACK_RUNNER_V3_SPEC.md). For crop-path
stability measurements, see
[docs/TRACK_RUNNER_CROP_PATH_FINDINGS.md](TRACK_RUNNER_CROP_PATH_FINDINGS.md).

## Test videos

All experiments use the same 7 test videos with solved intervals:

| Video | FPS | Resolution | Seeds/min | Role |
| --- | --- | --- | --- | --- |
| IMG_3830.MP4 | 30 | 1280x720 | 677 | Control (dense seeds, good baseline) |
| canon_60d_600m_zoom.MP4 | 30 | 1280x720 | 255 | Telephoto reference |
| IMG_3823.MP4 | 30 | 1280x720 | 317 | Strong zoom variation |
| IMG_3629.mkv | 60 | 2816x1584 | 79 | Sparse, jittery |
| IMG_3627.MOV | 60 | 2816x1584 | 27 | Very sparse, drifty |
| IMG_3702.mkv | 60 | 2816x1584 | 369 | Key failure case ("seasick") |
| IMG_3707.mkv | 60 | 2816x1584 | 217 | 4x400m relay, extreme jitter |

---

## Experiments 1-4: axis isolation (2026-03-16 to 2026-03-17)

**Plan:** [docs/archive/TRACK_RUNNER_PLAN_01_AXIS_ISOLATION.md](archive/TRACK_RUNNER_PLAN_01_AXIS_ISOLATION.md)

**Question:** Is the perceived instability caused primarily by center motion,
size motion, or both?

**Variants tested:**
- A: baseline (no overrides)
- B: center lock (offline smoothed center from solved trajectory)
- C: fixed crop height (constant size across full clip)
- D: slow size tracking (heavy EMA on height)
- E: center lock + fixed crop
- F: center lock + slow size

**Result:** All 6 variants produced visually indistinguishable output. Metrics
showed no meaningful separation between any variant.

**Root cause found:** `crop_fill_ratio` was 0.1 (crop height = 10x person
height), making the runner a tiny dot in the frame. At that zoom level, none
of the stabilization axes had visible effect because the runner was too small
to notice composition problems.

**Conclusion:** The experiment design was sound but the parameter space was
wrong. `fill_ratio` was the first-order problem, not center or size smoothing.

**Led to:** Experiment 5 with tighter fill ratio.

---

## Experiment 5: constraint stabilization (2026-03-17 to 2026-03-19)

**Plan:** [docs/archive/TRACK_RUNNER_PLAN_02_CONSTRAINT_STABILIZATION.md](archive/TRACK_RUNNER_PLAN_02_CONSTRAINT_STABILIZATION.md)

**Question:** Does tighter crop geometry plus containment constraints produce
a virtual dolly cam feel?

**Variants tested:**
- A_old_baseline: `fill_ratio=0.1`, no constraints (prior default)
- B_tight_030: `fill_ratio=0.3`, containment clamp, zoom constraint
- C_tight_040: `fill_ratio=0.4`, containment clamp, zoom constraint
- D_tight_030_no_contain: `fill_ratio=0.3`, no containment

**Key changes introduced:**
- Composition-quality metrics added to `encode_analysis.py` (center_offset,
  edge_touch, bad_frame_fraction)
- Double-clamp containment (clamp, re-smooth, re-clamp) in `tr_crop.py`
- Scalar `max_height_change` rate limiter for zoom smoothing

**Result:** `fill_ratio=0.3` was a clear first-order fix. The runner became a
meaningful part of the frame. `fill_ratio=0.4` cut off feet. Containment
clamp prevented the torso from drifting to the edge of the crop.

**User review feedback:**
- 0.3 better than 0.4 (feet visible at 0.3, cut at 0.4)
- Crop above torso (head) should be tighter than below (legs are longer)
- New rule: torso box must ALWAYS be closer to center than to edge
- Zoom smoothing rated "poor" -- needs more aggressive smoothing

**Conclusion:** First-order problem fixed. Runner is now meaningfully framed.
Remaining issues are zoom smoothing and vertical composition.

**Led to:** Experiment 6 (smart mode attempt) and later zoom-specific work.

---

## Experiment 6: smart mode v1a (2026-03-17 to 2026-03-18)

**Plan:** [docs/archive/TRACK_RUNNER_PLAN_03_SMART_MODE_V1A.md](archive/TRACK_RUNNER_PLAN_03_SMART_MODE_V1A.md)

**Question:** Can a regime-switching crop controller (clear/uncertain/distance)
improve output quality by adapting crop behavior to trajectory confidence?

**Variants tested:**
- A_baseline_dc: direct_center (the Experiment 5 winner)
- B_smart_v1a: regime-switching controller with per-regime fill_ratio and
  size_update_mode

**Key design:** Three regimes (clear, uncertain, distance) classified per-frame
from trajectory confidence and geometric signals. Each regime sets different
fill_ratio and zoom behavior. Vertical asymmetry offset and torso protection
applied globally.

**Result on IMG_3702:** "Rocking boat sensation" and "zoom inconsistency is
noticeable." 21 regime transitions in 92 seconds (one every ~4.4s), each
changing fill_ratio and creating visible zoom changes.

**User review:** baseline_dc is "quite good" -- smart mode was worse on the
key failure case. Too many regime transitions create instability they were
supposed to prevent.

**Root causes:**
- Vertical asymmetry offset tied to per-frame bbox height creates coupling
  between tracking noise and camera vertical motion
- Regime transitions are too frequent and visible
- Broad regime switching is too coarse for this problem

**Conclusion:** Rejected. Direct_center baseline outperforms smart mode on the
key failure case. The problem is not broad regime switching -- it is specific
failure modes (zoom transitions, composition) that need targeted fixes.

**Led to:** Return to direct_center baseline with targeted orthogonal fixes.

---

## Experiment 7: zoom-event detection (2026-03-18)

**Plan:** [docs/archive/TRACK_RUNNER_PLAN_04_COMPOSITION_ZOOM.md](archive/TRACK_RUNNER_PLAN_04_COMPOSITION_ZOOM.md)

**Question:** Can single-frame height-ratio detection identify and damp
discrete camera zoom jumps (iPhone 1X/2X/5X mode switching)?

**Variants tested:**
- A_baseline_dc: direct_center baseline
- B_torso_38: composition offset only (`torso_anchor=0.38`)
- C_zoom_hold: zoom event detection + hold behavior
- D_combined: both composition and zoom hold

**Result:** Single-frame zoom detection failed. iPhone lens transitions spread
over 2-5 frames at 60fps, producing per-frame height ratios of ~1.15 to ~1.26
(barely above or below the 1.25 threshold). Most transitions were missed.

Additionally, using a single median output resolution on multimodal footage
produced full-frame output (2816x1584), making the runner tiny and the
experiment uninterpretable.

**Conclusion:** Single-frame detection is the wrong approach for multi-frame
zoom transitions. Need a sliding-window detector.

**Led to:** Experiment 7b with sliding-window zoom detection.

---

## Experiment 7b: sliding-window zoom stabilization (2026-03-19)

**Plan:** [docs/archive/TRACK_RUNNER_PLAN_05_SLIDING_WINDOW.md](archive/TRACK_RUNNER_PLAN_05_SLIDING_WINDOW.md)

**Question:** Does a 3-mode piecewise zoom controller (normal drift, transition
freeze, settling convergence) with a sliding-window detector reduce zoom
pumping?

**Variants tested:**
- A_baseline_dc: direct_center, no zoom stabilization, `torso_anchor=0.50`
- B_torso_38: no zoom stabilization, `torso_anchor=0.38`
- C_zoom_stabilized: 3-mode zoom controller, `torso_anchor=0.50`
- D_zoom_stabilized_torso_38: 3-mode zoom + `torso_anchor=0.38`

**Sliding-window detector design:**
- 5-frame window, max/min height ratio threshold 1.40
- Three modes: normal (full rate), transition (0.02x rate, near-freeze),
  settling (0.20x rate, slow convergence with biased monotonicity)
- Settling duration: 60 frames (1s at 60fps)
- Biased monotonicity: suppress small height reversals (< 0.3% of height),
  allow sustained reversals after 5 consecutive confirming frames

**Result:** Zoom stabilization improved height_jerk_p95 on most videos.
Composition offset (`torso_anchor=0.38`) improved vertical framing.

**Led to:** Experiment 7c for further monotonicity refinement.

---

## Experiment 7c: global biased monotonicity (2026-03-19)

**Question:** Does applying biased monotonicity globally (not just in settling
windows) further reduce CropHVar and zoom bounce?

**Variants tested:** Same 4-variant structure as 7b with global monotonicity
applied to all frames.

**Result:** Reduced CropHVar (crop height variance) but visible zoom bounce
persisted, especially on IMG_3702. The rate limiter was still producing
staircase-like height changes that created visible bounce.

**Led to:** Experiment 7d to isolate the EMA vs rate-limiter interaction.

---

## Experiment 7d: EMA x zoom stabilization factorial (2026-03-19 to 2026-03-20)

**Question:** How do EMA size smoothing and the rate limiter interact? Which
combination produces the least zoom bounce?

**Variants tested (2x2 factorial):**
- A_baseline_dc: no EMA, no zoom stabilization
- B_size_smooth: EMA on height only (`alpha_size=0.05`)
- C_zoom_stab: rate-limiter zoom stabilization only
- D_smooth_zoom: EMA + rate limiter combined

**Key finding:** Variant D (both combined) had the WORST pixel bounce rate
(12.3 bounces/s on IMG_3707), worse than B (EMA only, 4.5 bounces/s). The
rate limiter re-quantized the smooth EMA output into staircase steps,
reintroducing the exact artifacts the EMA had removed.

**Ranking:** B > C > A > D

**Destructive interaction confirmed:** EMA produces a smooth curve. The rate
limiter quantizes it into piecewise-linear segments. Running both in series
is worse than running either alone.

**Conclusion:** EMA smoothing and rate limiting are mutually exclusive
mechanisms. When EMA is active, the rate limiter must be bypassed.

**Led to:** Experiment 8 to validate the bypass fix.

---

## Experiment 8: rate-limiter bypass validation (2026-03-20)

**Plan:** [docs/archive/TRACK_RUNNER_PLAN_06_ZOOM_BOUNCE_FIX.md](archive/TRACK_RUNNER_PLAN_06_ZOOM_BOUNCE_FIX.md)

**Question:** Does bypassing the rate limiter when `alpha_size > 0` fix the
EMA + limiter destructive interaction found in 7d?

**Code change:** Added a gate in `direct_center_crop_trajectory()`: when
`alpha_size > 0`, the rate limiter block (both 3-mode and scalar branches) is
skipped entirely. When `alpha_size == 0`, rate limiter behavior is unchanged.

**Variants tested:**
- B_baseline: EMA on (`alpha_size=0.05`), zoom stabilization off
- D_gated: same config as 7d D (EMA + zoom_stab + limiter), but code gate
  bypasses limiter because `alpha_size > 0`

**Result:** B_baseline and D_gated produced **identical** output on all metrics
across all 7 videos. height_jerk_p95 = 1.0 on all videos (matching baseline).
Pixel zoom assessment confirmed ~6 bounces/s (down from 12.3 in 7d D).

**Conclusion:** Rate-limiter bypass when EMA active is correct. The destructive
interaction is fully resolved. EMA handles zoom stability; rate limiter handles
the non-EMA path. They never run in series.

**Visual review noted:** Composition issue still present -- too much headroom,
feet cropped. This is a `torso_anchor` problem (still at 0.50), not related to
the bounce fix.

**Led to:** Experiment 9A (composition offset isolation).

---

## Experiment 9A: composition offset isolation (2026-03-23)

**Plan:** [docs/TRACK_RUNNER_EXPERIMENT_9_PLAN.md](../docs/../.claude/plans/peaceful-hatching-kitten.md) (active)

**Question:** Does a single global `torso_anchor` value (0.38) fix the
headroom/feet framing problem across all 7 videos?

**Background:** `torso_anchor` is a simple normalized vertical bias:
`composition_offset = (0.50 - torso_anchor) * smoothed_h`. Setting anchor to
0.38 shifts the torso up in the frame, leaving ~62% of vertical space below
for legs and ~38% above for head.

**Variants tested:**
- A_current: `torso_anchor=0.50` (centered, baseline from Experiment 8)
- B_anchor: `torso_anchor=0.38` (subject higher in frame)

**Fixed parameters (both):** `crop_mode=direct_center`, `fill_ratio=0.30`,
`alpha_size=0.05`, `alpha_pos=0.0` (position smoothing off),
`containment_radius=0.20`, limiter bypass active.

**Results:**

| Video | A TorsoMed | B TorsoMed | A Upper% | B Upper% |
| --- | --- | --- | --- | --- |
| canon_60d | 0.499 | 0.379 | 0.2% | 97.5% |
| IMG_3702 | 0.500 | 0.380 | 0.0% | 99.8% |
| IMG_3707 | 0.500 | 0.380 | 0.1% | 99.2% |
| IMG_3627 | 0.500 | 0.380 | 0.1% | 92.6% |
| IMG_3629 | 0.500 | 0.380 | 0.2% | 95.9% |
| IMG_3823 | 0.500 | 0.442 | 0.0% | 21.1% |
| IMG_3830 | 0.500 | 0.425 | 0.0% | 42.8% |

**Regression guards (all passed):**
- height_jerk_p95: identical A vs B on all 7 videos (no zoom regression)
- edge_touch_count: 0 on both variants across all 7 videos
- bad_frame_pct: same or slightly improved
- CropHVar, zoom phases, SizeCV: all identical (anchor is composition-only)

**Observations:**
- 5 of 7 videos (60fps and telephoto) get the full shift: torso median at 0.38
- IMG_3823 and IMG_3830 (30fps, wide-angle) only shift partially (median 0.44
  and 0.42) because the containment clamp limits the downward shift
- No stability regressions on any video

**Status:** Awaiting visual review for decision fork.

**Decision fork:**
- YES (framing improves across all videos): lock anchor, proceed to 9B
- NO (works on some, breaks others): stop tuning, move to phase-dependent anchor

**Next planned:** Experiment 9B (position smoothing, `alpha_pos=0.03` vs 0.0)

---

## Experiment progression summary

| Exp | Date | What changed | Key finding |
| --- | --- | --- | --- |
| 1-4 | 2026-03-16 | Center lock, fixed size, slow size | All indistinguishable (fill_ratio=0.1 was root cause) |
| 5 | 2026-03-17 | fill_ratio=0.3, containment, zoom constraint | First-order fix: runner visible in frame |
| 6 | 2026-03-18 | Smart mode regime switching | Rejected: rocking boat, too many transitions |
| 7 | 2026-03-18 | Single-frame zoom detection | Failed: missed multi-frame iPhone transitions |
| 7b | 2026-03-19 | Sliding-window zoom, 3-mode controller | Improved height_jerk, composition better at 0.38 |
| 7c | 2026-03-19 | Global biased monotonicity | Reduced CropHVar, bounce still present |
| 7d | 2026-03-19 | 2x2 EMA x rate limiter | EMA + limiter = WORST (destructive interaction) |
| 8 | 2026-03-20 | Rate-limiter bypass when EMA active | Bypass validated: B == D_gated on all metrics |
| 9A | 2026-03-23 | torso_anchor=0.38 | Framing improved on 5/7 full, 2/7 partial |

## Key learnings across all experiments

1. **Fill ratio was the first-order problem.** Experiments 1-4 were wasted
   because the runner was too small to evaluate. Always check that the
   experimental signal is large enough to measure before running variants.

2. **Broad regime switching is worse than targeted fixes.** Smart mode
   (Experiment 6) created more instability than it solved. Targeted orthogonal
   fixes (containment, zoom damping, composition offset) work better.

3. **EMA and rate limiting are mutually exclusive.** The Experiment 7d
   factorial was the most important single finding: combining smoothing
   mechanisms in series can be destructive, not additive.

4. **Metrics must match the visual complaint.** Experiments 1-4 measured
   average smoothness but the problem was composition quality. Experiment 5
   added composition metrics and immediately found the real issue.

5. **One variable at a time.** The sequential approach (5 -> 6 -> 7 -> 8 -> 9)
   has been more productive than the factorial approach (7d), because each
   experiment cleanly isolates one effect.

6. **The direct_center baseline is surprisingly strong.** Every attempt to
   replace it (smart mode, regime switching) has performed worse. Targeted
   additions to the baseline have been the successful path.
