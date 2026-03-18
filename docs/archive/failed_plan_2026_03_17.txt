# Virtual Dolly Cam Crop-Mode Stabilization Plan

## Objective

Determine whether center locking, fixed crop size, or slow crop-size
tracking materially improves runner-watchability for handheld track
footage, then promote only the winning behavior into the public
crop-mode surface.

## Design Philosophy

The runner should be the stable perceptual anchor. This milestone is not
a crop-system redesign; it is a controlled stabilization cycle to identify
whether the current discomfort is caused primarily by center motion, size
motion, or both. Public API growth happens only after one experiment wins.

## Definitions

- **Milestone**: timeboxed planning unit with deliverables and gates;
  planning-doc term only.
- **Workstream**: parallel lane inside a milestone with a named owner.
- **Work package**: coder-sized assignment with acceptance criteria and
  verification commands.
- **Patch**: reviewable code change set used for implementation reporting.
- **Virtual dolly cam**: crop behavior that keeps the runner visually
  stable while background motion carries most of the perceived movement.
- **Baseline crop**: current controller output from
  `compute_crop_trajectory()` or `direct_center_crop_trajectory()` without
  new experiment overrides. All non-overridden channels in experiment
  variants are inherited from baseline rects after gap fill and controller
  safeguards.
- **Center lock**: replacing baseline crop-center motion with an offline
  smoothed center path derived directly from solved trajectory `cx, cy`
  positions (not from baseline crop centers). This intentionally bypasses
  the CropController's reactive attack/release behavior to get zero-phase-
  lag tracking. This is a design decision: locked center tests a different
  tracking objective, not a smoothed version of the existing one.
- **Fixed crop** (mode name `fixed_crop`): replacing per-frame crop height
  with one constant crop height for the full clip. The crop frame is
  constant; runner apparent size still varies with distance.
- **Slow size** (mode name `slow_size`): replacing raw per-frame crop
  height with a heavily smoothed height path that ignores small
  oscillations.
- **Axis isolation**: changing only center behavior or only size behavior
  so each effect can be evaluated independently.
- **Promotion milestone**: follow-on milestone that turns the winning
  experiment into a durable public mode and documentation surface.
- **Center jerk** (metric): magnitude of the frame-to-frame change in the
  crop center velocity vector (2D). Computed as
  `hypot(vx[i]-vx[i-1], vy[i]-vy[i-1])`. Captures abrupt changes in
  center-path velocity, including reversals.
- **Height jerk** (metric): absolute value of frame-to-frame change in
  crop height velocity. `abs(h_vel[i] - h_vel[i-1])`. Measures zoom
  pumping spikes.
- **Combined variant**: an experiment-only crop configuration that applies
  both a center strategy override and a size strategy override to baseline
  rects. In M1, dispatch first produces baseline rects, then applies an
  optional center override pass, then an optional size override pass.
  Public `crop_mode` still exposes only baseline modes. Combined variants
  are not registered as permanent modes.

## Scope

- Fix the hidden size-smoothing default in
  [emwy_tools/track_runner/tr_crop.py](emwy_tools/track_runner/tr_crop.py).
- Add internal experiment-only center and size override passes.
- Run one bounded experiment cycle on `IMG_3702` and `IMG_3830`.
- Add unit tests for invariants and update docs/changelog for the bug fix
  plus experiment outcome.

## Non-goals

- No broad crop architecture refactor.
- No permanent public YAML modes during stabilization.
- No CLI/UI changes.
- No detector, solver, propagator, or encoder redesign.
- Subject-box refinement for final-product framing is deferred until after
  crop-objective selection.

## Current State

- Current public crop surface is `smooth` plus `direct_center`; new public
  modes would be additive API work.
- Existing experiments were contaminated by the hidden default where
  `crop_post_smooth_size_strength=0` still applied size smoothing.
- The unresolved question is objective selection, not smoothing-parameter
  tuning. By testing each axis independently, then combining the winners,
  we can identify which axis matters most and which method family works
  best. Only after that do we tune parameters within the winning approach.

