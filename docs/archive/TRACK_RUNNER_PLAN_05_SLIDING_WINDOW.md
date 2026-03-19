# Virtual Dolly Cam: Piecewise Zoom Stabilization

## Context

Recent experiments established the `direct_center` crop baseline as visually strong -- the runner is well-framed, the camera feels smooth, and containment keeps the subject in a protected zone. Smart Mode v1a (Experiment 6) tried broad regime switching but was rejected on the key failure case (IMG_3702): the baseline felt steadier, while smart mode introduced a rocking-boat sensation from 21 regime transitions in 92 seconds.

Those experiments produced useful findings:

- The torso box is the primary camera target and is close to ground truth, but not temporally stable enough to follow frame-by-frame without smoothing.
- Broad regime switching is too coarse: regime transitions create instability they should prevent.
- The baseline direct_center crop is compositionally close to good, but places the torso too low in the frame and cuts off the runner's feet on tight crops.
- The dominant failure mode is not general instability, but camera zoom-state transitions that the crop controller follows instead of absorbing.

A first attempt at zoom-event detection (Experiment 7) used single-frame height ratios with a 1.25x threshold. This failed: iPhone lens transitions spread over 2-5 frames at 60fps, so per-frame ratios are ~1.26 (barely caught) to ~1.15 (missed entirely). Additionally, the single median output resolution produced full-frame output (2816x1584) on multimodal footage, making the runner tiny and the experiment uninterpretable.

New direction: restart from the `direct_center` baseline. Replace the single-frame jump detector with a sliding-window approach. Model zoom as piecewise-smooth behavior with three controller modes, not a single global rate limit.

## Objective

Produce a virtual dolly cam effect for track runner footage: the viewer perceives a smooth camera tracking the runner at a steady distance, even though the source was shot from a fixed position with a handheld phone cycling through zoom modes. The runner stays well-framed with full-body composition, scale changes are gradual and intentional, and camera zoom transitions are absorbed rather than reproduced.

## Design philosophy

**The output should feel like a dolly cam, not a crop window.** A real dolly camera on rails maintains a constant distance to the runner. The background scrolls smoothly. The runner stays centered and consistently sized. The crop controller should replicate this feel by treating the torso box as a camera target and rejecting rapid magnification changes that are inconsistent with physical camera motion.

**Start from the visual winner.** The `direct_center` baseline is already visually strong (Experiment 6 review). Changes build on its stable feel, not replace it.

**The height signal is a composite, not a single source.** The bbox height signal contains two distinct effects that require different handling:
1. **Gradual scale drift** from the runner physically moving toward or away from a fixed camera. This is smooth, continuous, real motion. A dolly cam would show this same drift. Preserve it.
2. **Camera zoom transitions** from the iPhone switching among 1X, 2X, and 5X capture modes. These are short (2-5 frame) magnification changes that a dolly cam would never produce. Absorb them.

**Image-plane motion is a mixture of four sources:**
- Runner motion (the tracking target -- follow it)
- Camera pan/rotation (fixed camera position, variable aim -- smooth it)
- Camera zoom state changes (magnification jumps -- absorb them)
- Detection noise (tracker jitter -- filter it)

The current controller treats all of these as one smooth global signal with a single response rule. The key insight: camera zoom transitions and gradual distance drift should not be handled by the same response rule.

**Zoom transitions are structured, not random.** The iPhone 16 Pro Max cycles through 1X -> 2X -> 5X -> 2X -> 1X, stepping through adjacent modes. Transitions include a short Apple-provided animation (2-5 frames at 60fps). The controller should expect piecewise smooth behavior with short transition events, not instantaneous jumps or continuous drift.

**Three behaviors, not one.** The zoom controller should operate in three modes:
1. **Normal drift** -- follow scale smoothly (existing behavior, no change)
2. **Zoom transition** -- near-freeze crop height during the active magnification change
3. **Post-transition settling** -- begins after the transition window ends; slowly converge to new scale with biased monotonicity (suppress small reversals, allow sustained real motion)

**Composition is a first-class concern.** For running footage, the runner is not vertically symmetric. The crop should place the torso in the upper portion of the frame, leaving more room below for hips, legs, and feet. This offset uses smoothed crop height, not raw bbox height, to prevent coupling tracking noise into vertical camera motion.

**Priority hierarchy** (carried forward):
1. Keep the runner inside a protected composition zone
2. Keep camera motion smooth and low-order
3. Keep zoom motion smooth
4. Minimize black-border exposure
5. Only as a last resort, recenter aggressively

