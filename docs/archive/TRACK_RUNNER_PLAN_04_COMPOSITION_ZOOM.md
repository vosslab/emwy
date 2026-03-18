# Direct-Center Composition and Zoom-Event Stabilization Plan

## Context

Recent experiments with Smart Mode v1a showed that broad regime switching can improve some crop-path metrics, especially on far-shot videos, but those gains do not consistently translate into better perceived output. On the key failure case (IMG_3702), the direct_center baseline was visually better than smart_v1a: the baseline felt steadier, while smart mode introduced a rocking-boat sensation and noticeable zoom inconsistency from 21 regime transitions in 92 seconds.

Those experiments still produced useful findings:

- The torso box is the primary camera target and is close to ground truth, but it is not temporally stable enough to follow frame-by-frame without smoothing.
- Broad regime switching is too coarse: regime transitions create instability they should prevent.
- The baseline direct_center crop is often compositionally close to good, but on tight crops it places the torso too low in the frame and cuts off the runner's feet.
- The dominant failure mode in current results is not general instability, but discrete magnification jumps caused by camera zoom changes. These events create large, sudden changes in bounding box scale that the current controller follows instead of counteracting.

New direction: restart from the stronger direct_center baseline and make two independent, targeted improvements:

1. **Composition**: place the torso higher in the frame so the crop preserves legs and feet.
2. **Zoom event stabilization**: detect discrete camera zoom jumps and refuse to follow them immediately.

## Objective

Improve perceived output quality toward a virtual-dolly-cam feel: the runner stays visually centered with good full-body composition, the camera moves smoothly, and discrete zoom jumps from the source camera are absorbed rather than reproduced. This plan adds composition offset and zoom-event damping to the existing direct_center crop mode -- it is not yet a true virtual dolly controller.

Validate each fix in isolation and in combination on the same test videos.

## Scope

**In scope:**

- Vertical composition offset in `direct_center_crop_trajectory()` (torso anchor at ~38% from top)
- Zoom event detector based on bbox height step changes
- Zoom hold behavior: when event detected, hold previous crop height and transition slowly
- Per-frame `max_height_change` array replacing scalar (pattern already exists in `smart_crop_trajectory()`)
- Experiment 7 with 4 interpretable variants on all 7 test videos
- Composition and zoom event tests
- Changelog update

## Design philosophy

**Start from the visual winner.** The direct_center baseline is already "quite good" (Experiment 6 review). The next changes inherit its stable feel, not replace it.

**Treat composition as a first-class control problem.** For running footage, the subject is not vertically symmetric. The crop should allocate less room above the torso and more room below for hips, thighs, knees, and feet. Human proportions justify placing the torso in the upper portion of the frame, but the crop should not assume an idealized body model.

**Target specific, observed failures directly.** Large zoom-shift events should be identified and counteracted locally, not averaged into broad regime policies. The zoom-event damping mechanism triggers only when needed and leaves normal behavior unchanged.

**Keep changes orthogonal.** Composition and zoom stabilization are independent improvements. They can be tested separately and combined without interaction effects. This keeps the experiment interpretable.

**Distinguish two kinds of scale change.** The crop-height signal contains two different phenomena. First, continuous zoom drift from real distance change between runner and camera -- this should be preserved and smoothed. Second, discrete magnification jumps from camera zoom changes -- these violate the continuous-motion assumption and should be detected and damped separately. The zoom-event path is not a replacement for ordinary size control. It is an override that activates only when the height signal shows a large, abrupt, event-like jump inconsistent with normal runner motion.

**Priority hierarchy** (carried forward from prior plans):

1. Keep the runner inside a protected composition zone
2. Keep camera motion smooth and low-order
3. Keep zoom motion smooth
4. Minimize black-border exposure
5. Only as a last resort, recenter aggressively

## Setup

`direct_center_crop_trajectory()` in [emwy_tools/track_runner/tr_crop.py](emwy_tools/track_runner/tr_crop.py) (line 360) is the target function. Its pipeline:

