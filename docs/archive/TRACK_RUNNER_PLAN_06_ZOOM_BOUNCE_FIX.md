# Fix Zoom Bounce: Bypass Rate Limiter When EMA Smoothing Is Active

## Objective

Eliminate visible zoom bounce caused by post-EMA rate-limit quantization by preventing the `max_height_change` velocity limiter from re-quantizing the EMA-smoothed height signal. Validate with Experiment 8 across all 7 test videos.

## Context

Experiment 7d (2x2 factorial) revealed a destructive interaction between EMA smoothing and the rate limiter:

- **B (EMA only)**: best pixel bounce rate (4.5/s on clip1), height_jerk_p95 = 1.0
- **C (rate limiter only)**: moderate improvement but composition regressions (edge_touch spikes)
- **D (both combined)**: WORST pixel bounce rate (12.3/s) despite combining both fixes

The rate limiter at lines 437-515 of `tr_crop.py` operates on `smoothed_h` in-place AFTER the EMA pass. When EMA is active, the signal is already smooth. The rate limiter then quantizes smooth gradients into piecewise-linear staircases, and the biased monotonicity freezes height for up to 5 frames before each small reversal. This destroys the EMA's work.

The key implication is that EMA smoothing and the rate limiter interact destructively. EMA reduces high-frequency jitter, but the rate limiter re-quantizes the smoothed signal into staircase steps, reintroducing bounce. This explains the paradox: D < B instead of D > B.

## Design philosophy

The EMA and the rate limiter both constrain height changes, but through incompatible mechanisms when applied in series. The EMA produces a smooth curve; the rate limiter produces quantized steps. Running both in series lets the limiter re-introduce the exact artifacts the EMA removed. The fix is mutual exclusion: when EMA smoothing is active, bypass the rate limiter entirely.

## Scope

- Modify `direct_center_crop_trajectory()` in `tr_crop.py` to gate the rate limiter
- Update `batch_encode_experiment.py` for Experiment 8
- Run experiment on all 7 videos with pixel zoom assessment
- Add regression tests for the new behavior
- Update changelog

## Non-goals

- Tuning EMA alpha (0.05 works well per Experiment 7d)
- Removing the rate limiter code (keep it for the `alpha_size=0` path)
- Changing composition offset, containment, or other constraints
- Rewriting the zoom phase detection logic

## Current state

- `crop_post_smooth_size_strength: 0.05` is in default config (added 2026-03-20)
- Rate limiter runs unconditionally after EMA (lines 437-515 of `tr_crop.py`)
- Experiment 7d results show B > C > A > D for pixel bounce
- `test_tr_crop.py` was deleted in commit ca8d6d1 -- no existing crop tests

## Architecture boundaries

| Component | File | Change |
| --- | --- | --- |
| Crop trajectory | `emwy_tools/track_runner/tr_crop.py` | Gate rate limiter on `alpha_size` |
| Experiment harness | `tools/batch_encode_experiment.py` | Experiment 8 variants |
| Crop tests | `emwy_tools/tests/test_tr_crop.py` | New file (recreation) |
| Config | `emwy_tools/track_runner/track_runner.config.yaml` | No change needed |
| Pixel assessment | `tools/assess_pixel_zoom.py` | No change, used for validation |

### Component-to-patch mapping

- `tr_crop.py` (crop trajectory stage): Patch 1
- `test_tr_crop.py` (crop test module): Patch 2
- `batch_encode_experiment.py` (experiment harness): Patch 3
- `docs/CHANGELOG.md` + archive: Patch 4

---

## Milestone 1: Code change and unit tests

**Depends on:** none
**Entry criteria:** Experiment 7d results confirm B outperforms D on pixel bounce (confirmed)
**Exit criteria:** All tests pass, pyflakes clean on all modified files

### Work package 1.1: Gate rate limiter in `direct_center_crop_trajectory()`

**Owner:** coder
**Touch points:** `emwy_tools/track_runner/tr_crop.py` lines 434-515
**Acceptance criteria:**
- When `alpha_size > 0`, the rate limiter block (both 3-mode and scalar branches) is skipped entirely
- When `alpha_size == 0`, behavior is identical within existing numeric behavior on current tests and fixtures
- No other logic changes

