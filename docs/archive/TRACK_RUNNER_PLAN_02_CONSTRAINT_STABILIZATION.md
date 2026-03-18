# Virtual Dolly Cam: Constraint-Based Stabilization Plan

## Setup

Track runner encodes cropped video of a runner from handheld sports footage. The crop pipeline follows a solved trajectory (per-frame bounding box from YOLO detection + interval solver) and produces a crop rectangle for each frame. The current system uses `direct_center` crop mode: center the crop on the smoothed trajectory, compute crop size from the detected bounding box height divided by a fill ratio, apply forward-backward EMA smoothing, clamp to frame bounds, and optionally cap velocity.

The prior axis-isolation experiment (2026-03-17) tested 6 variants (A baseline through U combined override passes) and all produced visually indistinguishable output. The torso box regularly drifted to the edge of the crop frame, and zoom remained uneven and jerky. The experiment metrics (center jerk, height jerk, quantization chatter) measured instability but not composition quality, so they could not detect these failures.

Note: milestone numbers in this plan are labels within this plan only and do not refer to milestones from the failed prior experiment.

## Goal

Determine whether tighter crop geometry, center containment constraints, and scale stability constraints can make the crop output look like a virtual dolly cam shot: the runner stays visually centered, the camera moves smoothly, and there are no panic recentering events or zoom pumping spikes. Success is measured by extreme-value containment metrics (p95, max, worst-run-length), not by average smoothness.

## Design philosophy

**The runner should be the stable perceptual anchor.** The viewer should feel like a smooth camera is tracking the runner, not like a crop window is chasing a detection box.

**Source-frame containment is a soft rendering constraint, not a camera-motion constraint.** The virtual camera path is solved in runner-centered coordinates first. Source bounds are enforced only at render time, and limited black-border exposure is acceptable when needed to preserve subject stability and avoid abrupt corrective motion. A crop window that never shows black but keeps twitching is obviously fake. A mostly stable frame with occasional border exposure reads as intentional stabilization.

**Priority hierarchy:**
1. Keep the runner inside a protected composition zone
2. Keep camera motion smooth and low-order
3. Keep zoom motion smooth
4. Minimize black-border exposure
5. Only as a last resort, recenter aggressively to avoid black areas

**Failure policy:** prefer temporary black border drift over panic recentering or edge-chasing behavior.

This plan is a controlled stabilization cycle, not a crop-system redesign. It adds composition-quality metrics first to measure the actual failure, then applies two targeted fixes (tighter fill ratio as the first-order fix, containment clamp as the second-order fix) and validates on all test videos. Public API growth happens only after the experiment shows measurable improvement on the metrics that match the visual complaint.

**The annotated torso box is a supervisory signal for subject location, not the literal virtual camera target.** The box is a human-guided measurement that varies due to annotation noise, interpolation between annotated frames, posture changes, and human inconsistency. The crop should enforce perceptual composition rules instead of blindly following the boxes. The anchor should be derived from the box (e.g., box center or torso-core point), not equal to the box.

**Design slogan: The subject must stay centered by constraint, not by average tendency.**

## Scope

- Add composition-quality metrics to `encode_analysis.py` focused on extreme values
- Fix crop geometry in `direct_center_crop_trajectory()` -- tighter fill ratio is the first-order fix, containment clamp is the second-order fix
- Add constraint-based center clamping that prevents edge drift
- Run diagnostic and validation experiments on all 7 test videos
- Update experiment harness and changelog

## Non-goals

- Changing the trajectory solver or detection model
- Adding new crop modes (work within `direct_center` mode)
- Real-time/online `CropController` changes (stay offline)
- Architectural refactors or new modules

## Current state

- **First-order problem:** `crop_fill_ratio=0.1` makes crop 10x person height -- enormous window where subject is tiny and can drift far from center. This alone explains most of the failure. Note: the V3 spec (`docs/TRACK_RUNNER_V3_SPEC.md`) documents `target_fill_ratio: 0.30` as the design default, but the runtime config diverged to 0.1. Tightening to 0.3-0.4 is a return to the spec intent, not a novel change.
- Frame-edge clamping + velocity cap creates edge-lock: once crop hits boundary, it gets stuck
- All existing metrics (center_jerk, height_jerk, chatter, size_cv) measure instability, not composition quality
- No metric tracks where the subject sits within the crop frame
- Prior experiment override functions exist but operate on the wrong baseline geometry

