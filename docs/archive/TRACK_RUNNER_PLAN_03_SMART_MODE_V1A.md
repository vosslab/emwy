# Smart Mode v1a: Segment-Aware Crop Controller

## 1. Objective

Add a regime-switching crop controller to the track runner that classifies trajectory spans into regimes (clear, uncertain, distance) and applies different crop targets per regime, so that occlusion, scale changes, and confidence drops each get appropriate crop behavior instead of one global parameter set.

## 2. Design Philosophy

**Separate perception from control.** The classifier reads trajectory signals and labels spans. The policy maps labels to crop targets. The smoother produces the final path. No stage knows about the others' internals. This follows the stabilization literature's argument that motion estimation and path smoothing should be separated, and RAVA's perception/planning/execution architecture.

**Regime changes targets, not the smoother.** Per-regime fill_ratio and size_update_mode shape what the smoother aims for. The smoother's own alpha and constraints stay global. Transitions are handled naturally by the smoother acting on a target signal that steps at regime boundaries.

**The runner is the stable perceptual anchor.** The viewer should feel like a smooth camera is tracking the runner, not like a crop window is chasing a detection box. Source-frame containment is a soft rendering constraint, not a camera-motion constraint. The virtual camera follows the subject first; black-border avoidance is a lower priority than subject stability.

**Priority hierarchy (from prior plan, carried forward):**
1. Keep the runner inside a protected composition zone
2. Keep camera motion smooth and low-order
3. Keep zoom motion smooth
4. Minimize black-border exposure
5. Only as a last resort, recenter aggressively

**The annotated torso box is a supervisory signal, not the literal camera target.** The box varies due to annotation noise, interpolation, posture changes, and human inconsistency. The crop enforces perceptual composition rules instead of blindly following boxes.

**Confidence alone must never trigger a regime change.** At least one geometric or source-type corroborating signal is required alongside confidence to classify a frame as uncertain. This prevents the classifier from becoming a slightly fancier confidence threshold machine.

**All classifier thresholds are provisional.** They will be tuned after a 7-video experiment. Initial values are starting points, not commitments.

## 3. Scope

**In scope:**
- Per-frame regime classification from trajectory data (3 regimes: clear, uncertain, distance)
- Per-regime crop target mapping (2 levers: fill_ratio, size_update_mode)
- Smart crop trajectory function that wraps direct_center with varying targets
- Global composition rules (vertical asymmetry, torso protection) -- not per-regime
- Global containment clamp and smoothing alpha -- not per-regime
- Console regime summary in analyze output
- Synthetic unit tests for all new modules
- Regression fixture test for existing crop modes
- 7-video comparative experiment across all 7 solved videos on all interval JSON files

**Non-goals:**
- Persisted regime schedule JSON file (deferred until format stabilizes)
- User-editable per-regime config overrides (deferred)
- Crowd vs fixed occlusion distinction (deferred -- current signals cannot reliably separate them)
- Containment-radius switching per regime (deferred to v1b if experiment shows need)
- Per-regime smoothing alpha overrides
- Neural net or learned classifier
- New CLI flags or subcommands

## 4. Current State

The track runner crop pipeline (`trajectory_to_crop_rects()` in `emwy_tools/track_runner/tr_crop.py:540`) dispatches to two modes:
- `smooth`: online CropController with attack/release EMA, deadband, velocity cap
- `direct_center`: offline signal processing with forward-backward EMA, zoom constraint, containment clamp

Both apply one global parameter set to the entire video. Experiments 1-5 showed that global parameters cannot handle mixed conditions (occlusion spans, far shots, close shots) in one video. The analyze subcommand (`encode_analysis.py`) already identifies instability regions and classifies their causes, but this information is not fed back into crop computation.

Per-frame trajectory data includes: cx, cy, w, h, conf, source (seed/propagated/hold_last/fallback), seed_status (visible/partial/approximate/not_in_frame). Per-interval data includes: agreement_score, identity_score, competitor_margin, convergence error (meeting_point_error).

### Reference tracker repos (OTHER_REPO_TEMP/)

Three MIT-licensed tracker implementations are available for reference:

| Repo | Key portable idea | Portability | Dependencies beyond emwy |
| --- | --- | --- | --- |
| SeqTrackv2 | Confidence-gated template update (decoder confidence score, interval + threshold gate) | High -- logic is ~10 lines, decoupled from model | torch, torchvision, timm, pytorch-pretrained-bert |
| OSTrack | Candidate elimination (early pruning of low-attention search tokens) | Low -- deeply coupled to ViT architecture | torch, torchvision, timm |
| MixFormerV2 | Score-decay adaptive template update | Medium -- update logic extractable, score requires model | torch, torchvision, timm, einops |

All three are PyTorch transformer models requiring GPU inference. For v1a, we borrow **design patterns** (confidence gating, selective trust) but not code. The SeqTrackv2 confidence-gating pattern directly informs the classifier's principle that low-confidence frames should not aggressively update crop targets.

### Test videos (all 7 with solved intervals)

| Video | Intervals file | Notes |
| --- | --- | --- |
| canon_60d_600m_zoom.MP4 | tr_config/canon_60d_600m_zoom.MP4.track_runner.intervals.json | Fair reference |
| Hononega-Orion_600m-IMG_3702.mkv | tr_config/Hononega-Orion_600m-IMG_3702.mkv.track_runner.intervals.json | Failure case |
| Hononega-Varsity_4x400m-IMG_3707.mkv | tr_config/Hononega-Varsity_4x400m-IMG_3707.mkv.track_runner.intervals.json | Relay extreme |
| IMG_3627.MOV | tr_config/IMG_3627.MOV.track_runner.intervals.json | |
| IMG_3629.mkv | tr_config/IMG_3629.mkv.track_runner.intervals.json | Dense refined |
| IMG_3823.MP4 | tr_config/IMG_3823.MP4.track_runner.intervals.json | Strong zoom |
| IMG_3830.MP4 | tr_config/IMG_3830.MP4.track_runner.intervals.json | Control video |

## 5. Architecture Boundaries

**Regime-controlled levers (exactly 2):** fill_ratio and size_update_mode. These vary per regime.

**Global controls (not per-regime in v1a):** containment radius, smoothing alpha, vertical asymmetry, torso protection. These stay at their config values regardless of regime.

| Component | Owner | Responsibility |
| --- | --- | --- |
| `regime_classifier` module | coder | Per-frame feature extraction and regime labeling |
| `regime_policies` module | coder | Regime-to-target mapping (2 levers only) |
| `smart_crop` pass in `tr_crop` | coder | Two-pass crop computation with varying targets + global composition |
| `encode_analysis` integration | coder | Regime summary in analyze output |
| Test modules | tester | Synthetic tests for classifier, policies, smart crop, regression fixture |
| Docs and changelog | planner | Plan updates, changelog entries |

### 5a. Mapping: Components to Patches

| Component (durable name) | Patches | Workstream |
| --- | --- | --- |
| `regime_classifier` module (`regime_classifier.py`) | Patch 1 | WS-Classify |
| `regime_policies` module (`regime_policies.py`) | Patch 2 | WS-Policy |
| `smart_crop` pass in `tr_crop.py` | Patch 3 | WS-Execute |
| `encode_analysis` regime summary | Patch 4 | WS-Integrate |
| `test_regime_classifier.py` | Patch 5 | WS-Test |
| `test_regime_policies.py` | Patch 6 | WS-Test |
| `test_smart_crop.py` (includes regression fixture) | Patch 7 | WS-Test |
| `tr_config.py` update + changelog | Patch 8 | WS-Integrate |

## 6. Milestone Plan

### Milestone A: Core Implementation

**Depends on:** none
**Entry criteria:** existing direct_center mode passes all tests
**Exit criteria:** all 8 patches merged, all synthetic tests pass, regression fixture passes, pyflakes clean

**Deliverables:**
- `regime_classifier.py` with classify_regimes(), feature extraction, label smoothing
- `regime_policies.py` with REGIME_DEFAULTS and get_frame_params()
- `smart_crop_trajectory()` in tr_crop.py with two-pass execution
- `crop_mode: "smart"` branch in trajectory_to_crop_rects()
- Regime summary in analyze console output
- 3 test files with synthetic trajectory tests
- Regression fixture: saved crop rects from a small known trajectory, verified unchanged for direct_center and smooth modes
- `tr_config.py` updated to accept "smart" as valid crop_mode