## Scope

**In scope:**
- Sliding-window zoom transition detector
- Three-mode per-frame zoom constraint with local monotonicity
- Vertical composition offset (torso anchor)
- 3-variant experiment on all 7 test videos
- Unit tests for zoom detection, constraint modes, and composition
- Changelog update

**Non-goals:**
- Smart mode / regime classifier changes (v1a stays as-is)
- New user-facing config knobs (internal experiment overrides only)
- Tracker or solver modifications
- Background motion estimation (deferred to future dolly-cam architecture)
- Explicit output resolution selection logic (this plan fixes control behavior, not output sizing; if stabilized signal still produces poor median, output resolution is a separate follow-up)
- Formal path optimization or foreground-background separation

## Definitions

- **Virtual dolly cam**: crop behavior that keeps the runner visually stable while background motion carries most of the perceived movement. The viewer should feel like a smooth camera is tracking the runner, not like a crop window is chasing a detection box.
- **Zoom drift**: gradual, continuous scale change in the bbox height signal caused by the runner moving closer to or further from the camera. This is real physical motion. A dolly cam would show this same drift. The crop should follow it smoothly.
- **Zoom transition**: a short (2-5 frame) magnification change in the bbox height signal caused by the iPhone switching capture modes (1X, 2X, 5X). Detected when the ratio of max to min height within a 5-frame window exceeds 1.40. Distinguished from zoom drift by magnitude and structure (piecewise, stepping through adjacent modes). A dolly cam would never produce this.
- **Post-transition flicker**: oscillation in crop height after a zoom transition, caused by the controller trying to converge to a new scale and then reversing when the next transition occurs. The dominant visual failure in current output.
- **Biased monotonicity**: within a settling window after a zoom transition, the crop height is biased toward continuing in one direction (grow or shrink). Small reversals are suppressed, but a reversal is allowed if it exceeds a minimum threshold (e.g., 0.3% of current height) sustained over multiple consecutive frames. This suppresses flicker while avoiding "frozen" behavior when real distance change occurs during settling.
- **Torso anchor fraction**: the vertical position (0.0 = top, 1.0 = bottom) within the crop frame where the torso center should sit. Values < 0.5 place the torso in the upper portion, leaving more room below for legs and feet.
- **Baseline crop**: current controller output from `direct_center_crop_trajectory()` without new experiment overrides.

## Current state

- **First-order problem solved:** `crop_fill_ratio=0.30` tightened in Experiment 5. Runner is a meaningful part of the frame.
- **Containment clamp working:** double-pass containment keeps subject within protected zone.
- **Zoom constraint working but coarse:** scalar `max_height_change=0.005` damps all scale changes uniformly. Cannot distinguish camera zoom transitions from natural approach/recession.
- **Composition not addressed:** torso centered vertically (anchor=0.50). Running footage needs torso higher to preserve legs and feet.
- **Smart mode v1a tested and rejected for IMG_3702:** rocking-boat sensation from regime transitions.
- **Previous plan (Experiment 7) attempted and failed:** single-frame zoom detection missed iPhone transitions that spread over 2-5 frames. Single median output resolution was wrong for multimodal height distributions.

### Evidence from zoom analysis

Height signal analysis across 7 test videos confirms the composite signal structure:

| Video | Height CV | Height range (px) | 1-frame >1.15x | 3-frame >1.15x | Distribution modes |
| --- | --- | --- | --- | --- | --- |
| IMG_3702 | 0.40 | 54-440 | 159 | 493 | 4 (86, 125, 189, 267) |
| IMG_3830 | 0.85 | 21-192 | 243 | 740 | 2 (30, 69) |
| IMG_3629 | 1.35 | 30-781 | 223 | 712 | 4 (67, 218, 493, 718) |
| IMG_3707 | 0.45 | 49-635 | 548 | 1660 | 2 (117, 254) |
| IMG_3823 | 0.51 | 11-119 | 91 | 384 | 2 (27, 42) |
| IMG_3627 | 0.51 | 27-246 | 47 | 198 | 3 (67, 82, 96) |
| canon_60d | 0.21 | 59-325 | 161 | 528 | 1 (99) |

Key findings:
- 3-frame windows catch 3-4x more events than single-frame ratios. Transitions spread across multiple frames.
- Height distributions are multimodal on multi-zoom footage. A single median is a poor summary.
- Every video has zoom events -- this is normal footage behavior, not an edge case.
- Per-frame ratio p95 is ~1.07 across all videos. Ratios exceeding 1.40 over 5 frames are clearly zoom transitions, not normal drift.