1. Extract `cx`, `cy`, `h` from trajectory (line 401)
2. Compute `desired_crop_h = raw_h / fill_ratio` (line 412)
3. Forward-backward EMA on position and size (lines 415-425)
4. Zoom constraint: scalar `crop_max_height_change` limits frame-to-frame height change (lines 427-434)
5. Min size guard (line 436)
6. Double containment clamp (lines 443-468)
7. Reconstruct rectangles, velocity cap, integer conversion (lines 471-508)

**Composition offset** is architecturally designed but disabled. Comments at lines 721-723 and 755-758 describe the formula: `desired_cy = torso_cy + (0.5 - anchor_fraction) * crop_h`. Currently `anchor = 0.5` (centered), `offset = 0`.

**Zoom constraint** uses a single scalar `max_height_change` (default 0.005 = 0.5%/frame). This treats camera zoom events the same as normal scale variation. The per-frame `max_height_change` array pattern already exists in `smart_crop_trajectory()` (lines 780-784) and can be reused.

**Experiment harness** at [tools/batch_encode_experiment.py](tools/batch_encode_experiment.py) uses a `VARIANTS` dict (line 101) with per-variant config overrides applied via `apply_overrides()` (line 138).

## Definitions

- **Virtual dolly cam**: crop behavior that keeps the runner visually stable while background motion carries most of the perceived movement. The viewer should feel like a smooth camera is tracking the runner, not like a crop window is chasing a detection box.
- **Zoom drift**: gradual, continuous scale change in the bbox height signal caused by the runner moving closer to or further from the camera. This is real physical motion and the crop should follow it smoothly. The existing scalar `max_height_change` constraint handles this adequately.
- **Zoom event**: a discrete magnification jump in the bbox height signal caused by camera zoom changes (e.g., iPhone lens switches). Distinguished from zoom drift by magnitude (>1.25x ratio) and abruptness (occurs within 1-3 frames and persists). These are the primary visual failure -- the crop follows them as if they were real motion.
- **Zoom-event damping**: a temporary reduction in the crop height change rate during and after a detected zoom event. The crop heavily damps (not freezes) size updates, allowing slow transition to the new scale. Normal zoom drift is unaffected -- only discrete events trigger the damping.
- **Torso anchor fraction**: the vertical position (0.0 = top, 1.0 = bottom) within the crop frame where the torso center should sit. Values < 0.5 place the torso in the upper portion of the crop, leaving more room below for legs and feet.
- **Baseline crop**: current controller output from `direct_center_crop_trajectory()` without new experiment overrides.

## Non-goals

- Broad regime switching or per-regime policy surfaces
- New config knobs for users (composition and zoom-event damping are internal improvements)
- Tracker replacement or solve/refine changes
- Changes to smooth crop mode or CropController
- Smart mode modifications (v1a stays as-is for comparison)
- Background motion estimation (deferred to Stage A-D architecture)
- Formal path optimization (L1 or learned)
- Foreground-background separation

## Current state

- **First-order problem solved:** `crop_fill_ratio` was tightened from 0.1 to 0.3 in Experiment 5 (virtual dolly cam plan). Subject is now a meaningful part of the frame.
- **Containment clamp working:** double-pass containment keeps subject within protected zone.
- **Zoom constraint working but coarse:** scalar `max_height_change` damps all scale changes uniformly. Cannot distinguish camera zoom events from natural approach/recession.
- **Composition not addressed:** torso is centered vertically (anchor = 0.5). Running footage needs torso higher in frame to preserve legs and feet.
- **Smart mode v1a tested and rejected for IMG_3702:** rocking-boat sensation from regime transitions and vertical offset coupled to per-frame bbox height.

## Literature grounding

This plan draws on established research while targeting a specific failure mode not well-covered by the literature.

**Video stabilization (Szeliski Ch. 9.2.1, Matsushita et al. 2006, NNDVS, Cigla CVPRW 2024, Xu et al. 2025 survey):** The canonical pipeline is motion estimation, motion smoothing, frame synthesis. The track runner currently skips motion estimation entirely -- it feeds the raw bbox signal (which mixes camera shake, subject locomotion, and detector noise) directly into the crop controller. The literature is emphatic that separating camera motion from subject motion is step 1. This plan defers that architectural change (it is the Stage B work from the prior dolly-cam plan) and instead targets two specific composition and zoom failures that can be fixed within the current pipeline.