## Architecture Boundaries And Ownership

- Durable components: crop module, config module, experiment harness, crop
  tests, crop docs.
- Ownership boundary:
  - `coder`: crop-module internals and experiment harness.
  - `tester`: invariant and regression tests.
  - `planner`: docs, experiment rubric, changelog note.
  - `architect`: approves promotion decision after stabilization evidence.
  - `reviewer`: audits each patch before closure.

## Mapping: Milestones, Workstreams, Components, Patches

- **Milestone M1 Stabilize crop objective**
  - WS1 Crop experiment internals -> components: `tr_crop`, experiment
    config handling -> Patch 1, Patch 2.
  - WS2 Verification -> components: `test_tr_crop`, analysis outputs ->
    Patch 3.
  - WS3 Reporting -> components: experiment script, docs, changelog note ->
    Patch 4.
- **Milestone M2 Promote winning mode** (optional)
  - WS4 Public mode promotion -> components: `tr_crop`, `tr_config`, YAML
    docs -> Patch 5.
  - WS5 Cleanup and closure -> components: tests, docs, changelog ->
    Patch 6.
- Patch split rule: no patch may touch more than two components.

## Milestone Plan

### Milestone M1: Stabilize Crop Objective

- Depends on: none.
- Entry criteria: current crop path generation passes existing tests;
  hidden-default bug is reproducible.
- Deliverables:
  - Hidden-default fix.
  - Internal experiment-only override passes for center lock, fixed crop,
    and slow size.
  - Experiment cycle with baseline reference plus four experiments:
    (1) center lock only, (2) fixed crop only, (3) slow size only,
    (4) center lock + best size variant from (2)/(3). Variants (2) and
    (3) are evaluated first via human review, then variant (4) is
    instantiated using the better of the two size behaviors. This is a
    two-stage run, not one unattended batch.
  - Written recommendation: promote, iterate once more, or revert.
- Exit criteria:
  - Bug fix verified by unit test.
  - All experiment variants encoded on both videos.
  - Human review score and one functional stability metric recorded for
    every variant.
  - Winner chosen or explicit "no winner, stop promotion" decision
    documented.
- Done checks:
  - `crop_post_smooth_size_strength=0` produces true no-size-post-smoothing.
  - Fixed-height experiment yields zero crop-height variance after override.
  - Slow-scale experiment suppresses deadband-sized oscillations.
  - Center-lock experiment reduces center-path jitter versus baseline on at
    least one target clip.

### Milestone M2: Promote Winning Mode

- Depends on: DEP-M1-DECISION, reason: promotion only after stabilization
  winner is documented.
- Entry criteria: M1 exit criteria met and `architect` approves winner.
- Deliverables:
  - One promoted public crop mode only.
  - Config defaults, validation, docs, and tests updated to match the
    winning behavior.
  - Losing experiment-only toggles removed or left internal-only with no
    public docs.
- Exit criteria:
  - Public mode behavior matches experiment winner.
  - Docs describe when to use it and what it changes.
  - Regression suite passes.
- Done checks:
  - Public `crop_mode` set remains minimal and documented.
  - No temporary experiment terminology leaks into durable API names.

## Workstream Breakdown

### WS1 Crop Experiment Internals

- Goal: add the minimum internal hooks needed to isolate center and size
  behavior.
- Owner: `coder`
- Interfaces:
  - Needs: solved trajectory, baseline crop rects, processing config.
  - Provides: experiment-ready crop rect sequences.
- Expected patches: 2

### WS2 Verification

- Goal: prove the bug fix and each experiment invariant with deterministic
  tests.
- Owner: `tester`
- Interfaces:
  - Needs: experiment override hooks from WS1.
  - Provides: unit and regression evidence for gates.
- Expected patches: 1

### WS3 Reporting

- Goal: run the bounded experiment cycle and capture an explicit
  recommendation.
- Owner: `planner`
- Interfaces:
  - Needs: outputs from WS1 and WS2.
  - Provides: comparison table, human review rubric, closure note.