## Literature grounding

**Video stabilization (Szeliski Ch. 9.2.1, Matsushita et al. 2006, NNDVS, Cigla CVPRW 2024, Xu et al. 2025 survey):** The canonical pipeline is motion estimation, motion smoothing, frame synthesis. The track runner currently skips motion estimation -- it feeds the raw bbox signal (which mixes camera shake, subject locomotion, and detector noise) directly into the crop controller. This plan defers the architectural change (Stage B from the prior dolly-cam plan) and targets two specific failures fixable within the current pipeline.

**Tracking confidence gating (SeqTrackv2, MixFormer):** Both transformer trackers use score-based gates to prevent template contamination from low-confidence frames. The zoom-transition damping mechanism partially addresses this for discrete events. A general per-frame confidence gate on size updates remains a natural follow-up.

**Zoom events from multi-lens phones:** Discrete camera lens switches are not addressed by the stabilization or tracking literature. These produce short-transition magnification changes that violate the continuous-motion assumption underlying standard smoothing. This plan is a targeted response to this modern failure mode.

## Test videos (all 7 with solved intervals)

| Video | Intervals file | Notes |
| --- | --- | --- |
| canon_60d_600m_zoom.MP4 | tr_config/canon_60d_600m_zoom.MP4.track_runner.intervals.json | Fair reference: pre-stabilized in ShotCut |
| Hononega-Orion_600m-IMG_3702.mkv | tr_config/Hononega-Orion_600m-IMG_3702.mkv.track_runner.intervals.json | Key failure case, high convergence error |
| Hononega-Varsity_4x400m-IMG_3707.mkv | tr_config/Hononega-Varsity_4x400m-IMG_3707.mkv.track_runner.intervals.json | Relay extreme |
| IMG_3627.MOV | tr_config/IMG_3627.MOV.track_runner.intervals.json | Very sparse seeds |
| IMG_3629.mkv | tr_config/IMG_3629.mkv.track_runner.intervals.json | Dense refined |
| IMG_3823.MP4 | tr_config/IMG_3823.MP4.track_runner.intervals.json | Strong zoom variation |
| IMG_3830.MP4 | tr_config/IMG_3830.MP4.track_runner.intervals.json | Control video |

## Architecture boundaries and ownership

Durable components: crop module, config module, experiment harness, crop tests, crop docs.

Ownership boundary:
- `coder`: crop-module internals and experiment harness
- `tester`: invariant and regression tests
- `planner`: docs, experiment rubric, changelog note
- `architect`: approves promotion decision after stabilization evidence
- `reviewer`: audits each patch before closure

All changes stay within existing files. No new modules.

| Component | File | Owner |
| --- | --- | --- |
| Zoom phase detector | `emwy_tools/track_runner/tr_crop.py` | coder |
| Three-mode zoom constraint | `emwy_tools/track_runner/tr_crop.py` | coder |
| Composition offset | `emwy_tools/track_runner/tr_crop.py` | coder |
| Zoom and composition tests | `emwy_tools/tests/test_tr_crop.py` | tester |
| Experiment harness | `tools/batch_encode_experiment.py` | coder |
| Changelog | `docs/CHANGELOG.md` | planner |

### Mapping: milestones to components and patches

| Milestone | Component | Patches |
| --- | --- | --- |
| M1: Zoom stabilization | tr_crop zoom detector + three-mode constraint | Patch 1, Patch 2 |
| M2: Composition offset | tr_crop composition logic | Patch 3 |
| M3: Experiment 7b | batch_encode_experiment, changelog | Patch 4 |

## Milestone plan

### M1: Piecewise zoom stabilization

- **Depends on:** none
- **Entry criteria:** existing `direct_center` tests pass
- **Exit criteria:** zoom transitions detected on synthetic signals; three-mode constraint produces different rate limits per mode; local monotonicity suppresses reversals in settling zones; default config produces identical output to pre-change code

**Goal:** Replace the scalar `max_height_change` constraint with a three-mode per-frame constraint that separates normal drift, zoom transitions, and post-transition settling.

#### Workstream breakdown

**WS1: Zoom stabilization implementation**
- Goal: Detect zoom transitions and enforce mode-specific height constraints
- Owner: coder
- Work packages: 2
- Interfaces: modifies step 2.5 (zoom constraint) of `direct_center_crop_trajectory()` pipeline
- Expected patches: 2