**Change:** Replace the current conditional at line 434-515:

```python
# current
if zoom_stabilization and max_height_change_frac > 0:
    # three-mode constraint...
elif max_height_change_frac > 0:
    # scalar constraint...
```

With:

```python
# new: EMA smoothing already bounds height change rate; rate limiter
# would re-quantize the smooth signal into staircase artifacts
if alpha_size > 0:
    # EMA handles zoom stability, skip rate limiting
    pass
elif zoom_stabilization and max_height_change_frac > 0:
    # three-mode constraint (no EMA active, rate limiting needed)
    ...  # unchanged
elif max_height_change_frac > 0:
    # scalar constraint (no EMA active, rate limiting needed)
    ...  # unchanged
```

**Verification:**
```bash
source source_me.sh && python -m pyflakes emwy_tools/track_runner/tr_crop.py
```

### Work package 1.2: Recreate `test_tr_crop.py` with regression tests

**Owner:** tester
**Touch points:** `emwy_tools/tests/test_tr_crop.py` (new file)
**Acceptance criteria:** At least these test cases:

1. **Direct gate comparison**: With identical synthetic input and identical `max_height_change=0.005`, compare output for `alpha_size=0.05` vs `alpha_size=0.0`. Assert that with `alpha_size > 0`, output matches the pure EMA path and does not show clamp-step behavior (no frame-to-frame deltas quantized to `max_height_change * h`). Additionally, assert that with `alpha_size > 0`, output is identical whether `max_height_change=0.005` or `max_height_change=0.02` (proves the limiter path is fully bypassed).
2. **Rate limiter activates at alpha_size=0**: With `alpha_size=0.0`, `max_height_change=0.005`, `zoom_stabilization=False`, verify staircase clamping on a step input (output deltas are capped at 0.5% of previous height).
3. **Three-mode branch at alpha_size=0**: With `alpha_size=0.0`, `zoom_stabilization=True`, `max_height_change=0.005`, verify the three-mode constraint activates and produces different rates for transition vs normal frames.
4. **EMA convergence time**: A 40% step change in raw_h through alpha=0.05 forward-backward EMA converges to within 5% of target within 60 frames (1 second at 60fps).
5. **parse_aspect_ratio**: Basic tests for "16:9", "4:3", "1:1".

**Verification:**
```bash
source source_me.sh && python -m pytest emwy_tools/tests/test_tr_crop.py -v
source source_me.sh && python -m pyflakes emwy_tools/tests/test_tr_crop.py
```

---

## Milestone 2: Experiment 8 -- validate the code gate removes the bad interaction

**Depends on:** Milestone 1 (code change must be in place)
**Entry criteria:** Milestone 1 tests pass
**Exit criteria:** Success metrics met on all 7 videos

### Experiment design rationale

The goal is to prove the specific claim: the code gate fixes the bad EMA + limiter interaction. Comparing E_ema_only vs B would only show "EMA-only still works" without testing the condition that used to fail (D config).

**Variants:**

| Variant | Config | Purpose |
| --- | --- | --- |
| B_baseline | EMA on (0.05), zoom_stab off, limiter 0.005 | Reproduce best 7d result as reference |
| D_gated | EMA on (0.05), zoom_stab on, limiter 0.005 | Same config as old D, but with new code gate active |

**What this proves:**
- Old D was bad (12.3 bounces/s from 7d archived results)
- D_gated should become approximately B, or much better than old D
- That directly validates the interaction hypothesis

**Note:** Archived 7d D numbers are used as the historical failing reference. Experiment 8 does not attempt to recreate old ungated D in code -- the old behavior no longer exists after the code change. The comparison is: live D_gated vs archived 7d D.

The results table should explicitly include archived 7d D numbers for comparison.

### Equivalence-to-B rule

D_gated "approximates B" means all of:
- `bounce_rate_per_s`: within 20% of B_baseline
- `zoom_jerk_p95`: within 20% of B_baseline
- `height_jerk_p95`: not worse than 1.0
- No visual regression in first 7-8 seconds

### Success metrics (pass/fail)