- Expected patches: 1

## Work Package Specs

- **Work package: Remove hidden size default**
  - Owner: `coder`
  - Touch points: `tr_crop`
  - Acceptance criteria: zero `alpha_size` means no size post-smoothing
    fallback.
  - Verification commands:
    `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py`
  - Dependencies: none

- **Work package: Add center-lock override pass**
  - Owner: `coder`
  - Touch points: `tr_crop`
  - Acceptance criteria: override preserves baseline width/height while
    replacing center path with smoothed trajectory center and optional
    velocity cap. Resulting center path has lower jerk than the raw
    trajectory center under the center jerk metric.
  - Verification commands: same pytest command
  - Dependencies: Remove hidden size default

- **Work package: Add fixed-height and slow-scale override passes**
  - Owner: `coder`
  - Touch points: `tr_crop`
  - Acceptance criteria: fixed-crop height is clip-constant and clamped by
    `crop_min_size` and frame bounds; slow-size applies deadband plus
    heavy smoothing with the same min/max guardrails.
  - Verification commands: same pytest command
  - Dependencies: Remove hidden size default

- **Work package: Extend crop invariant tests**
  - Owner: `tester`
  - Touch points: `test_tr_crop`
  - Acceptance criteria: tests cover bug fix, center-lock invariants,
    fixed-crop invariants, slow-size deadband behavior, and baseline
    inheritance.
  - Verification commands:
    `source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py`
  - Dependencies: Add center-lock override pass; Add fixed-crop and
    slow-size override passes

- **Work package: Run bounded experiment cycle and publish recommendation**
  - Owner: `planner`
  - Touch points: `tools/batch_encode_experiment.py`, docs, changelog
  - Acceptance criteria: baseline reference plus four experiments are run
    on both videos; results table names winner or says "no promotion".
  - Verification commands:
    `source source_me.sh && python tools/batch_encode_experiment.py`
  - Dependencies: Extend crop invariant tests

## Acceptance Criteria And Gates

- **Unit gate**: all crop invariant tests pass under Python 3.12.
- **Integration gate**: experiment harness can generate all planned
  variants on both target videos without manual patching.
- **Regression gate**:
  `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py`
  passes.
- **Release gate for M1**:
  - Success metric 1, functional: center-lock or size-control variant
    improves the chosen crop-stability metric versus baseline on at least
    one target clip without breaking bounds or minimum-size invariants.
  - Success metric 2, visual: human review median overall comfort score
    improves by at least 1 point on the 0-3 rubric for at least one
    variant.
- **Promotion gate for M2**: exactly one winner is selected; if no clear
  winner exists, stop after M1 and do not add public modes.

## Test And Verification Strategy

- Unit checks: bug-fix behavior, fixed-crop exact height constancy,
  slow-size deadband rejection, center-lock center-path smoothing, bounds
  clamping.
- Integration checks: experiment harness builds baseline plus four
  experiment outputs from the same input trajectory.
- Smoke checks: both target videos complete overnight without manual
  intervention.
- Human review: blinded variant review using one gate score,
  `overall_comfort_0_to_3`. Optional context tags per clip (e.g.,
  "center drift", "zoom pumping", "best overall") for diagnosis but
  not used as gate criteria.
- Failure semantics: any invariant failure blocks M1 exit; inconclusive
  human review blocks M2 promotion.

## Migration And Compatibility Policy

- M1 is internal-only and additive; no public config contract changes.
- Existing `smooth` and `direct_center` remain unchanged during
  stabilization.
- M2 may add one public mode only after approval.
- Deletion rule: experiment-only toggles not promoted in M2 are removed
  from public config/docs and may remain internal only if needed for
  future experiments.

## Risk Register And Mitigations

- **Risk**: hidden-default fix changes historical semantics of zero size
  smoothing from implicit coupling to true disable. Existing configs
  relying on the hidden default will produce different output. Owner:
  `coder`. Mitigation: document in CHANGELOG; one-line revert if needed.