**WP-1.1: Add sliding-window zoom phase detector**
- Owner: coder
- Touch points: `emwy_tools/track_runner/tr_crop.py`
- Acceptance criteria:
  - `_detect_zoom_phases(raw_h)` returns `(transition_mask, settle_mask)` boolean arrays
  - Uses 5-frame sliding window; flags frame when max/min height ratio within the window exceeds 1.40
  - Transition mask marks frames during active zoom change
  - Settle mask marks `settle_frames=60` frames after each transition (starts after the transition window ends, not overlapping)
  - Overlapping settling zones merge
  - Guards against zero/NaN heights
  - Smooth signal produces empty masks
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v -k zoom`
- Dependencies: none

**WP-1.2: Add three-mode constraint with local monotonicity**
- Owner: coder
- Touch points: `emwy_tools/track_runner/tr_crop.py`
- Acceptance criteria:
  - New config key `crop_zoom_stabilization` (bool, default False)
  - When False: behavior identical to current scalar constraint
  - When True: builds per-frame `max_height_change_arr` with three rates:
    - Normal frames: 1.0x base rate
    - Transition frames: 0.02x base rate (near-freeze)
    - Settling frames: 0.20x base rate (slow convergence)
  - Biased monotonicity in settling zones: small reversals suppressed, reversal allowed only if it exceeds a minimum threshold (0.3% of current height) sustained over multiple consecutive frames
  - Monotonicity bias resets when exiting settling zone
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: WP-1.1

**WS2: Zoom stabilization tests**
- Goal: Validate zoom detection and three-mode behavior
- Owner: tester
- Work packages: 1
- Interfaces: needs WP-1.1 and WP-1.2 functions
- Expected patches: 1 (combined test patch)

**WP-2.1: Add zoom phase detection and constraint tests**
- Owner: tester
- Touch points: `emwy_tools/tests/test_tr_crop.py`
- Acceptance criteria:
  - Smooth height signal: no transitions, no settling
  - 2x step at frame 50: transition detected
  - 2x change spread over 5 frames: transition detected across ramp
  - Settling zone spans correct frame range after last transition
  - Multiple transitions: zones merge when overlapping
  - Bidirectional: zoom-in and zoom-out both detected
  - `crop_zoom_stabilization=False` matches baseline exactly
  - Transition mode: crop height changes at most 2% of normal rate
  - Settling mode: crop height changes at most 20% of normal rate
  - Biased monotonicity: small reversals suppressed in settling zone
  - Sustained reversal exceeding threshold is allowed in settling zone
  - After settling expires: normal rate and free reversals resume
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`
- Dependencies: WP-1.1, WP-1.2

### M2: Vertical composition offset

- **Depends on:** none (parallel with M1)
- **Entry criteria:** existing `direct_center` tests pass
- **Exit criteria:** torso anchor offset produces measurably different vertical placement; default config produces identical output to pre-change code

**Goal:** Place the torso higher in the crop frame so running footage preserves legs and feet. Offset uses smoothed crop height to decouple from tracking noise.

#### Workstream breakdown

**WS3: Composition implementation and tests**
- Goal: Add torso anchor parameter with tests
- Owner: coder
- Work packages: 1
- Interfaces: modifies smoothed_cy after EMA, before zoom constraint
- Expected patches: 1

**WP-3.1: Add torso anchor offset and composition tests**
- Owner: coder
- Touch points: `emwy_tools/track_runner/tr_crop.py`, `emwy_tools/tests/test_tr_crop.py`
- Acceptance criteria:
  - New config key `crop_torso_anchor` (float, default 0.50 = centered)
  - `anchor=0.50` produces identical output to pre-change code
  - `anchor=0.38` places torso center in upper 40% of crop
  - Offset = `(0.50 - anchor) * smoothed_h`, uses smoothed height not raw
  - Offset scales with crop height (larger crop = larger offset)
  - Containment clamp still functions with offset active
  - Offset inserts after EMA smoothing, before zoom constraint
- Verification commands: `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v -k torso`
- Dependencies: none

### M3: Experiment 7b

- **Depends on:** M1-exit (zoom stabilization working), M2-exit (composition offset working)
- **Entry criteria:** all M1 and M2 tests pass; pyflakes lint clean on changed files
- **Exit criteria:** 3 variants encoded on all 7 test videos; results table produced; changelog updated