## Architecture boundaries

All changes stay within these files:

| Component | File | Change type |
| --- | --- | --- |
| Composition metrics | `emwy_tools/track_runner/encode_analysis.py` | Add new metric functions |
| Crop geometry | `emwy_tools/track_runner/tr_crop.py` | Modify `direct_center_crop_trajectory()` |
| Diagnostic script | `tools/analyze_crop_path_stability.py` | Update for composition metrics |
| Experiment harness | `tools/batch_encode_experiment.py` | Update variants and metric display |
| Tests | `emwy_tools/tests/test_encode_analysis.py` | Add metric tests |
| Tests | `emwy_tools/tests/test_tr_crop.py` | Add constraint tests |
| Changelog | `docs/CHANGELOG.md` | Update |

## Test videos (all 7 with solved intervals)

All diagnostic and validation runs use these 7 videos:

| Video | Intervals file | Notes |
| --- | --- | --- |
| canon_60d_600m_zoom.MP4 | tr_config/canon_60d_600m_zoom.MP4.track_runner.intervals.json | Fair reference: pre-stabilized in ShotCut, near-target quality |
| Hononega-Orion_600m-IMG_3702.mkv | tr_config/Hononega-Orion_600m-IMG_3702.mkv.track_runner.intervals.json | Failure case, high convergence error |
| Hononega-Varsity_4x400m-IMG_3707.mkv | tr_config/Hononega-Varsity_4x400m-IMG_3707.mkv.track_runner.intervals.json | Relay extreme |
| IMG_3627.MOV | tr_config/IMG_3627.MOV.track_runner.intervals.json | |
| IMG_3629.mkv | tr_config/IMG_3629.mkv.track_runner.intervals.json | Dense refined |
| IMG_3823.MP4 | tr_config/IMG_3823.MP4.track_runner.intervals.json | Strong zoom |
| IMG_3830.MP4 | tr_config/IMG_3830.MP4.track_runner.intervals.json | Control video |

## Mapping: milestones to components and patches

| Milestone | Component | Patches |
| --- | --- | --- |
| M1: Composition metrics | encode_analysis, tests | Patch 1-2 |
| M2: Diagnostic run | analyze_crop_path_stability | Patch 3 |
| M3: Constraint-based crop | tr_crop, tests | Patch 4-5 |
| M4: Validation experiment | batch_encode_experiment, changelog | Patch 6 |

---

## Milestone M1: Add composition-quality metrics

Depends on: none
Entry criteria: none
Exit criteria: new metrics compute correctly on synthetic data; pass pytest

### Goal

Add first-class metrics that measure where the subject sits within the crop, focused on extreme values and run-length of bad frames.

### New metrics to add to `analyze_crop_stability()`

The trajectory provides per-frame `cx, cy, w, h` (subject center and bbox). The crop_rects provide per-frame `(x, y, w, h)` (crop rectangle).

**Per-frame signals:**
- `center_offset_px[i]` = euclidean distance from subject center to crop center, using anisotropic normalization:
  - `dx_norm = (traj_cx - crop_cx) / crop_w`
  - `dy_norm = (traj_cy - crop_cy) / crop_h`
  - `center_offset_norm[i] = hypot(dx_norm, dy_norm)`
- `edge_margin_px[i]` = minimum distance from subject bbox edge to any crop edge (4 margins: left, right, top, bottom; take the minimum)
- Per-axis normalized margins: left/right margins divided by crop_w, top/bottom margins divided by crop_h
- `edge_margin_norm[i]` = min of all four per-axis normalized margins
- Three per-cause bad frame flags:
  - `bad_center_frame[i]` = True if center_offset_norm > 0.25
  - `bad_edge_frame[i]` = True if edge_margin_norm < 0.05
  - `bad_zoom_frame[i]` = True if abs(crop_h[i] - crop_h[i-1]) / crop_h[i-1] > 0.02
- `bad_frame[i]` = bad_center_frame OR bad_edge_frame OR bad_zoom_frame