- **Risk**: experiment refactor changes baseline behavior. Owner: `coder`.
  Mitigation: baseline rect sequence must remain numerically identical
  (within test tolerance) when no override is active.
- **Risk**: too many variants dilute conclusions. Owner: `planner`.
  Mitigation: limit M1 to baseline reference plus four experiments.
- **Risk**: public API grows before evidence exists. Owner: `architect`.
  Mitigation: block M2 until promotion gate passes.
- **Risk**: human review is noisy. Owner: `planner`. Mitigation: use one
  visual score and fixed target clips only.

## Rollout And Release Checklist

- M1: ship bug fix plus experiment evidence only.
- M2: promote one winner, update config/docs/tests, remove non-winning
  public surface.
- Closure requires reviewer sign-off on every patch and architect sign-off
  on promotion.

## Documentation Close-Out Requirements

- Record the hidden-default bug fix in `docs/CHANGELOG.md`.
- If M2 happens, update `docs/TRACK_RUNNER_YAML_CONFIG.md` with only the
  winning public mode.
- Archive the experiment summary with the decision and loser rationale.

## Patch Plan And Reporting Format

- Patch 1: `tr_crop` remove hidden size fallback and preserve baseline
  behavior.
- Patch 2: `tr_crop` add experiment-only center and size override passes.
- Patch 3: crop tests add stabilization invariants and regression coverage.
- Patch 4: experiment harness and docs publish bounded results and
  recommendation.
- Patch 5: `tr_crop` and `tr_config` promote one winning public mode.
- Patch 6: tests, migration, docs close out promoted mode and remove
  unused public knobs.

## Open Questions And Decisions Needed

- None for M1; defaults are fixed as follows:
  - Treat baseline as reference, not as one of the five experiments.
  - Keep new behavior internal-only during stabilization.
  - Promote at most one public mode after evidence, not three at once.

## Post-plan: Torso box refinement (M3)

### Objective

Reduce torso-box noise so the winning crop mode from M2 receives a
cleaner, more stable input signal for center and/or size control.
This milestone does not change the crop objective. It improves the
measurement feeding the objective. M3 consumes the winning crop
objective from M1/M2 rather than redefining it.

### Design principle

Separate what to stabilize from what to measure.
- M1/M2 choose the correct control objective.
- M3 improves the input signal so that objective performs well.

**Core M3 insight:** The background is approximately rigid across
adjacent frames, while the runner is non-rigid and produces high-
frequency bbox variation from gait and pose. M3 therefore treats
background motion as the primary source for frame-to-frame camera
transform estimation, and treats the runner only as the subject anchor.

The goal is to stop asking a single noisy torso bbox to do three jobs
(camera motion, true subject motion, and pose deformation) and instead
split those responsibilities:
- **Background** = stable geometry -> estimate camera motion
- **Runner** = unstable silhouette -> estimate subject anchor only
- **Fuse** them instead of trusting one bbox for both

**Known limitation:** Background motion estimation may break when the
runner occupies too much of the frame or when the camera motion is fast
enough to blur background features. The implementation should detect
these conditions and fall back to bbox-only behavior gracefully.

### Thought experiments

**1. Separate camera motion from subject deformation.**
Each frame contains: a mostly rigid background undergoing smooth
low-order scene motion + a non-rigid foreground runner. If you estimate the background transform between
adjacent frames, much of the apparent crop jitter can be explained as
camera motion, not runner motion. The crop controller can then work in
a stabilized coordinate system: first subtract estimated background
motion, then track the runner in that compensated space. Expected:
center lock becomes much cleaner.

**2. Background-derived scale instead of runner-derived scale.**
The background (track, lanes, stands) undergoes only smooth low-order
scene motion from camera panning. Its apparent scale changes predictably.
The runner is a blob of swinging arms and pumping legs whose bbox
changes shape every frame. Hypothesis: deriving scale change from
background feature motion produces a much cleaner signal than runner
bbox height. Use sparse feature tracking on lane lines, railings, or
track markings. Use runner bbox only for center, not for scale.
Expected: materially smoother scale signal at the source.