**Done checks:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_classifier.py -v` passes
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_policies.py -v` passes
- `source source_me.sh && python -m pytest emwy_tools/tests/test_smart_crop.py -v` passes (includes regression fixture)
- `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py -v` passes
- `source source_me.sh && python emwy_tools/track_runner/cli.py analyze -i <video>` prints regime summary

### Milestone B: 7-Video Experiment

**Depends on:** MA-exit (Milestone A exit criteria met -- need working smart mode to compare)
**Entry criteria:** all Milestone A tests pass
**Exit criteria:** comparison table produced for all 7 interval JSON files, visual review completed, thresholds tuned or accepted

**Deliverables:**
- Analyze output for all 7 test videos showing regime classifications
- Smart mode encodes for all 7 videos
- Comparison against direct_center baseline using existing analysis tooling
- Evaluation on 4-dimension rubric (lateral comfort, zoom comfort, subject lock, watchability)

**Done checks:**
- Each dimension rated per video on 3-point scale: worse / same / better
- Smart mode is "same or better" on all dimensions for >= 5 of 7 videos
- Smart mode is "better" on >= 1 dimension for failure-case videos (IMG_3702, IMG_3707). For known failure-case videos, improvement in overall watchability or subject lock counts as a successful outcome even if one secondary dimension (lateral comfort, zoom comfort) remains unchanged.
- Threshold adjustments documented in changelog if any

## 7. Workstream Breakdown

### WS-Classify: Regime Classifier

**Goal:** Produce per-frame regime labels from trajectory data using geometric + confidence signals. Confidence alone must never trigger uncertain; at least one geometric or source-type corroborating signal is required.
**Owner:** coder
**Work packages:** WP-1, WP-2 (see section 8)
**Interfaces:**
- Needs: trajectory list (from interval_solver stitch/anchor/erase pipeline), video_info dict
- Provides: list of regime span dicts to WS-Execute
**Expected patches:** 1 (Patch 1: regime_classifier module)

### WS-Policy: Regime Policies

**Goal:** Map regime labels to exactly 2 crop parameter targets (fill_ratio, size_update_mode).
**Owner:** coder
**Work packages:** WP-3 (see section 8)
**Interfaces:**
- Needs: regime span list from WS-Classify
- Provides: per-frame fill_ratio and size_update_mode to WS-Execute
**Expected patches:** 1 (Patch 2: regime_policies module)

### WS-Execute: Smart Crop Pass

**Goal:** Two-pass crop computation with regime-varying targets (2 levers) and global smoothing + global composition rules.
**Owner:** coder
**Work packages:** WP-4, WP-5 (see section 8)
**Interfaces:**
- Needs: full trajectory, regime spans from WS-Classify, frame params from WS-Policy
- Provides: crop_rects list to encoder
**Expected patches:** 1 (Patch 3: smart_crop pass in tr_crop)

### WS-Integrate: CLI and Config Wiring

**Goal:** Wire smart mode into CLI, config, and analyze output.
**Owner:** coder
**Work packages:** WP-6, WP-7 (see section 8)
**Interfaces:**
- Needs: working classifier and smart crop from WS-Classify + WS-Execute
- Provides: end-to-end smart mode via config setting
**Expected patches:** 2 (Patch 4: encode_analysis regime summary, Patch 8: tr_config + changelog)

### WS-Test: Synthetic Tests

**Goal:** Validate all new modules with deterministic synthetic trajectories. Include regression fixture to verify existing modes are unchanged.
**Owner:** tester
**Work packages:** WP-8, WP-9, WP-10 (see section 8)
**Interfaces:**
- Needs: all modules from WS-Classify, WS-Policy, WS-Execute
- Provides: test coverage, regression gate, regression fixture
**Expected patches:** 3 (Patches 5, 6, 7: one test file each)

## 8. Work Package Specs