**Tracking confidence gating (SeqTrackv2, MixFormer):** Both transformer trackers use score-based gates to prevent template contamination from low-confidence frames. The track runner's crop controller does not gate on confidence. The zoom-event damping mechanism partially addresses this for discrete events, but a general per-frame confidence gate on size updates remains a natural follow-up.

**Zoom events from multi-lens phones:** Discrete camera lens switches (e.g., iPhone switching between wide and telephoto lenses mid-recording) are not addressed by the stabilization or tracking literature. These produce instantaneous magnification jumps that violate the continuous-motion assumption underlying all standard smoothing techniques. The zoom-event damping mechanism in this plan is a targeted response to this specific, modern failure mode.

**What this plan does not attempt:** Background motion estimation (the biggest gap vs. the literature), formal path optimization (L1 or learned), or foreground-background separation. These are the correct long-term direction but require the Stage A-D architecture described in the prior dolly-cam plan.

## Architecture boundaries and ownership

Durable components: crop module, config module, experiment harness, crop tests, crop docs.

Ownership boundary:

- `coder`: crop-module internals and experiment harness.
- `tester`: invariant and regression tests.
- `planner`: docs, experiment rubric, changelog note.
- `architect`: approves promotion decision after stabilization evidence.
- `reviewer`: audits each patch before closure.

All changes stay within existing files. No new modules.

| Component | File | Change type |
| --- | --- | --- |
| Composition offset | `emwy_tools/track_runner/tr_crop.py` | Modify `direct_center_crop_trajectory()` |
| Zoom event detector | `emwy_tools/track_runner/tr_crop.py` | Add helper function |
| Zoom hold behavior | `emwy_tools/track_runner/tr_crop.py` | Modify step 2 and step 4 of pipeline |
| Composition tests | `emwy_tools/tests/test_tr_crop.py` | Add tests |
| Zoom event tests | `emwy_tools/tests/test_tr_crop.py` | Add tests |
| Experiment harness | `tools/batch_encode_experiment.py` | Update variants to Experiment 7 |
| Changelog | `docs/CHANGELOG.md` | Update |

### Mapping: milestones to components and patches

| Milestone | Component | Patches |
| --- | --- | --- |
| M1: Composition offset | tr_crop composition logic, tests | Patch 1, Patch 2 |
| M2: Zoom event stabilization | tr_crop zoom detector + hold, tests | Patch 3, Patch 4 |
| M3: Experiment 7 | batch_encode_experiment, changelog | Patch 5 |

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

### Reference tracker repos (OTHER_REPO_TEMP/)

Three MIT-licensed tracker implementations are available for reference:

| Repo | Key portable idea | Portability | Dependencies beyond emwy |
| --- | --- | --- | --- |
| SeqTrackv2 | Confidence-gated template update (decoder confidence score, interval + threshold gate) | High -- logic is ~10 lines, decoupled from model | torch, torchvision, timm, pytorch-pretrained-bert |
| OSTrack | Candidate elimination (early pruning of low-attention search tokens) | Low -- deeply coupled to ViT architecture | torch, torchvision, timm |
| MixFormerV2 | Score-decay adaptive template update | Medium -- update logic extractable, score requires model | torch, torchvision, timm, einops |

All three are PyTorch transformer models requiring GPU inference. We borrow **design patterns** (confidence gating, selective trust) but not code. The SeqTrackv2 confidence-gating pattern directly informs the principle that low-confidence frames should not aggressively update crop targets.

---

## Milestone M1: Vertical composition offset

Depends on: none
Entry criteria: existing `direct_center` tests pass
Exit criteria: composition offset produces measurably different vertical placement; all existing tests still pass

### Goal

Place the torso higher in the crop frame so running footage preserves legs and feet. The offset uses smoothed crop height (not per-frame raw height) to avoid coupling tracking noise into vertical camera motion.

### Design

Add a `torso_anchor_fraction` parameter to `direct_center_crop_trajectory()`. This is the vertical fraction (0.0 = top, 1.0 = bottom) where the torso center should sit in the crop.

**Formula** (activating the existing deferred design at tr_crop.py line 723):