**Goal:** Validate zoom stabilization and composition on real footage with a controlled 3-variant comparison.

#### Experiment variants

Because the source footage and failure modes are well understood, experiments should be hypothesis-driven rather than exploratory. Each variant must isolate one known mechanism: composition, zoom-transition handling, or their combination.

| Variant | Zoom stabilization | Composition | Question it answers |
| --- | --- | --- | --- |
| `A_baseline_dc` | off | anchor=0.50 | Current behavior (control) |
| `B_torso_38` | off | anchor=0.38 | Is the missing-feet problem primarily composition? |
| `C_zoom_stabilized` | on | anchor=0.50 | Is the zoom-flicker problem primarily transition handling? |
| `D_zoom_stabilized_torso_38` | on | anchor=0.38 | Do those fixes combine cleanly? |

This is a structured 2x2 factorial, not a sweep. A vs B isolates composition. A vs C isolates zoom stabilization. C vs D shows whether composition adds value on top of stabilization. Without B, gains in D over C would be ambiguous -- you could not tell whether composition alone was the main win.

#### Targeted diagnostics

Because the source content is well understood, each experiment should report hypothesis-specific metrics beyond generic stability numbers:

**Zoom stabilization diagnostics** (per video):
- Number of detected zoom transitions
- Fraction of frames in transition mode vs settling mode vs normal
- Output crop-height variance before/after stabilization
- Output resolution (to verify stabilized signal produces tighter median)

**Composition diagnostics** (per video):
- Torso vertical position in crop (fraction from top, median and p95)
- Fraction of frames where torso is in desired upper band (< 0.42 from top)

#### Workstream breakdown

**WS4: Experiment execution**
- Goal: Update harness, run experiment, update changelog
- Owner: coder
- Work packages: 1
- Interfaces: needs working zoom stabilization and composition from WS1/WS3
- Expected patches: 1

**WP-4.1: Update experiment harness and changelog**
- Owner: coder
- Touch points: `tools/batch_encode_experiment.py`, `docs/CHANGELOG.md`
- Acceptance criteria:
  - VARIANTS dict updated to 4 variants (2x2 factorial)
  - Results table includes targeted diagnostics (zoom transition count, settling fraction, torso position, crop-height variance)
  - Experiment runs on all 7 test videos without error
  - Changelog entry describes zoom stabilization, composition, and findings
- Verification commands: `source source_me.sh && python tools/batch_encode_experiment.py`
- Dependencies: WP-1.2, WP-3.1

### Success criteria

**Pass:**
- `C_zoom_stabilized` produces smaller output resolution than `A_baseline_dc` on multimodal videos (IMG_3702, IMG_3629)
- `C_zoom_stabilized` reduces `height_jerk_p95` on IMG_3702 vs `A_baseline_dc`
- `C_zoom_stabilized` does not regress on canon_60d
- `B_torso_38` places torso measurably higher in frame than `A_baseline_dc`
- `D_zoom_stabilized_torso_38` combines both improvements without regression on any video
- Human visual review: zoom-stabilized variants feel like a dolly cam, not a chasing crop window

**Stretch:**
- Output resolution on IMG_3702 drops to reasonable crop size (not full 2816x1584)
- Zoom flicker eliminated on all 7 videos

## Patch plan

- Patch 1: tr_crop add `_detect_zoom_phases()` sliding-window detector
- Patch 2: tr_crop add three-mode constraint with local monotonicity
- Patch 3: tr_crop add torso anchor offset + composition and zoom tests
- Patch 4: batch_encode_experiment 4-variant Experiment 7b + targeted diagnostics + changelog

## Acceptance criteria and gates