**Summary metrics (stored in output dict under `"composition"` key):**
- `center_offset_p50` = median of center_offset_norm
- `center_offset_p95` = 95th percentile of center_offset_norm
- `center_offset_max` = max of center_offset_norm
- `edge_margin_min_px` = minimum edge_margin_px across all frames
- `edge_margin_p05` = 5th percentile of edge_margin_px (worst 5%)
- `edge_touch_count` = frames where any subject bbox edge is within 5px of crop edge
- `bad_frame_fraction` = fraction of frames with any bad flag
- `bad_center_fraction` = fraction with bad_center_frame
- `bad_edge_fraction` = fraction with bad_edge_frame
- `bad_zoom_fraction` = fraction with bad_zoom_frame
- `bad_run_max_length` = longest consecutive run of combined bad frames
- `bad_run_count` = number of bad-frame runs of length >= 3

### Implementation

Add these functions to `encode_analysis.py`:

1. `_compute_composition_metrics(crop_rects, trajectory)` -- computes all per-frame signals and returns summary dict with per-cause breakdowns
2. `_compute_bad_frame_runs(bad_flags)` -- finds consecutive runs of True in a boolean list, returns (max_length, run_count)

Call `_compute_composition_metrics()` from `analyze_crop_stability()` and add `"composition"` key to the output dict.

### Workstream breakdown

**WS1: Metric implementation**
- Owner: coder
- Work packages: 2
- Interfaces: needs trajectory and crop_rects format (already defined)
- Expected patches: 2

**WP1.1: Add composition metric functions**
- Owner: coder
- Touch points: `emwy_tools/track_runner/encode_analysis.py`
- Acceptance: `_compute_composition_metrics()` returns dict with all 12 summary keys including per-cause breakdowns; `_compute_bad_frame_runs()` returns correct run lengths
- Verification: `source source_me.sh && python -m pytest emwy_tools/tests/test_encode_analysis.py -v`
- Dependencies: none

**WP1.2: Add composition metric tests**
- Owner: tester
- Touch points: `emwy_tools/tests/test_encode_analysis.py`
- Acceptance: tests cover centered subject (low offset), edge-drifted subject (high offset, edge touch), bad-frame run detection, per-cause flag isolation (bad_center vs bad_edge vs bad_zoom), anisotropic normalization correctness
- Verification: `source source_me.sh && python -m pytest emwy_tools/tests/test_encode_analysis.py -v`
- Dependencies: WP1.1

### Patch plan

- Patch 1: encode_analysis composition metrics + integration into analyze_crop_stability
- Patch 2: tests for composition metrics

---

## Milestone M2: Diagnostic run on all 7 videos

Depends on: M1 (need composition metrics)
Entry criteria: M1 tests pass
Exit criteria: diagnostic numbers available for all 7 test videos showing current baseline composition quality

### Goal

Run composition metrics on all 7 test videos to quantify how bad the current centering is. This gives concrete numbers to improve against. The canon_60d clip establishes a fair reference for what acceptable metrics look like.

### Implementation

Update `tools/analyze_crop_path_stability.py` to include composition metrics in its cross-video comparison output. Run on all 7 videos (metrics-only, no encoding needed).

### Workstream breakdown

**WS2: Diagnostic run**
- Owner: coder
- Work packages: 1
- Expected patches: 1

**WP2.1: Add composition columns to cross-video analysis**
- Owner: coder
- Touch points: `tools/analyze_crop_path_stability.py`
- Acceptance: diagnostic script runs on all 7 videos, outputs comparison table with center_offset_p95, edge_margin_p05, edge_touch_count, bad_frame_fraction, bad_run_max_length, plus per-cause bad_center/bad_edge/bad_zoom fractions
- Verification: run on all 7 videos, verify new columns appear with plausible values; canon_60d establishes fair reference baseline
- Dependencies: WP1.1

### Patch plan

- Patch 3: analyze_crop_path_stability composition columns + diagnostic run on all 7 videos

---

## Milestone M3: Constraint-based crop geometry

Depends on: none for implementation; M2 baseline numbers required for exit comparison
Entry criteria: none (implementation can proceed in parallel with M1/M2)
Exit criteria: new crop geometry passes constraint tests; all existing tests still pass; M2 baseline numbers available for comparison

### Goal

Fix `direct_center_crop_trajectory()` to enforce subject-centered containment by constraint. Three changes, ordered by expected impact:

### Change 1: Tighter fill ratio (first-order fix)

Currently `crop_fill_ratio=0.1` makes the crop 10x the person height. **This is the primary cause of failure.** At 0.3, the crop is 3.3x person height -- tight enough that the subject is a meaningful part of the frame, loose enough to allow smooth motion without constant reframing.

**Approach:** Change the experiment variants to test fill_ratio values of 0.3 and 0.4 alongside the current 0.1. This is a config change, not a code change -- `direct_center_crop_trajectory()` already reads `crop_fill_ratio` from config.

### Change 2: Center containment clamp (second-order fix)

After smoothing the crop center, add a containment pass that ensures the subject stays within a protected central zone. If the smoothed center drifts too far from the subject, pull it back.

**Algorithm (add to `direct_center_crop_trajectory()` after Step 2, before Step 4):**

The containment uses anisotropic normalization matching the metrics. Here `raw_cx[i]` / `raw_cy[i]` are the unsmoothed subject-center trajectory positions (the detection bbox center), used as the containment target:

```
containment_radius_frac = 0.20  # config key: crop_containment_radius

for i in range(n):
    dx_norm = (raw_cx[i] - smoothed_cx[i]) / smoothed_w[i]
    dy_norm = (raw_cy[i] - smoothed_cy[i]) / smoothed_h[i]
    offset_norm = hypot(dx_norm, dy_norm)

    if offset_norm > containment_radius_frac:
        # pull crop center toward subject
        pull_factor = 1.0 - containment_radius_frac / offset_norm
        smoothed_cx[i] += (raw_cx[i] - smoothed_cx[i]) * pull_factor
        smoothed_cy[i] += (raw_cy[i] - smoothed_cy[i]) * pull_factor
```

**Black fill policy (implements priority hierarchy from Design Philosophy):** The crop may extend beyond the source frame boundary. When the runner is near a frame edge, the crop should stay centered on the runner and allow black fill (uncaptured areas) to appear at the opposite edge. This follows the priority hierarchy: runner composition (priority 1) outranks black-border avoidance (priority 4). The existing `apply_crop()` in `encoder.py` already fills out-of-bounds regions with black (zeros), so no encoder changes are needed. The change is in `direct_center_crop_trajectory()`: remove or relax the frame-boundary clamping (Step 5/7) so the crop center is driven by containment, not by frame bounds.

**Diagnostic metric:** Add `black_border_fraction` to `"crop_diagnostics"` -- fraction of frames where the crop rectangle extends beyond source frame bounds. This measures the cost of the soft-containment policy.

**Five-step order (important):**
1. Smooth center with forward-backward EMA
2. Apply containment clamp (subject stays in protected zone)
3. Light re-smoothing (hardcoded alpha=0.3) to blunt corrective snaps
4. Re-apply containment clamp once more (the re-smoothing can reintroduce violations)
5. Clamp crop size to frame dimensions (crop cannot be larger than frame), but do NOT clamp crop position to frame bounds (allow black fill at edges)

### Change 3: Zoom stability constraint

After computing `desired_crop_h`, add a maximum frame-to-frame height change constraint:

```
max_height_change_frac = 0.005  # max 0.5% height change per frame
for i in range(1, n):
    delta = smoothed_h[i] - smoothed_h[i-1]
    max_delta = max_height_change_frac * smoothed_h[i-1]
    if abs(delta) > max_delta:
        smoothed_h[i] = smoothed_h[i-1] + copysign(max_delta, delta)
```

0.5% per frame at 60fps = 30% height change per second max.

**Diagnostic metric:** Add `zoom_clamp_fraction` to the crop diagnostics output (separate from composition metrics) -- fraction of frames where the zoom constraint activated. This tells us whether the constraint is helping or constantly saturating. Stored under `"crop_diagnostics"` key in the analysis output, not under `"composition"`.

### Workstream breakdown

**WS3: Crop geometry changes**
- Owner: coder
- Work packages: 2
- Interfaces: provides improved crop rects to experiment harness
- Expected patches: 2