```
offset = (0.5 - torso_anchor_fraction) * smoothed_crop_h
desired_cy = raw_cy + offset
```

With `torso_anchor_fraction = 0.38`:
- Offset = `(0.5 - 0.38) * crop_h = 0.12 * crop_h` (crop shifts down, torso appears higher)
- Torso sits at 38% from top of crop
- 62% of crop height is below the torso (for hips, legs, feet)

**Key decision:** The offset uses `smoothed_crop_h` from the EMA pass, not `raw_h`. This decouples composition from tracking noise. The prior v1a rocking-boat failure was caused by tying vertical offset to per-frame bbox height.

**Pipeline change in `direct_center_crop_trajectory()`:**

After EMA smoothing of crop height (after line 425), add:
```python
# composition: shift crop so torso sits at anchor fraction
torso_anchor = float(processing.get("crop_torso_anchor", 0.50))
if torso_anchor != 0.50:
    offset = (0.50 - torso_anchor) * smoothed_h
    smoothed_cy = smoothed_cy + offset
```

This inserts between the existing EMA pass (step 3) and the zoom constraint (step 4). The offset is applied to `smoothed_cy`, not `desired_cy`, so it does not fight the containment clamp.

**Config key:** `crop_torso_anchor` (float, default 0.50 = centered = current behavior). Not a user-facing knob -- used only in experiment overrides.

### Workstream breakdown

**WS1: Composition implementation**
- Owner: coder
- Work packages: 2
- Interfaces: modifies smoothed_cy after EMA, before containment clamp
- Expected patches: 2

**WP-1.1: Add torso anchor offset to direct_center_crop_trajectory**
- Owner: coder
- Touch points: `emwy_tools/track_runner/tr_crop.py`
- Acceptance criteria: `crop_torso_anchor=0.38` shifts crop so torso center is at 38% from top; `crop_torso_anchor=0.50` (default) produces identical output to current code; offset uses smoothed_h not raw_h
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: none

**WP-1.2: Add composition offset tests**
- Owner: tester
- Touch points: `emwy_tools/tests/test_tr_crop.py`
- Acceptance criteria: test that anchor=0.50 matches baseline output exactly; test that anchor=0.38 places torso center in upper 40% of crop; test that offset scales with crop height not bbox height; test that containment clamp still functions with offset active
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: WP-1.1

### Patch plan

- Patch 1: tr_crop add torso anchor offset after EMA smoothing
- Patch 2: test_tr_crop add composition offset tests

---

## Milestone M2: Zoom event stabilization

Depends on: none (can proceed in parallel with M1)
Entry criteria: existing `direct_center` tests pass
Exit criteria: zoom events are detected and damped; no regression on smooth footage; all existing tests pass

### Goal

Separate normal scale drift from discrete zoom events in the bbox height signal. Preserve gradual approach/recession, but detect abrupt camera-induced magnification jumps and refuse to follow them immediately. Replace the scalar `max_height_change` with a per-frame array that uses heavy damping during zoom events and normal behavior otherwise.

### Design

**Step 1: Detect zoom events.**

Add a helper function `_detect_zoom_events()` that scans `raw_h` for large step changes:

```python
def _detect_zoom_events(raw_h, threshold_ratio=1.25, hold_frames=30):
    """Detect frames where bbox height jumps by more than threshold_ratio.

    Args:
        raw_h: numpy array of per-frame bbox heights.
        threshold_ratio: minimum h(t)/h(t-1) ratio to flag as zoom event.
        hold_frames: number of frames to hold after each event.

    Returns:
        Boolean numpy array, True for frames in zoom-hold zones.
    """
```

Detection rule (two-part):

1. **Step detection**: if `h(t) / h(t-1) > threshold_ratio` or `h(t) / h(t-1) < 1.0 / threshold_ratio`, flag frame `t` as a candidate zoom event.
2. **Persistence check**: confirm the candidate by verifying that the post-step height level persists over the next 2-3 frames (i.e., `h(t+1)` and `h(t+2)` remain within 10% of `h(t)`). This prevents single-frame bbox outliers from triggering a hold zone. If the jump does not persist, it was likely a detection glitch, not a camera zoom event.