### WP-1: Implement per-frame feature extraction

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/regime_classifier.py` (new)
**Acceptance criteria:**
- Function `_per_frame_features(trajectory, video_info)` returns list of feature dicts
- Features: conf, conf_trend (1s rolling mean), bbox_height_ratio (h / frame_height), height_change_rate (rolling normalized std), edge_pressure (min bbox-to-frame-edge distance normalized), source_type (categorical)
- convergence_quality: included when interval score data available, omitted entirely otherwise. Never substitute zero for missing convergence data -- zero would falsely signal perfect convergence. The classifier runs from features 1-6 when convergence data is absent.
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_classifier.py -k feature -v`
**Dependencies:** none

### WP-2: Implement regime classification and label smoothing

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/regime_classifier.py` (new)
**Acceptance criteria:**
- Function `classify_regimes(trajectory, video_info, config)` returns list of span dicts with start_frame, end_frame, regime, distance_flag, mean_conf, mean_bbox_ratio
- Three regimes: clear, uncertain, distance. The distance regime carries a secondary near or far flag used only for fill_ratio selection; it does not create separate smoothing logic.
- **Classifier invariant:** confidence alone must never trigger uncertain. At least one of: edge_pressure above threshold, height_change_rate above threshold, source_type is hold_last/fallback, or convergence_quality above threshold must corroborate.
- Label smoothing: minimum span duration ~0.5s, majority-vote absorption of short spans
- Blend zones: ~0.3s inserted between adjacent regime transitions
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_classifier.py -v`
**Dependencies:** WP-1 (needs feature extraction)

### WP-3: Implement regime policy mapping

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/regime_policies.py` (new)
**Acceptance criteria:**
- REGIME_DEFAULTS dict with exactly 2 keys per regime: fill_ratio and size_update_mode
- Function `get_frame_params(frame_idx, regime_spans)` returns fill_ratio (float) and size_update_mode (string) for any frame
- fill_ratio interpolated linearly in blend zones; size_update_mode uses incoming span's mode (categorical, no interpolation)
- size_update_mode values: normal, slow, frozen
- No config overrides for v1a
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_policies.py -v`
**Dependencies:** none (pure data mapping, can be built in parallel with WP-1/WP-2)

### WP-4: Implement smart_crop_trajectory two-pass function

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/tr_crop.py`
**Acceptance criteria:**
- New function `smart_crop_trajectory(trajectory, frame_w, frame_h, config, regime_spans)` returns list of (x, y, w, h) crop rects
- Target pass: per-frame desired crop height from regime fill_ratio (from policy) and bbox height; per-frame desired center from trajectory + vertical asymmetry offset (crop center shifted upward by ~0.1 * bbox height) + torso protection (torso center always in inner 60% of crop). These composition rules are global, not per-regime.
- Per-frame max_height_change array from size_update_mode (from policy): normal = config value, slow = config * 0.3, frozen = config * 0.01
- Smoothing pass: reuse existing `_forward_backward_ema()` on target signals with global alpha (from config, not per-regime); zoom constraint uses per-frame max_height_change array; containment clamp uses global config radius (not per-regime)
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_smart_crop.py -v`
**Dependencies:** WP-2 (needs regime spans), WP-3 (needs policy mapping)

### WP-5: Add crop_mode smart branch to trajectory_to_crop_rects

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/tr_crop.py` (~line 599)
**Acceptance criteria:**
- `crop_mode: "smart"` in config routes to `smart_crop_trajectory()` via regime_classifier and regime_policies
- Regime classification happens inside trajectory_to_crop_rects (no separate CLI pass needed)
- Error message for unknown crop_mode updated to include "smart"
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_smart_crop.py -k branch -v`
**Dependencies:** WP-4 (needs smart_crop_trajectory)

### WP-6: Add regime summary to encode_analysis

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/encode_analysis.py`
**Acceptance criteria:**
- After instability region analysis, call `regime_classifier.classify_regimes()` on the trajectory
- Add `regime_summary` key to analysis YAML: percentage of frames per regime, number of transitions, span list
- Print regime summary in console report (e.g., "Regimes: clear 85%, distance 10%, uncertain 5%, 4 transitions")
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_classifier.py -v`
**Dependencies:** WP-2 (needs working classifier)