**WP3.1: Add containment clamp and zoom constraint to direct_center_crop_trajectory**
- Owner: coder
- Touch points: `emwy_tools/track_runner/tr_crop.py`
- Acceptance: containment clamp pulls crop center toward subject when offset exceeds radius; double-clamp (clamp-smooth-reclamp) order is correct; zoom constraint limits per-frame height change; existing tests still pass
- Verification: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: none (can start in parallel with M1/M2)

**WP3.2: Add constraint tests**
- Owner: tester
- Touch points: `emwy_tools/tests/test_tr_crop.py`
- Acceptance: tests verify containment clamp activates when subject drifts past radius, double-clamp prevents re-smoothing from reintroducing violations, zoom constraint limits height change rate, both respect frame bounds
- Verification: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: WP3.1

### New config keys

- `crop_containment_radius`: float, default 0.20. Fraction of crop dimensions (anisotropic). Subject center must stay within this normalized distance of crop center.
- `crop_max_height_change`: float, default 0.005. Maximum fractional height change per frame.

These go in the `processing` section of config.

### Patch plan

- Patch 4: tr_crop containment clamp (double-pass) + zoom constraint + zoom_clamp_fraction diagnostic metric
- Patch 5: constraint tests

---

## Milestone M4: Validation experiment on all 7 videos

Depends on: M1, M2, M3
Entry criteria: all tests pass, composition metrics available, constraints implemented
Exit criteria: experiment results show improvement on extreme-value metrics across all 7 videos; human visual review confirms improvement

### Goal

Run a new experiment comparing old baseline against new geometry on all 7 test videos. Measure with composition metrics.

### Experiment variants

| Variant | fill_ratio | containment | zoom_constraint | Description |
| --- | --- | --- | --- | --- |
| A_old_baseline | 0.1 | off | off | Current broken state |
| B_tight_030 | 0.3 | 0.20 | 0.005 | Tighter framing + constraints |
| C_tight_040 | 0.4 | 0.20 | 0.005 | Tightest framing + constraints |
| D_tight_030_no_contain | 0.3 | off | off | Tighter framing only (isolate fill ratio effect) |

### Success criteria

**Pass criteria** (practical: every video must improve materially over baseline, and at least 6 of 7 must meet all thresholds; one difficult clip may fail one threshold without blocking overall success):
- `center_offset_p95 < 0.20` (subject stays within 20% normalized distance from center, 95th percentile)
- `edge_touch_count < 10` per video (near-zero edge violations)
- `bad_frame_fraction < 0.05` (fewer than 5% bad frames)
- `bad_run_max_length < 10` (no very long bad-frame runs)
- `height_jerk_p95 < 5.0` (zoom reasonably smooth)
- Material improvement over A_old_baseline on all composition metrics for every video
- No catastrophic failures on any video (e.g., no video worse than baseline)
- `black_border_fraction < 0.10` (black fill acceptable but should not dominate)

**Stretch criteria** (target for a polished result):
- `center_offset_p95 < 0.15`
- `edge_touch_count = 0`
- `bad_frame_fraction < 0.02`
- `bad_run_max_length < 5`
- `height_jerk_p95 < 3.0`
- `black_border_fraction < 0.03`
- Human visual review: no visible panic recentering, no edge drift, smooth dolly cam feel

### Workstream breakdown

**WS4: Validation experiment**
- Owner: coder
- Work packages: 1
- Expected patches: 1

**WP4.1: Update experiment variants and run validation on all 7 videos**
- Owner: coder
- Touch points: `tools/batch_encode_experiment.py`, `docs/CHANGELOG.md`
- Acceptance: experiment runs all 4 variants on all 7 test videos, results table includes composition metrics with per-cause breakdowns, changelog updated
- Verification: results.md file exists with all metrics for all 7 videos
- Dependencies: WP1.1, WP2.1, WP3.1

### Patch plan

- Patch 6: experiment variant update + validation run on all 7 videos + changelog

---

## Acceptance criteria and gates

### Unit gate
- All existing tests pass: `source source_me.sh && python -m pytest emwy_tools/tests/ -v`
- Pyflakes clean: `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py`

### Integration gate
- Diagnostic and validation experiments produce results for all 7 test videos
- Composition metrics are non-zero and plausible
- zoom_clamp_fraction diagnostic shows whether zoom constraint is helping or saturating

### Quality gate
- Winning variant meets pass criteria on all 7 videos
- Human visual review confirms improvement over baseline