If confirmed, mark frame `t` and the next `hold_frames` frames as zoom-event damping zone.

The threshold of 1.25 catches iPhone lens switches (which typically produce 1.5x-3x jumps) while ignoring normal approach/recession (typically < 1.05x per frame at 60fps). The persistence check adds robustness against single-frame detector noise. The hold duration of 30 frames (~0.5s at 60fps) gives the slow transition time to blend.

**Step 2: Build per-frame max_height_change array.**

Replace the scalar zoom constraint loop (tr_crop.py lines 427-434) with a per-frame array:

```python
zoom_hold_mask = _detect_zoom_events(raw_h, threshold_ratio=1.25, hold_frames=30)

# per-frame max height change
max_height_change_arr = numpy.full(n, base_max_height_change)
# during zoom events, heavily damp size updates
zoom_hold_factor = 0.1  # 10% of normal rate
max_height_change_arr[zoom_hold_mask] = base_max_height_change * zoom_hold_factor
```

The existing constraint loop (lines 427-434) already iterates per-frame. The only change is indexing into the array instead of using a scalar:

```python
for i in range(1, n):
    delta = smoothed_h[i] - smoothed_h[i - 1]
    max_delta = max_height_change_arr[i] * smoothed_h[i - 1]
    if abs(delta) > max_delta:
        smoothed_h[i] = smoothed_h[i - 1] + math.copysign(max_delta, delta)
```

This pattern is already proven in `smart_crop_trajectory()` (lines 780-784).

**Step 3: Add diagnostic metric.**

Add `zoom_event_count` and `zoom_hold_fraction` to the crop output for experiment reporting. These go alongside existing diagnostics, not in a new structure.

**Config keys:** None. The zoom-event damping parameters (`threshold_ratio=1.25`, `hold_frames=30`, `zoom_hold_factor=0.1`) are hardcoded internal constants for Experiment 7. They become config keys only if experiment results justify tuning.

### Workstream breakdown

**WS2: Zoom event stabilization**
- Owner: coder
- Work packages: 2
- Interfaces: modifies step 4 (zoom constraint) of direct_center pipeline
- Expected patches: 2

**WP-2.1: Add zoom event detector and per-frame height change array**
- Owner: coder
- Touch points: `emwy_tools/track_runner/tr_crop.py`
- Acceptance criteria: `_detect_zoom_events()` returns boolean mask; zoom-event damping zones span `hold_frames` after each event; per-frame `max_height_change_arr` replaces scalar in constraint loop; when no zoom events detected, behavior is identical to current code; zoom-event damping factor reduces size update rate to 10% of normal
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: none

**WP-2.2: Add zoom event stabilization tests**
- Owner: tester
- Touch points: `emwy_tools/tests/test_tr_crop.py`
- Acceptance criteria: test that smooth height signal produces no zoom events; test that 2x height jump at frame N triggers hold zone from N to N+hold_frames; test that crop height during hold zone changes at most 10% of normal rate; test that after hold zone, normal rate resumes; test bidirectional: zoom-in and zoom-out both detected; test that multiple events produce merged hold zones when overlapping
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: WP-2.1

### Patch plan

- Patch 3: tr_crop add zoom event detector and per-frame height change array
- Patch 4: test_tr_crop add zoom event stabilization tests

---

## Milestone M3: Experiment 7

Depends on: M1-exit (need composition offset), M2-exit (need zoom-event damping)
Entry criteria: all M1 and M2 tests pass
Exit criteria: experiment results produced for key test videos; visual review completed

### Goal

Run a controlled 2x2 experiment with 4 variants that isolate composition and zoom-event damping independently, then test their combination.

### Experiment variants

| Variant | Composition | Zoom-event damping | Description |
| --- | --- | --- | --- |
| `A_baseline_dc` | anchor=0.50 (centered) | off | Current direct_center behavior |
| `B_torso_38` | anchor=0.38 | off | Composition offset only |
| `C_zoom_hold` | anchor=0.50 (centered) | on | Zoom-event damping only |
| `D_zoom_hold_torso_38` | anchor=0.38 | on | Both improvements combined |