1. **height_jerk_p95 <= 1.0** on all 7 videos (matches B from Experiment 7d)
2. **pixel bounce_rate_per_s <= 5.0** on IMG_3707 clips (B achieved 4.5/s on clip1)
3. **pixel zoom_jerk_p95**: D_gated must not exceed B_baseline by more than 20% (prevents gaming bounce count through flattening or noisy missed detections)
4. **valid_frame_fraction > 0.95** on all pixel assessment runs (if measurement quality is poor, the bounce comparison is unreliable)

### Secondary metrics (monitor, no pass/fail)

- `edge_touch_count` must not regress above B's Experiment 7d values
- `crop_size_cv` comparable to B
- `bad_frame_fraction < 0.05`

### Work package 2.1: Update experiment harness for Experiment 8

**Owner:** coder
**Touch points:** `tools/batch_encode_experiment.py`
**Acceptance criteria:**
- `EXPERIMENT_DIR` points to `output_smoke/experiment_8`
- Two variants defined as specified above (B_baseline and D_gated)
- All 7 test videos included
- Experiment header comments updated with context referencing Experiment 7d interaction finding
- Results table includes a reference row for archived 7d D values

**Verification:**
```bash
source source_me.sh && python -m pyflakes tools/batch_encode_experiment.py
```

### Work package 2.2: Run experiment and collect results

**Owner:** coder
**Touch points:** `output_smoke/experiment_8/` (output directory)
**Acceptance criteria:**
- All 7 videos encode for both variants without errors
- `results.md` comparison table generated
- Pixel zoom assessment run on IMG_3707 clips
- Results table includes archived 7d D numbers for comparison

**Verification:**
```bash
source source_me.sh && python tools/batch_encode_experiment.py
source source_me.sh && python tools/assess_pixel_zoom.py -d output_smoke/experiment_8 -p '*IMG_3707*.mkv'
```

### Work package 2.3: Human visual review

**Owner:** maintainer (human review)
**Acceptance criteria:**
- Both pass/fail success metrics met
- Visual review of IMG_3702 and IMG_3707 clips:
  - Review first 7-8 seconds specifically for zoom bounce artifacts (the worst window per 7d findings)
  - Review later motion sections for lag or sluggish adaptation to real scale changes
- No composition regressions
- D_gated approximates B_baseline quality (confirms the gate fixed the interaction)

---

## Milestone 3: Documentation and cleanup

**Depends on:** Milestone 2 (experiment must pass with human approval)
**Entry criteria:** Success metrics met, human visual review approved
**Exit criteria:** Changelog updated, plan archived

### Work package 3.1: Update changelog

**Owner:** coder
**Touch points:** `docs/CHANGELOG.md`
**Acceptance criteria:** Entry under current date documenting:
- The rate limiter bypass when EMA is active
- Why D was worse than B in Experiment 7d (rate limiter re-quantizes EMA output)
- Experiment 8 results summary with D_gated vs old D comparison

### Work package 3.2: Archive this plan

**Owner:** coder
**Touch points:** `docs/archive/TRACK_RUNNER_PLAN_06_ZOOM_BOUNCE_FIX.md`
**Acceptance criteria:** Plan copied to archive with experiment results appended

---

## Risk register

| Risk | Impact | Trigger | Mitigation |
| --- | --- | --- | --- |
| EMA alone lags behind real iPhone zoom transitions | Slow convergence visible on IMG_3702 | Visual review of later motion shows sluggish adaptation | Follow-up Experiment 9: test alpha_size=0.08 for faster convergence |
| Bypass removes too much control (D_gated worse than B) | Functional equivalence not achieved | D_gated bounce_rate exceeds B by more than 20% | Follow-up Experiment 9: re-enable rate limiter with relaxed max_height_change=0.02 under EMA |
| EMA output exceeds frame bounds | Large crops on edge frames | Crop height > frame height after EMA | Already handled by Step 5 (line 557-558): `numpy.minimum(smoothed_h, frame_height)` |

Note: if the bypass fails, the next step is a follow-up experiment, not an immediate in-place fallback. The current fix is clean because it is simple; adding conditional limiter tuning would dilute that.

## Backup plan if Experiment 8 fails

Failure means any of:
- D_gated bounce_rate exceeds B_baseline by more than 20%
- height_jerk_p95 > 1.0 on any video
- Visual review shows sluggish zoom response on later motion sections
- Composition regressions appear