**3. Background as veto signal for size updates.**
If the runner box suddenly gets 8% taller in one frame, two
possibilities: real approach/zoom, or pose/detector artifact. If the
background transform shows almost no scale change, the height jump is
probably not real. The background can veto the update. Rule: allow
size updates only when scene evidence agrees; otherwise hold or slowly
blend. This is much stronger than filtering the runner box alone.

**4. Anatomical anchor for center, scene for motion.**
The runner's location matters, but not every part should influence it
equally. Better split: runner-derived anchor for who to center on
(hips, shoulders, torso midpoint) + background-derived motion model
for how the frame itself is moving (feature tracks on stable scene
elements). Two pipelines, then compose them.

**5. Scene-relative subject stability as the correct metric.**
Instead of "how noisy is the bbox center?", ask "how stable is the
runner relative to the stabilized background frame?" The viewer
probably tolerates consistent background slide more than subject
wobble from pose-driven box noise. M3 metric: subject anchor variance
after background-motion compensation.

**6. Outlier rejection via scene consistency.**
Single-frame detection failures (sudden height spike, lateral jump,
partial occlusion) can be caught by checking whether the background
transform agrees. Hold previous value when scene evidence contradicts
the runner measurement. Expected: large improvement in worst-case
stability with minimal complexity.

**7. Model runner height as: slow scene-scale + fast body-shape + noise.**
Short-timescale size changes are mostly pose noise; long-timescale size
changes are mostly true distance/camera change. This argues for tying
size updates to scene motion evidence rather than filtering a dirty
signal. Enforce monotonic segments when distance is clearly changing.

**8. One box vs two signals (from bbox-signal engineering).**
A single bbox is doing two jobs poorly: tracking position (center) and
estimating scale (height). These have different noise characteristics.
Split into a tracking signal for center (stable, possibly keypoint-
based) and a sizing signal for height (robust to pose, possibly
percentile or median-filtered). Expected: reduced coupling between
center jitter and scale jitter.

**9. Box shape vs scalar height (bbox practical sanity check).**
Width changes from arm swing corrupt height-based scaling indirectly
via bbox coupling. Derive scale from height only, ignore width, or
use a torso-only region for scale. Expected: reduced scale jitter
from lateral motion. This is a simple signal fix that complements
the background-derived approach.

### M3 implementation options (two pipelines + fusion)

**Background motion pipeline:**
- Sparse optical flow on non-runner regions
- Feature matching on lane lines, railings, track markings
- Simple translation model first, optionally translation + scale
- Output: per-frame camera transform estimate

**Subject anchor pipeline:**
- Hips midpoint, shoulders midpoint, or torso center from reduced box
- Filtered anchor independent of bbox width swings
- Output: per-frame subject position in scene-compensated coordinates

**Fusion rules:**
- Scene motion updates every frame
- Subject center updates in scene-compensated coordinates
- Size changes accepted only when consistent with slow scene-scale trend
- Background veto on single-frame outlier jumps

### Candidate work packages (M3)

- Add background motion estimation (sparse flow on non-runner regions)
- Add subject anchor pipeline (keypoint-based or reduced-box center)
- Add scene-consistent size update rules (background veto + slow trend)
- Add scene-relative stability metric
- Add outlier rejection via scene consistency checks
- Extend tests for signal stability invariants

### Metrics

Reuse M1 metrics, applied to input signals:
- Center jerk (input vs refined)
- Height jerk (input vs refined)
- Outlier sensitivity (max deviation under spike)
- Downstream improvement in winning crop mode

### Exit criteria

- Refined signal reduces jerk metrics vs raw bbox signal
- Winning M2 crop mode shows measurable improvement using refined input
- No regression in bounds, min-size, or tracking continuity

### Key constraint

Do not re-open the crop-objective decision. M3 only improves the signal
feeding the already selected behavior.