**Why 4 variants:** True isolation. A vs B shows composition effect alone. A vs C shows zoom damping effect alone. C vs D shows whether composition adds value on top of zoom damping. Without B, gains in D over C would be ambiguous.

**Config overrides per variant:**

```python
VARIANTS = {
    "A_baseline_dc": {
        "description": "Current direct_center: centered torso, scalar zoom constraint",
        "overrides": {
            "crop_mode": "direct_center",
            "crop_torso_anchor": 0.50,
            "crop_zoom_event_damping": False,
        },
    },
    "B_torso_38": {
        "description": "Composition offset only: torso at 38% from top",
        "overrides": {
            "crop_mode": "direct_center",
            "crop_torso_anchor": 0.38,
            "crop_zoom_event_damping": False,
        },
    },
    "C_zoom_hold": {
        "description": "Zoom-event damping only, centered torso",
        "overrides": {
            "crop_mode": "direct_center",
            "crop_torso_anchor": 0.50,
            "crop_zoom_event_damping": True,
        },
    },
    "D_zoom_hold_torso_38": {
        "description": "Zoom-event damping + torso at 38% from top",
        "overrides": {
            "crop_mode": "direct_center",
            "crop_torso_anchor": 0.38,
            "crop_zoom_event_damping": True,
        },
    },
}
```

### Experiment test videos

Run all 4 variants on all 7 test videos. Processing time is available and the user is not waiting for results.

| Video | Role in experiment |
| --- | --- |
| IMG_3702 | Key failure case; zoom events are the primary problem |
| IMG_3830 | Control video; must not regress |
| IMG_3823 | Strong zoom variation; tests zoom-event damping on natural scale changes |
| canon_60d_600m_zoom | Fair reference; near-target quality |
| IMG_3707 | Relay extreme; tests edge cases |
| IMG_3629 | Dense refined; sparse seeds |
| IMG_3627 | Very sparse; tests degraded conditions |

### Success criteria

**Pass criteria:**
- `C_zoom_hold` reduces `height_jerk_p95` on IMG_3702 compared to `A_baseline_dc`
- `C_zoom_hold` does not increase `height_jerk_p95` on IMG_3830 (no regression on smooth footage)
- `B_torso_38` places torso center measurably higher in frame than `A_baseline_dc`
- `D_zoom_hold_torso_38` combines both improvements without regression on any video
- Human visual review: zoom-event damping variants feel steadier than baseline on IMG_3702
- No variant is visually worse than baseline on any of the 7 test videos

**Stretch criteria:**
- `height_jerk_p95 < 5.0` on IMG_3702 for zoom-event damping variants
- `bad_zoom_fraction < 0.02` for zoom-event damping variants
- Human visual review rates combined variant as approaching virtual dolly cam feel

### Workstream breakdown

**WS3: Experiment execution**
- Owner: coder
- Work packages: 1
- Interfaces: needs working composition offset and zoom-event damping from WS1/WS2
- Expected patches: 1

**WP-3.1: Update experiment harness to Experiment 7 and run on test videos**
- Owner: coder
- Touch points: `tools/batch_encode_experiment.py`, `docs/CHANGELOG.md`
- Acceptance criteria: experiment runs 4 variants on all 7 test videos; results table includes composition metrics and zoom event diagnostics; changelog updated with experiment description and findings
- Verification commands: `source source_me.sh && python tools/batch_encode_experiment.py`
- Dependencies: WP-1.1, WP-2.1

### Patch plan

- Patch 5: batch_encode_experiment Experiment 7 variants + changelog

---

## Acceptance criteria and gates

**Unit gate:**
- All existing tests pass: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- All existing tests pass: `source source_me.sh && python -m pytest emwy_tools/tests/ -v`

**Lint gate:**
- Pyflakes clean: `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py`

**Regression gate:**
- `crop_torso_anchor=0.50` (default) produces identical output to pre-change code
- No zoom events detected on smooth synthetic trajectory produces identical output to pre-change code
- `crop_zoom_event_damping=False` (default) produces identical output to pre-change code

**Integration gate:**
- Experiment harness runs all 4 variants on all 7 test videos without error
- Results table includes both motion stability and composition metrics