**Unit gate:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v`

**Lint gate:**
- `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py -v` (no new warnings)

**Regression gate:**
- `crop_zoom_stabilization=False` (default) produces identical output to pre-change code
- `crop_torso_anchor=0.50` (default) produces identical output to pre-change code

**Integration gate:**
- Experiment 7b runs all 4 variants on all 7 test videos without error

**Quality gate:**
- Human visual review confirms dolly cam feel on zoom-stabilized variants

## Test strategy

| Level | What | File |
| --- | --- | --- |
| Unit | Zoom detector: smooth (no events), step jump, spread ramp, bidirectional, settling zones, overlap merging | test_tr_crop.py |
| Unit | Three-mode constraint: per-mode rates, monotonicity enforcement, default passthrough | test_tr_crop.py |
| Unit | Composition: anchor positions, offset scaling, default passthrough, containment interaction | test_tr_crop.py |
| Regression | Default config produces identical output to pre-change code | test_tr_crop.py |
| Lint | No new pyflakes warnings | test_pyflakes_code_lint.py |
| Experiment | 4-variant 2x2 comparison on all 7 videos with targeted diagnostics | batch_encode_experiment.py |

**Failure semantics:** Unit or regression failure blocks M3. Experiment failures trigger parameter tuning (threshold, settling duration, anchor fraction), not code rollback.

## Parameter calibration

| Parameter | Value | Rationale |
| --- | --- | --- |
| Sliding window | 5 frames | iPhone transitions take 2-5 frames at 60fps |
| Transition threshold | log(1.40) | Per-frame p95 ratio is ~1.07; 1.40 over 5 frames is clearly a zoom transition |
| Settling duration | 60 frames (1s at 60fps) | Allows oscillation to die down before next zoom cycle |
| Transition rate | 0.02x normal | Near-freeze during the magnification change |
| Settling rate | 0.20x normal | Slow convergence to new scale |
| Torso anchor | 0.38 | Torso at 38% from top; 62% below for legs/feet |

## Migration and compatibility

- **Additive only.** New behavior requires explicit config keys (`crop_zoom_stabilization=True` or `crop_torso_anchor != 0.50`). Default config produces identical output.
- **No new modules.** All changes within existing `tr_crop.py`.
- **No CLI changes.** No new flags or subcommands.
- **Backward compatible.** Existing configs without new keys behave identically.
- **Deletion criteria:** If Experiment 7b shows no improvement, remove zoom stabilization code path. Composition offset can remain dormant at default=0.50.
- **Rollback:** Both features are guarded by config checks. Disabling is a config change, not a code revert.

## Risk register

| Risk | Impact | Trigger | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| 1.40 threshold misses subtle transitions | Zoom transitions pass through undetected | Actual transitions produce < 1.40 ratio over 5 frames | Analysis data shows clear separation from normal drift (p95=1.07). Can lower to 1.30. | coder |
| 1.40 threshold catches normal drift | False positives damp legitimate distance changes | Runner approaches camera at > 8%/s | p95 of normal 5-frame ratio is ~1.35. Margin exists. Review diagnostic counts. | coder |
| 60-frame settling too long | Sluggish response after zoom change | Rapid zoom cycling (< 2s between events) | Reduce to 30 frames. User's zoom cycle is 5-15s so 1s settling has room. | coder |
| Biased monotonicity feels frozen or laggy | Crop stuck at wrong scale during settling | Real distance drift coincides with settling window | Monotonicity is biased, not absolute: sustained reversals exceeding 0.3% threshold are allowed. Normal frames have no restriction. Settling duration tunable (60 -> 30 frames). | coder |
| Output resolution still full-frame | Runner still tiny despite stabilization | Stabilized signal still has high median | Stabilized signal will have lower variance. If insufficient, follow up with mode-based output resolution. | coder |

## Rollout and release checklist

1. All M1 tests pass (zoom stabilization)
2. All M2 tests pass (composition offset)
3. Regression: default config produces identical output
4. Pyflakes lint clean
5. Experiment 7b runs all 4 variants on all 7 test videos
6. Human visual review confirms improvement
7. Changelog entry written

## Documentation close-out

- `docs/CHANGELOG.md`: entry documenting zoom stabilization, composition offset, and Experiment 7b findings
- Plan file: archive after Experiment 7b visual review
- If zoom stabilization is promoted to default: update `docs/TRACK_RUNNER_YAML_CONFIG.md`

## Open questions

1. **Transition threshold calibration.** 1.40 over 5 frames is based on analysis data showing clear separation. If IMG_3702 results show missed transitions, lower to 1.30. **Decision needed after:** reviewing zoom event diagnostic counts in experiment output.

2. **Torso anchor value.** 0.38 is the single test value. If heads are cut off, try 0.40. **Decision needed after:** visual review of variant C.

3. **Settling duration.** 60 frames (1s) is conservative. If flicker persists, increase to 90 frames. If response feels sluggish, decrease to 30 frames. **Decision needed after:** visual review.

4. **Output resolution.** The plan assumes stabilized height signal will produce a reasonable median. If not, a follow-up is needed to select output resolution from the dominant height cluster rather than the global median. **Decision needed after:** checking output resolution of zoom-stabilized variants on multimodal videos.