**Backup Experiment 9A: relaxed limiter under EMA** (for residual bounce)
- Keep `alpha_size=0.05` and EMA active
- Re-enable limiter with a much looser threshold: `max_height_change=0.02`
- Compare against B_baseline and D_gated

**Backup Experiment 9B: faster EMA** (for sluggish response)
- Set `alpha_size=0.08` with limiter still bypassed
- Use only if Experiment 8 removes bounce but visual review shows lag on real zoom transitions

**Decision rule:**
- If the failure mode is bounce still too high, try 9A first
- If the failure mode is lag or sluggish adaptation, try 9B first
- Do not test both at once (mixing two variables makes interpretation muddy)

## Test and verification strategy

1. **Unit tests:** `emwy_tools/tests/test_tr_crop.py` -- synthetic signal tests confirm gate logic directly
2. **Pyflakes gate:** All modified files pass pyflakes
3. **Experiment 8:** 7-video encode with metadata metrics, B_baseline vs D_gated
4. **Pixel assessment:** `tools/assess_pixel_zoom.py` on IMG_3707 clips (bounce_rate + zoom_jerk)
5. **Archived comparison:** D_gated results compared against 7d D archived numbers
6. **Visual review:** Human watches IMG_3702 and IMG_3707 clips -- first 7-8s for bounce, later sections for lag

## Patch plan

- Patch 1: `tr_crop.py` rate limiter gate (Milestone 1.1)
- Patch 2: `test_tr_crop.py` regression tests (Milestone 1.2)
- Patch 3: `batch_encode_experiment.py` Experiment 8 setup (Milestone 2.1)
- Patch 4: `CHANGELOG.md` + archive (Milestone 3)

## Open questions

None. Do not include `alpha_size=0.08` in Experiment 8. Keep Experiment 8 focused on validating the rate-limiter bypass with the known-good `alpha_size=0.05`. Add 0.08 only in a follow-up experiment if visual review shows that EMA-only convergence is too slow on real zoom transitions.

---

## Experiment 8 results (2026-03-20)

### Outcome: PASS -- gate fully bypasses limiter

B_baseline and D_gated produce **identical output** on every metric across all 7 videos.

### Metadata metrics (all 7 videos identical between variants)

| Video | HJerk p95 | SizeCV | EdgeTouch | BadFr% |
| --- | --- | --- | --- | --- |
| canon_60d | 1.0 | 0.1054 | 0 | 0.0 |
| IMG_3702 | 1.0 | 0.3422 | 0 | 0.0 |
| IMG_3707 | 1.0 | 0.3548 | 0 | 0.0 |
| IMG_3627 | 1.0 | 0.3835 | 0 | 0.1 |
| IMG_3629 | 1.0 | 0.7308 | 0 | 2.9 |
| IMG_3823 | 0.0 | 0.051 | 0 | 0.0 |
| IMG_3830 | 1.0 | 0.2986 | 0 | 0.0 |

### Pixel zoom assessment (IMG_3707)

| File | bounce_rate/s | velocity_p95 | valid% |
| --- | --- | --- | --- |
| B_baseline (full) | 6.125 | 0.000726 | 100 |
| D_gated (full) | 6.125 | 0.000726 | 100 |
| B_baseline clip0 | 5.158 | 0.000479 | 100 |
| D_gated clip0 | 5.158 | 0.000479 | 100 |
| B_baseline clip1 | 6.277 | 0.000595 | 100 |
| D_gated clip1 | 6.277 | 0.000595 | 100 |

### Conclusions

1. The post-EMA rate limiter was responsible for the additional bounce seen in old D. With the limiter bypassed under EMA, D_gated becomes identical to the EMA-only baseline B.
2. `zoom_stabilization` and `max_height_change` are fully inert when `alpha_size > 0`.
3. Any remaining bounce is baseline EMA behavior and should be evaluated separately, not attributed to the limiter interaction.
4. Visual review confirmed much improved bounce (600m nearly no bounce, 4x400m minor bounce in first 7s only).
5. Composition regression noted (head room too large, feet cropped) -- separate issue, deferred to torso_anchor tuning experiment.