### WP-7: Update tr_config and changelog

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/tr_config.py`, `docs/CHANGELOG.md`
**Acceptance criteria:**
- "smart" accepted as valid crop_mode value
- Changelog entry under appropriate date heading documenting smart mode addition
**Verification commands:**
- `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py -v`
**Dependencies:** none

### WP-8: Write test_regime_classifier.py

**Owner:** tester
**Touch points:** `emwy_tools/tests/test_regime_classifier.py` (new)
**Acceptance criteria:**
- All-high-confidence trajectory -> all clear
- Confidence drop + hold_last source -> uncertain span
- **Confidence drop alone (no geometric corroboration) -> remains clear** (enforces invariant)
- Small bbox ratio (h/frame_h < 0.08) -> distance with far flag
- Large bbox ratio (h/frame_h > 0.25) -> distance with near flag
- 3-frame blip does not create a new regime (smoothing)
- Blend zones exist at transitions
- Edge pressure contributes to uncertain classification
- Missing convergence data does not crash or produce false confidence
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_classifier.py -v`
**Dependencies:** WP-2 (needs classifier to test)

### WP-9: Write test_regime_policies.py

**Owner:** tester
**Touch points:** `emwy_tools/tests/test_regime_policies.py` (new)
**Acceptance criteria:**
- Default fill_ratio and size_update_mode returned for each regime (exactly 2 keys per regime)
- Blend zone interpolation produces intermediate fill_ratio values
- size_update_mode maps to correct max_height_change multipliers (normal=1.0, slow=0.3, frozen=0.01)
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_regime_policies.py -v`
**Dependencies:** WP-3 (needs policies to test)

### WP-10: Write test_smart_crop.py

**Owner:** tester
**Touch points:** `emwy_tools/tests/test_smart_crop.py` (new)
**Acceptance criteria:**
- **Regression fixture:** saved crop rects from a small deterministic trajectory using direct_center mode. Test verifies that direct_center output is byte-identical to the saved fixture after smart mode is added. This replaces "manual diff" as the regression gate.
- Smart mode on all-clear trajectory with composition rules disabled matches direct_center output (same fill_ratio, same size behavior). Composition rules disabled in this test to avoid self-contradiction.
- Distance-far regime produces wider crop than clear regime
- Uncertain regime near-freezes size (crop height change per frame < 0.02 * config max)
- Vertical asymmetry: crop center is above subject center (composition test)
- Torso protection: torso center is always in inner 60% of crop (composition test)
- Transitions between regimes are smooth (no frame-to-frame crop jump exceeding velocity cap)
**Verification commands:**
- `source source_me.sh && python -m pytest emwy_tools/tests/test_smart_crop.py -v`
**Dependencies:** WP-4, WP-5 (needs smart crop to test)

## 9. Patch Plan and Reporting

| Patch | Component | Intent |
| --- | --- | --- |
| Patch 1 | regime_classifier module | Per-frame features + regime labeling + smoothing |
| Patch 2 | regime_policies module | Regime-to-target mapping (2 levers) |
| Patch 3 | tr_crop smart_crop pass | Two-pass crop with varying targets + global composition |
| Patch 4 | encode_analysis | Regime summary in analyze output |
| Patch 5 | test_regime_classifier | Classifier synthetic tests (incl. confidence-alone invariant) |
| Patch 6 | test_regime_policies | Policy mapping tests |
| Patch 7 | test_smart_crop | Smart crop tests + regression fixture for existing modes |
| Patch 8 | tr_config + changelog | Config update + documentation |

Each patch touches at most 2 components. Patches 1-3 are serial (classifier -> policy -> crop). Patches 5-7 parallel the code patches. Patches 4 and 8 can proceed once their dependencies land.

## 10. Acceptance Criteria and Gates

**Unit gate:** All 3 test files pass with `pytest -v`.
**Lint gate:** `tests/test_pyflakes_code_lint.py` passes (no new lint errors).
**Integration gate:** `analyze` subcommand prints regime summary on a real video without error.
**Regression gate:** Saved fixture test verifies direct_center output is unchanged (deterministic comparison on a small known trajectory). Smooth mode is checked by additive-branch regression: the smart mode addition does not touch the smooth code path, verified by smoke testing.
**Experiment gate (Milestone B):** Smart mode rated "same or better" on all 4 dimensions for >= 5 of 7 videos.

## 11. Test Strategy

| Level | What | Files |
| --- | --- | --- |
| Unit | Classifier feature extraction, label rules, smoothing, confidence-alone invariant | test_regime_classifier.py |
| Unit | Policy defaults, blend interpolation, mode mapping | test_regime_policies.py |
| Unit | Smart crop target computation, composition rules, regime transitions | test_smart_crop.py |
| Regression | Saved fixture: direct_center output unchanged by smart mode addition | test_smart_crop.py |
| Lint | No new pyflakes warnings | test_pyflakes_code_lint.py |
| Smoke | Analyze prints regime summary on real video | manual CLI check |
| Experiment | 7-video comparison on all interval JSON files | Milestone B |

**Failure semantics:** Any unit, regression, or lint failure blocks progression from Milestone A. Experiment failures in Milestone B trigger threshold tuning, not code rollback.

## 12. Migration and Compatibility

- **Additive only.** Smart mode is a new `crop_mode` value. Existing `smooth` and `direct_center` modes are unchanged. No existing config files are affected.
- **No persistence.** No new JSON files, no schema to version. Regime schedule lives in memory only.
- **No CLI changes.** No new flags or subcommands.
- **Backward compatibility:** configs without `crop_mode: smart` behave identically to before. Verified by regression fixture, not manual inspection.
- **Deletion criteria:** none. No legacy paths created.
- **Rollback:** remove the `elif crop_mode == "smart"` branch from tr_crop.py. All other new code is unreachable without it.

## 13. Risk Register

| Risk | Impact | Trigger | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| Classifier thresholds wrong for most videos | Smart mode worse than baseline | Experiment shows "worse" on >2 videos | Thresholds are provisional; tune after experiment. If 3+ videos worse, revert to direct_center and redesign classifier. | coder |
| Two-pass execution introduces discontinuities at regime boundaries | Visual artifacts at transitions | Review of encoded output | Smoother naturally handles transitions. Blend zones add margin. Test specifically for frame-to-frame jumps. | coder |
| Vertical asymmetry / torso protection interacts badly with regime fill_ratio changes | Composition artifacts when regime switches near frame edge | Visual review of transition spans | Composition rules are global, applied after regime targets. Test with edge-case trajectories. | tester |
| Scope creep: adding containment-radius switching, persistence, config overrides | Delays and complexity | Temptation during implementation | Non-goals list is explicit. Defer to v1b. | reviewer |
| Smart mode alters existing crop_mode behavior | Regression in smooth or direct_center | Regression fixture test fails | Regression fixture is deterministic. Smart mode is additive; existing branches untouched. | tester |
| Classifier degenerates to confidence threshold | Uncertain regime triggered by confidence alone, ignoring geometry | Test for confidence-alone invariant fails | Explicit classifier invariant: confidence alone cannot trigger uncertain. Test enforces this. | coder |

## 14. Rollout and Release Checklist

1. All Milestone A tests pass (including regression fixture)
2. Pyflakes lint clean
3. Analyze runs on at least 1 real video with regime summary
4. Regression fixture passes for direct_center and smooth modes
5. Changelog entry written
6. Milestone B experiment completed on all 7 interval JSON files with documented results
7. Threshold adjustments (if any) committed and tested

## 15. Documentation Close-Out

- `docs/CHANGELOG.md`: entry documenting smart mode addition, regime definitions, composition rules, and provisional thresholds
- `docs/TRACK_RUNNER_YAML_CONFIG.md`: add `crop_mode: smart` to valid values list
- Plan file: archive after Milestone B experiment completes

## 16. Resolved Decisions

| Decision | Resolution | Rationale |
| --- | --- | --- |
| bbox_height_ratio thresholds for far/near | Temporary provisional values for Milestone A. Report observed distributions per video. Choose final thresholds only after reviewing those distributions in Milestone B. | Thresholds derived from data, not guessed up front. |
| Vertical asymmetry offset (0.1 * h) | Hardcoded for v1a. Not configurable. | Prevents knob soup. Revisit only if visual review shows per-footage adjustment is clearly needed. |
| Torso protection "inner 60%" rule | Hardcoded heuristic for v1a. Validate in Milestone B. Ready to revise if needed. | Keep it simple. Not a law, not configurable. |
| Containment radius per regime | Deferred to v1b. Global only in v1a. | Keep regime levers at exactly 2. |
| Smart mode config surface | Minimal. Only `crop_mode: smart` recognized in config. No new user-facing knobs. Regime thresholds and composition rules are implementation details, not user settings. | Smart mode is supposed to be smart, not another burden on the user. |
| Documentation location | `docs/TRACK_RUNNER_YAML_CONFIG.md` gets one line noting `crop_mode: smart` is valid. Behavior details go in `docs/TRACK_RUNNER_ANALYZE_AND_ENCODE.md`. No big new config doc. | Avoid creating a settings panel for an experiment. |

## 17. Long-Term Intent

`crop_mode: smart` is an experimental switch for comparing against baseline modes during development. It is not designed as a permanent user-facing knob family.

**If smart mode wins Milestone B:** it should become the default crop behavior. Old modes (`direct_center`, `smooth`) would be retained as fallback/debug options, not as equal user choices.

**Target end state:**
- Default: smart controller (no explicit config needed)
- Optional fallback modes for debugging only: `direct_center`, `smooth`
- Regime rules and thresholds remain implementation details, not user settings

This means the coder should not build a big config surface around smart mode. If it works, it absorbs the others. If it does not work, it gets reverted.

## 18. Execution Guidance

**Treat v1a strictly as a control-policy experiment.** The perception/policy/smoothing separation must stay intact so results are interpretable. In code review, enforce this rigidly: no smoothing logic in the classifier, no regime-specific smoothing parameters, no policy logic in the smoother.

**Expect partial success, not a final solution.** The regime approach is directionally correct and should improve mixed-condition videos, but the classifier is heuristic and the trajectory signal may remain a limiting factor.

**Do not expand config surface.** Current decision to keep smart mode non-configurable is correct. Thresholds and composition rules remain internal until after Milestone B.

**Guard against trajectory defects misclassified as regimes.** The main execution risk is not threshold tuning -- it is drift looking like "uncertain", bad scale looking like "distance", or identity switches looking like occlusion. The confidence-alone invariant mitigates this. Additional guard: if `source_type == fallback` for long spans (>2s), treat internally as a degraded condition that maps to uncertain but is not over-trusted. No new regime needed -- just prevent over-trusting those spans.

**Expect composition/fill_ratio interaction at regime boundaries.** Vertical offset and torso protection are global but interact strongly with fill_ratio changes at regime transitions. This is the most likely visual artifact. Edge cases near frame boundaries will be the first failure. Tests cover this, but visual review should pay special attention to regime transition spans near frame edges.

**If this fails, the answer is still valuable.** The experiment is falsifiable: same smoother, same trajectory, only targets change. If smart mode does not help, the conclusion is "control policy alone is insufficient given current trajectory quality" -- which directly motivates Track B and solve/refine upgrades.

**Smart mode is also a diagnostic layer.** Beyond crop control, the regime labels provide structure for the entire pipeline:
- uncertain spans are candidates for more aggressive solve/refine
- distance-far suggests smoother motion priors during interpolation
- distance-near suggests tighter constraints
- Regime spans can guide refine density and re-initialization passes

This diagnostic value persists even if the crop-control experiment is only partially successful.

## 19. Parallel Track B: Trajectory Quality Benchmark

**Purpose:** Determine whether remaining crop quality issues after smart mode are primarily control-policy limitations or upstream tracking quality problems.

**Method:** Run 2-3 failure-case videos through a pretrained tracker (SeqTrackv2 or similar, from OTHER_REPO_TEMP/) and compare:
- Center path smoothness and drift
- Scale path stability
- Occlusion behavior (confidence gating, template update timing)
- Confidence signal quality

**Scope:** This is a diagnostic investigation, not a product integration. The goal is to answer: does Smart Mode help enough with current trajectories, or is the real bottleneck the tracker itself?

**Relationship to Track A:** Track B runs in parallel with Milestones A and B. It does not block or gate Track A. Results inform the decision after Milestone B.

**Decision after Milestone B:**
- If smart mode improves most cases: promote toward default
- If gains are limited or inconsistent: prioritize improving the trajectory source before expanding regime complexity

## 20. Open Questions

None -- all design decisions resolved for v1a. Remaining unknowns (threshold values, composition constants) are explicitly provisional and will be decided by experiment, not by further planning.