**Quality gate:**
- Zoom hold variant meets pass criteria on IMG_3702
- No regression on IMG_3830
- Human visual review confirms improvement

## Test strategy

| Level | What | File |
| --- | --- | --- |
| Unit | Composition offset: anchor positions, offset scaling, default passthrough | test_tr_crop.py |
| Unit | Zoom detector: smooth signal (no events), step jump (event detected), bidirectional, hold zones, overlap merging | test_tr_crop.py |
| Unit | Zoom hold integration: damped height change during hold, normal rate outside hold | test_tr_crop.py |
| Regression | Default config produces byte-identical output to pre-change code | test_tr_crop.py |
| Lint | No new pyflakes warnings | test_pyflakes_code_lint.py |
| Experiment | 4-variant comparison on all 7 videos | batch_encode_experiment.py |

**Failure semantics:** Any unit or regression failure blocks M3. Experiment failures trigger parameter tuning (threshold, hold duration, anchor fraction), not code rollback.

## Migration and compatibility

- **Additive only.** New behavior requires explicit config keys (`crop_torso_anchor != 0.50` or `crop_zoom_event_damping = True`). Default config produces identical output.
- **No new modules.** All changes within existing `tr_crop.py`.
- **No CLI changes.** No new flags or subcommands.
- **Backward compatible.** Existing configs without new keys behave identically.
- **Deletion criteria:** If Experiment 7 shows no improvement, revert the zoom-event damping code path. Composition offset can remain dormant at default=0.50.
- **Rollback:** Remove the zoom-event damping conditional and anchor offset conditional. Both are guarded by config checks.

## Risk register

| Risk | Impact | Trigger | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| Zoom detector triggers on normal approach/recession | False positives damp legitimate scale changes | threshold too low or hold too long | Start conservative (1.25x, 30 frames); tune after reviewing diagnostics | coder |
| Zoom detector misses subtle lens switches | No improvement on real footage | threshold too high | Review raw_h signal on IMG_3702 to calibrate; can lower threshold | coder |
| Composition offset interacts with containment clamp | Torso pulled back to center, offset nullified | containment radius too tight for offset | Offset applied to smoothed_cy before containment; clamp allows the shifted center | coder |
| Zoom hold creates visible pause in output | Crop freezes noticeably during hold | hold_frames too long or factor too low | Reduce hold_frames or increase factor; 30 frames at 60fps = 0.5s is conservative | coder |
| IMG_3823 (strong zoom) loses legitimate zoom tracking | Zoom hold triggers on real distance changes | natural scale variation exceeds threshold | Review IMG_3823 zoom event count; may need higher threshold for that video | coder |

## Rollout and release checklist

1. All M1 tests pass (composition offset)
2. All M2 tests pass (zoom event stabilization)
3. Regression: default config produces identical output
4. Pyflakes lint clean
5. Experiment 7 runs on all 7 test videos with documented results
6. Human visual review completed
7. Changelog entry written with experiment findings

## Documentation close-out

- `docs/CHANGELOG.md`: entry documenting composition offset, zoom event stabilization, and Experiment 7 findings
- Plan file: archive after Experiment 7 visual review
- If zoom-event damping is promoted to default behavior, update `docs/TRACK_RUNNER_YAML_CONFIG.md`

## Open questions

1. **Zoom event threshold calibration.** The 1.25x ratio is a starting point. Need to inspect `raw_h` on IMG_3702 to see actual jump magnitudes. If iPhone lens switches produce 2x+ jumps, 1.25x is safely conservative. If natural running approach produces 1.15x, there is margin. **Decision needed after:** inspecting raw_h signal on test videos.

2. **Torso anchor value.** User suggested 35% and 40% from top. Plan uses 38% as the single test value based on Experiment 5 feedback ("crop above torso should be tighter than below"). If 38% cuts off heads, try 40%. **Decision needed after:** visual review of Experiment 7 variant C.

3. **Hold-to-transition behavior.** Current design holds at previous height then resumes normal rate. An alternative is to hold briefly then ramp to the new height over a longer window. The simple hold-then-resume is the first implementation; ramping can be added if visual review shows the transition is too abrupt. **Decision needed after:** visual review.