## Test strategy

- Synthetic tests for composition metrics (known subject position, known crop rect, verify metric values)
- Synthetic tests for anisotropic normalization (wide crop vs tall crop)
- Synthetic tests for per-cause bad frame isolation
- Synthetic tests for containment clamp (subject at edge -> crop pulled back)
- Synthetic tests for double-clamp (re-smoothing does not reintroduce violations)
- Synthetic tests for zoom constraint (large height jump -> clamped to max rate)
- Diagnostic run on all 7 real videos as baseline measurement
- Full experiment on all 7 real videos as validation

## Migration and compatibility

- Existing configs remain valid (API-compatible), but behavior changes because constraints are enabled by default (not behavior-compatible). Existing configs without the new keys will get containment clamping and zoom constraint automatically.
- Old fill_ratio=0.1 still works but is not the recommended setting.
- Prior experiment override functions (`center_lock_override`, `fixed_height_override`, `slow_size_override`, `apply_experiment_overrides`) remain in code but are no longer the primary stabilization approach. Cleanup deferred.

## Risk register

| Risk | Impact | Trigger | Mitigation |
| --- | --- | --- | --- |
| Containment clamp causes visible jerking | High | Subject moves fast, clamp snaps crop | Double-pass: clamp, re-smooth (alpha=0.3), re-clamp |
| Tighter fill ratio increases frame-boundary collisions | Medium | Subject near frame edge with smaller crop window, crop cannot fit without clipping | Increases containment clamp activity and visible edge-boundary interaction; fall back to 0.2 or adaptive fill ratio |
| Zoom constraint constantly saturating | Medium | zoom_clamp_fraction > 0.5 | Loosen to 0.01/frame or remove; diagnostic metric reveals this |
| New metrics don't correlate with visual quality | Medium | Bad frames metric disagrees with human review | Per-cause breakdowns help diagnose; adjust thresholds after review |
| Pass criteria too strict for all 7 videos | Low | One difficult video fails while rest pass | Separate pass and stretch criteria allow partial success |

## Resolved decisions

1. `crop_containment_radius`: default 0.20, revisit after M4 tail-metric review
2. Post-containment re-smoothing: hardcode alpha=0.3. Double-pass (clamp, smooth, re-clamp) to prevent re-smoothing from reintroducing violations
3. Prior experiment override cleanup: defer until after M4
4. Center offset normalization: anisotropic (dx/crop_w, dy/crop_h) to handle wide aspect ratios correctly
5. Bad frame flags: stored as per-cause (bad_center, bad_edge, bad_zoom) plus combined, for easier debugging
6. Success criteria: split into pass (achievable first time) and stretch (polished target)
7. `zoom_clamp_fraction` diagnostic metric added to detect zoom constraint saturation

## Reference data

- `canon_60d_600m_zoom.MP4` is a fair reference clip: pre-stabilized in ShotCut, near-target quality. Use to establish calibration values for composition metrics. Not ground truth, but a useful near-target reference.

## Future direction (beyond this plan)

This plan is a controlled stabilization cycle that stays within the current "smoothed bbox" paradigm. The user has identified that the correct long-term framing is:

**A virtual dolly cam is not a smoothed tracker box. It is a constrained camera reconstruction problem driven by noisy subject measurements and cleaner scene motion.**

The right architecture separates:
- **Stage A: Subject anchor** -- hips/shoulders/torso midpoint, short-window robust estimate. Use the runner only for identity and anchoring (who is the subject? where should the visual anchor be?).
- **Stage B: Scene motion** -- sparse background features, reject features on the runner, estimate frame-to-frame global motion (translation, then translation+scale, maybe weak affine).
- **Stage C: Virtual camera solver** -- choose a camera path smooth in scene coordinates, enforce composition constraints on the subject, limit zoom velocity and acceleration.
- **Stage D: Crop rendering** -- convert solved camera path to crop rects, apply bounds handling last.

This plan (tighter geometry + containment constraints) is expected to produce a noticeably better result, and possibly something that feels like "virtual dolly cam" on easier clips. But the final-quality illusion across all clips will likely require the Stage A-D architecture, where scene motion drives the camera and the runner drives only anchoring.

## Open questions

None -- all design decisions resolved.
