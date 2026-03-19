# Changelog

## 2026-03-19

### Fixes and Maintenance
- Removed `processing` section from all 6 per-video config files in `tr_config/`. These files had stale `crop_fill_ratio: 0.1` from before Experiment 5 established 0.30 as the correct value. The experiment harness did not override this key, so all Experiment 7 variants silently ran with the wrong fill ratio, producing full-frame output (2816x1584 on IMG_3702) instead of tight crops. Root cause: processing parameters were duplicated across per-video configs instead of being controlled by the experiment.
- Consolidated 6 identical per-video `*.track_runner.config.yaml` files into one global [tr_config/track_runner.config.yaml](tr_config/track_runner.config.yaml). Per-video configs contained only detection settings (model, confidence_threshold) which were identical across all videos. Processing parameters now live exclusively in the experiment variant overrides in [tools/batch_encode_experiment.py](tools/batch_encode_experiment.py).
- Added `crop_fill_ratio`, `crop_aspect`, `video_codec`, `crf`, and `encode_filters` to experiment variant overrides so all processing is controlled in one place.

### Decisions and Failures
- Per-video config files with processing settings are a maintenance trap. Processing parameters that the experiment controls must not also live in per-video YAML files where they go stale. Detection-only configs are the correct separation: detection settings describe the video, processing settings describe the experiment.

## 2026-03-18

### Additions and New Features
- Added vertical composition offset to `direct_center_crop_trajectory()` in [emwy_tools/track_runner/tr_crop.py](emwy_tools/track_runner/tr_crop.py). New `crop_torso_anchor` config key (default 0.50 = centered) places the torso at a specified vertical fraction within the crop frame. Anchor < 0.5 shifts the crop down so the torso appears higher, leaving more room below for legs and feet. Offset is derived from smoothed crop height (not raw bbox height) to avoid coupling tracking noise into vertical camera motion.
- Added sliding-window zoom phase detector `_detect_zoom_phases()` to [emwy_tools/track_runner/tr_crop.py](emwy_tools/track_runner/tr_crop.py). Treats crop height as a noisy time series: uses 5-frame sliding window to detect camera zoom transitions (iPhone lens switches) when max/min ratio exceeds 1.40. Returns separate transition and settling masks. Settling zones of 60 frames follow each transition block. Replaces the prior single-frame `_detect_zoom_events()` approach which missed multi-frame iPhone transitions.
- Added three-mode piecewise zoom constraint to `direct_center_crop_trajectory()`. New `crop_zoom_stabilization` config key (default False) enables per-frame rate limiting with three modes: transition (0.02x normal rate, near-freeze), settling (0.20x normal rate, slow convergence with biased monotonicity to suppress small reversals), and normal (1.0x, unrestricted). Replaces the prior `crop_zoom_event_damping` two-mode approach. When disabled, behavior is identical to the scalar constraint.
- Added zoom phase detection tests and three-mode stabilization tests to [emwy_tools/tests/test_tr_crop.py](emwy_tools/tests/test_tr_crop.py): smooth signal no phases, large jump detected, zoom-out detected, gradual ramp not detected, spread ramp detected, overlapping events merge, no overlap between masks, stabilization disabled matches baseline, transition mode near-freeze, settling mode slow convergence, normal rate after settling, biased monotonicity suppresses small reversals.
- Updated [tools/batch_encode_experiment.py](tools/batch_encode_experiment.py) to Experiment 7b: 2x2 factorial design with 4 variants (A_baseline_dc, B_torso_38, C_zoom_stabilized, D_zoom_stabilized_torso_38) isolating composition offset and piecewise zoom stabilization independently. Added targeted diagnostics: zoom transition block count, per-mode frame fractions, crop height variance, torso vertical position (median, p95, upper-band fraction).
- Added `crop_mode: smart` regime-switching crop controller to track runner. Classifies trajectory spans into 3 regimes (clear, uncertain, distance) using geometric + confidence signals, then applies per-regime crop targets (fill_ratio and size_update_mode). Uses offline two-pass processing with global smoothing. New modules: [emwy_tools/track_runner/regime_classifier.py](emwy_tools/track_runner/regime_classifier.py), [emwy_tools/track_runner/regime_policies.py](emwy_tools/track_runner/regime_policies.py).
- Classifier invariant: confidence alone cannot trigger uncertain regime -- requires geometric or source-type corroboration (edge pressure, height instability, or degraded source type).
- Added regime classification summary to `analyze` subcommand console output (percentage per regime, transition count). Regime spans also written to analysis YAML.
- Added 3 test files: [emwy_tools/tests/test_regime_classifier.py](emwy_tools/tests/test_regime_classifier.py) (21 tests), [emwy_tools/tests/test_regime_policies.py](emwy_tools/tests/test_regime_policies.py) (13 tests), [emwy_tools/tests/test_smart_crop.py](emwy_tools/tests/test_smart_crop.py) (10 tests including regression fixture for direct_center).
- Documented `crop_mode: smart` in [docs/TRACK_RUNNER_YAML_CONFIG.md](docs/TRACK_RUNNER_YAML_CONFIG.md). All thresholds are provisional pending 7-video experiment.
- Added Experiment 6 batch script [tools/batch_smart_experiment.py](tools/batch_smart_experiment.py) for smart vs baseline comparison across all 7 test videos.

### Decisions and Failures
- Experiment 6 (smart mode v1a vs baseline direct_center): smart mode passed the quantitative metric gate (SizeCV improved on 6/7 videos, CJerk improved on 3/7) but failed visual review on key failure case IMG_3702. Baseline direct_center is visually better. Smart mode introduces "rocking boat" low-frequency drift and visible zoom inconsistency from too-frequent regime transitions (21 transitions in 92s). Broad regime-level policy switching is too coarse for this video -- the real problem is a small number of specific major zoom-shift events that need targeted counteraction, not whole-span policy changes. Smart mode v1a is a diagnostic experiment, not a promotion candidate.
- Vertical asymmetry composition (torso offset) was prototyped and reverted. The initial implementation tied vertical offset to per-frame raw bbox height, coupling tracking noise into vertical camera motion. Correct approach: express composition as a torso anchor fraction within the crop (e.g., torso at 35-40% from top), derived from smoothed crop height, and test as a separate composition-only experiment on baseline_dc.
- Next direction: keep baseline direct_center as the visual winner. Design composition experiment (torso anchor fraction) separately. Design v1b as event-aware local size suppression, not broad regime switching.

### Fixes and Maintenance
- **Bug fix**: made `write_intervals()` and `write_diagnostics()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) use atomic writes (temp file + `os.replace`), matching the pattern `write_seeds()` already used. Previously these wrote directly to the target file, so an interrupted refine process could leave a truncated/corrupt JSON file. This caused IMG_3707 intervals to be unreadable during Experiment 5.
- Renamed four archived plan files in `docs/archive/` from random generated names to descriptive sequenced names: `TRACK_RUNNER_PLAN_01_AXIS_ISOLATION.md`, `TRACK_RUNNER_PLAN_02_CONSTRAINT_STABILIZATION.md`, `TRACK_RUNNER_PLAN_03_SMART_MODE_V1A.md`, `TRACK_RUNNER_PLAN_04_COMPOSITION_ZOOM.md`.

## 2026-03-17

### Additions and New Features
- Added composition-quality metrics to [emwy_tools/track_runner/encode_analysis.py](emwy_tools/track_runner/encode_analysis.py): `_compute_composition_metrics()` computes per-frame center offset (anisotropic normalization), edge margin, and per-cause bad frame flags (bad_center, bad_edge, bad_zoom). Summary metrics include center_offset_p50/p95/max, edge_margin_min_px/p05, edge_touch_count, bad_frame_fraction with per-cause breakdowns, and bad_run_max_length/count. `_compute_bad_frame_runs()` finds consecutive bad-frame runs. Integrated into `analyze_crop_stability()` under the `"composition"` key.
- Added center containment clamp and zoom stability constraint to `direct_center_crop_trajectory()` in [emwy_tools/track_runner/tr_crop.py](emwy_tools/track_runner/tr_crop.py). Containment clamp uses anisotropic normalization with double-pass (clamp, re-smooth at alpha=0.3, re-clamp) to keep subject within a protected composition zone. Zoom constraint limits per-frame height change to 0.5% (configurable via `crop_max_height_change`). Black fill policy: crop position is no longer clamped to frame bounds -- the virtual camera follows the subject and `apply_crop()` fills out-of-bounds with black. New config keys: `crop_containment_radius` (default 0.20), `crop_max_height_change` (default 0.005).
- Added composition metric tests to [emwy_tools/tests/test_encode_analysis.py](emwy_tools/tests/test_encode_analysis.py): centered subject (low offset), edge-drifted subject (high offset, edge touch), bad-frame run detection, per-cause flag isolation (bad_center vs bad_edge vs bad_zoom), anisotropic normalization correctness, None trajectory fallback.
- Added constraint tests to [emwy_tools/tests/test_tr_crop.py](emwy_tools/tests/test_tr_crop.py): containment clamp activation, double-clamp prevents re-smoothing violations, zoom constraint limits height change rate, crop position allows black fill (extends beyond frame bounds), crop size stays within frame dimensions, disabled-when-zero tests.
- Updated [tools/analyze_crop_path_stability.py](tools/analyze_crop_path_stability.py) with composition metrics columns in CSV and console comparison table: center_offset_p95, edge_margin_p05, edge_touch_count, bad_frame_fraction, bad_run_max_length, per-cause breakdowns.
- Updated [tools/batch_encode_experiment.py](tools/batch_encode_experiment.py) to Experiment 5 (virtual dolly cam): replaced axis-isolated override variants with constraint-based variants (A_old_baseline fill=0.1, B_tight_030 fill=0.3 + constraints, C_tight_040 fill=0.4 + constraints, D_tight_030_no_contain fill=0.3 only). Expanded to all 7 test videos. Added composition metrics to results table.

### Behavior or Interface Changes
- `direct_center_crop_trajectory()` now applies containment clamping and zoom constraint by default. Existing configs without the new keys get containment_radius=0.20 and max_height_change=0.005 automatically. Crop position is no longer clamped to frame bounds (black fill at edges is allowed).

### Fixes and Maintenance
- **Bug fix**: fixed negative ETA in track runner interval solver. `total_new_frames` undercounted by 1 per interval (off-by-one from inclusive seed endpoints), causing the frame counter to overshoot and produce negative ETA. Added `+ len(new_indices)` to both parallel and sequential paths in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py).
- **Bug fix**: removed hidden size-smoothing default in [emwy_tools/track_runner/tr_crop.py](emwy_tools/track_runner/tr_crop.py). When `crop_post_smooth_size_strength=0`, the code previously fell back to `alpha_pos / 2.0`, applying unwanted size smoothing. Now `alpha_size=0` truly disables size post-smoothing. This contaminated all prior experiment results where size smoothing appeared to be off but was actually running at half the position smoothing strength.

### Decisions and Failures
- The hidden size-smoothing default contaminated Experiments 1-3. All variants that set `crop_post_smooth_size_strength=0` were actually running size smoothing at `alpha_pos/2`. This explains why Experiment 2 variants all looked the same to the reviewer.
- Experiment 4 (axis isolation) produced visually indistinguishable output across all 6 variants. Root cause: `crop_fill_ratio=0.1` makes the crop 10x person height, so the subject is tiny and drifts freely. Tighter fill ratio (0.3-0.4) is the first-order fix.
- Virtual dolly cam design: subject stays centered by constraint, not by average tendency. Priority hierarchy: (1) runner in protected zone, (2) smooth camera motion, (3) smooth zoom, (4) minimize black border, (5) aggressive recenter as last resort.

## 2026-03-16

### Additions and New Features
- Created [emwy_tools/track_runner/encode_analysis.py](emwy_tools/track_runner/encode_analysis.py): pre-encode crop-path stability analysis module. Computes motion-stability metrics (2D vector center jerk, height jerk, crop size CV, quantization chatter fraction), confidence statistics, confidence-weighted instability regions with heuristic cause classification (bbox_noise, confidence_gap, smoothing_lag, size_instability), dominant symptom summary, and seed frame suggestions. Also includes solver context analysis (FWD/BWD convergence error, seed density, desert count, identity score, competitor margin). Outputs both a formatted console report and diagnostic YAML file.
- Added `analyze` subcommand to track runner CLI in [emwy_tools/track_runner/cli_args.py](emwy_tools/track_runner/cli_args.py) and [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). The analyze mode reconstructs the trajectory (same pipeline as encode: stitch, anchor, erase), computes crop rects, runs crop-path stability analysis and solver context analysis, prints a formatted console report, and writes a diagnostic YAML to `tr_config/{video}.encode_analysis.yaml`. Supports `--aspect` flag for previewing different crop aspect ratios.
- Added `default_encode_analysis_path()` to [emwy_tools/track_runner/tr_paths.py](emwy_tools/track_runner/tr_paths.py) for the diagnostic YAML output path.
- Created [emwy_tools/tests/test_encode_analysis.py](emwy_tools/tests/test_encode_analysis.py): 23 Layer 1 synthetic tests for the encode_analysis module covering constant velocity (near-zero jerk), sinusoidal oscillation (elevated jerk proportional to amplitude), step height change (jerk spike), quantization chatter detection (alternating pattern vs real motion), direction reversal (high vector jerk), confidence statistics, instability region detection, dominant symptom classification, solver context metrics, reproducibility (identical output on same input), YAML write, report formatting, smooth zoom, and edge cases (single frame, two frames, None trajectory entries).
- Created [docs/TRACK_RUNNER_ANALYZE_AND_ENCODE.md](docs/TRACK_RUNNER_ANALYZE_AND_ENCODE.md): reference documentation for the analyze subcommand and encode pipeline covering motion-stability metrics, instability region classification, quantization chatter, diagnostic YAML format, acting on diagnoses, encode pipeline overview, adaptive interpolation, available filters, and recommended presets.

- Created [docs/TRACK_RUNNER_CROP_PATH_FINDINGS.md](docs/TRACK_RUNNER_CROP_PATH_FINDINGS.md): scientific findings document from V4 crop-path stability analysis across all 7 test videos. Establishes which metrics predict visible output instability, characterizes IMG_3702 (unwatchable) and IMG_3707 (relay extreme) failure cases, identifies height_jerk_p95 as the strongest single predictor, shows quantization chatter is systemic (14-35% across all videos), and reveals that convergence error normalized by crop width separates quality tiers. Includes provisional thresholds and next steps for Layer 2/3 validation.
- Created [tools/analyze_crop_path_stability.py](tools/analyze_crop_path_stability.py): cross-video crop-path analysis script that runs encode_analysis across all test videos with solved intervals. Discovers videos from tr_config/, reconstructs trajectories, computes crop-path and solver-context metrics, outputs per-video analysis YAMLs, cross-video comparison CSV, and formatted markdown tables.
- Created [tests/analyze_benchmarks/](tests/analyze_benchmarks/): benchmark reference set with 6 metric snapshots from real video analysis: dense_refined (IMG_3830), sparse_seed (IMG_3629), telephoto_ambiguous (canon_60d), unwatchable_failure (IMG_3702), strong_zoom (IMG_3823), relay_extreme (IMG_3707). Each YAML captures summary, motion_stability, confidence, dominant_symptom, solver_context, and instability_region_count.
- Created [tools/batch_encode_experiment.py](tools/batch_encode_experiment.py): batch encode experiment script for overnight variant comparison. Encodes 6 single-knob-isolated config variants (A baseline, B no filters, C center smoothing only, D size smoothing only, E velocity cap only, F combined) for IMG_3702 (failure case) and IMG_3830 (control). Each variant changes exactly one parameter to isolate its effect: if zoom pumping improves only with size smoothing (D), that identifies the mechanism. Extracts 15-second clips around worst instability regions, runs analysis on each variant, and produces `output_smoke/experiment/results.md` comparison table plus per-variant analysis YAMLs. Key finding from setup: `crop_post_smooth_size_strength` defaults to 0.0, meaning zoom pumping passes through the crop controller completely unfiltered.
- Track runner startup now prints the analysis YAML file path when it exists (e.g. `analysis: .../tr_config/video.encode_analysis.yaml`), providing diagnostic awareness alongside the config, seeds, diagnostics, and intervals paths.

### Behavior or Interface Changes
- Changed interpolation method in [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py) from static selection (LANCZOS4 when filters active, LINEAR otherwise) to adaptive per-frame selection based on scale direction: `cv2.INTER_AREA` for downscaling (avoids aliasing shimmer on high-frequency textures), `cv2.INTER_LANCZOS4` for upscaling (preserves detail). Applied in both sequential (`encode_cropped_video`) and parallel (`_encode_segment`) encode paths. This is a correctness fix: INTER_AREA is the proper method for pixel decimation per OpenCV documentation.

### Fixes and Maintenance
- Updated [docs/TRACK_RUNNER_ANALYZE_AND_ENCODE.md](docs/TRACK_RUNNER_ANALYZE_AND_ENCODE.md) to align with V4 empirical findings: corrected metric interpretation to note height_jerk_p95 is the strongest watchability predictor, center_jerk alone is not sufficient, chatter is systemic (14-35% across all videos), convergence should be normalized by crop width, and seed density alone does not prevent instability. Replaced fabricated YAML example with real IMG_3830 analysis output. Updated presets with findings-informed thresholds.
- Fixed `analyze_solver_context()` in [emwy_tools/track_runner/encode_analysis.py](emwy_tools/track_runner/encode_analysis.py) to read interval scores from the correct data structure. The real intervals format stores `identity_score`, `competitor_margin`, and `meeting_point_error` (list of per-frame `center_err_px` dicts) inside the `interval_score` dict, not a `diagnostics` dict. Initial implementation returned all zeros for solver context metrics; now correctly extracts convergence error, identity score, and competitor margin.

## 2026-03-15

### Additions and New Features
- Added quit-chain tracing to track runner for debugging Q-quit failures. New `QUIT_TRACE` flag in [emwy_tools/track_runner/key_input.py](emwy_tools/track_runner/key_input.py) enables timestamped boundary markers (KEY_POLL, KEY_HANDLE, MAIN_LOOP, WAIT_ENTER/WAIT_EXIT, POOL_KILL_START/DONE, ENCODE_WAIT, FUNCTION_RETURN) with PID. Enabled automatically when `-d` debug flag is set.
- Replaced blocking `future.result()` loop in `encode_cropped_video_parallel()` with `concurrent.futures.wait()` polling that checks keyboard input and quit flag. This is a prerequisite for encode Q-quit to be observable at all -- previously the parallel encode path could not respond to Q because the main thread was blocked. Note: manual `f.done()` polling does not work reliably with `ProcessPoolExecutor`; `concurrent.futures.wait()` uses internal condition variables and is the correct approach.
- Wired `run_control` and `key_reader_obj` through to `encode_cropped_video_parallel()` from [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), enabling Q-quit during parallel encoding.
- Added `_force_kill_pool()` per-worker join and trace logging: each worker is joined with a 2s timeout and its alive/exitcode state is logged via POOL_KILL_DONE markers.
- Created three diagnostic test scripts for isolating quit-chain failure points: `_temp_test_quit_input.py` (Test A: input path), `_temp_test_quit_loop.py` (Test B: main-loop responsiveness), `_temp_test_quit_procs.py` (Test C: process tree shutdown).

### Fixes and Maintenance
- Fixed encode parallel polling loop hanging forever after workers complete. Manual `f.done()` polling never detected completion; replaced with `concurrent.futures.wait(timeout=0.2)` which uses proper internal condition variables.
- Fixed `RuntimeError: dictionary changed size during iteration` in `_force_kill_pool()`: snapshot `pool._processes.values()` into a list before iterating, avoiding race with the management thread.
- Fixed encode Q-quit causing `ffmpeg mux failed: No such file or directory` crash. After quit-interrupted parallel encode, cli.py now returns early and skips mux/finalize steps.
- Reduced ENCODE_WAIT heartbeat from every 0.2s to every ~6s to avoid drowning out worker progress bars.

- Created [docs/TRACK_RUNNER_YAML_CONFIG.md](docs/TRACK_RUNNER_YAML_CONFIG.md): reference documentation for the track runner YAML config file covering detection, crop modes, smoothing tuning, encode filters, CLI overrides, and recommended presets for handheld vs tripod footage.
- Created [emwy_tools/track_runner/tr_paths.py](emwy_tools/track_runner/tr_paths.py): centralized path construction for track_runner config and state files. All data files now default to `./tr_config/` subdirectory under cwd instead of next to the input video. Encoded output stays next to the source video. The `tr_config/` directory is auto-created on first run and can be replaced with a symlink to a network drive.
- Created [emwy_tools/track_runner/tr_video_identity.py](emwy_tools/track_runner/tr_video_identity.py): video identity fingerprinting module. Builds metadata-based identity blocks (basename, size, resolution, fps, frame count, duration) and compares stored vs current identity with tolerant matching (fps within 0.01, duration within 0.5s). Mismatches produce warnings, not errors.
- All data file writes (seeds, diagnostics, intervals) now include a `video_identity` block for mismatch detection when loading files created for a different video.
- Track runner now prints full absolute paths for config, seeds, diagnostics, and intervals files at startup.
- Created [emwy_tools/tests/test_tr_paths.py](emwy_tools/tests/test_tr_paths.py): 11 tests covering path construction, basename extraction, directory creation, and output path preservation.
- Created [emwy_tools/tests/test_tr_video_identity.py](emwy_tools/tests/test_tr_video_identity.py): 14 tests covering identity construction, exact and tolerant field comparison, missing fields, and multiple mismatches.

### Behavior or Interface Changes
- **Storage policy change**: track_runner config YAML and state JSON files now default to `./tr_config/` subdirectory instead of next to the input video. This separates small metadata files (suitable for network drives/backup) from large video files (on fast local SSD). Existing files next to videos still work when pointed to explicitly with `-c` flag.
- Removed `default_seeds_path()`, `default_diagnostics_path()`, and `default_intervals_path()` from [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py). Removed `default_config_path()` from [emwy_tools/track_runner/tr_config.py](emwy_tools/track_runner/tr_config.py). All path construction now lives in [emwy_tools/track_runner/tr_paths.py](emwy_tools/track_runner/tr_paths.py).

### Behavior or Interface Changes
- Changed scrub step sizes in seed mode from fixed time presets (`[0.1, 0.2, 0.5, 1.0, 2.0, 5.0]` seconds) to frame-based halve/double logic with `[`/`]` keys. Internal representation is now frame counts (floor 1 frame, ceiling fps*10). Default step changed from 0.2s (~6 frames) to 2 frames. Display shows both frames and seconds (e.g. `2f (0.07s)`).
- Auto-centering in zoomed view now targets the REFINED (fused) prediction box when available, falling back to FWD/BWD average. Previously always used FWD/BWD average. Affects `_get_prediction_center()` in [emwy_tools/track_runner/ui/base_controller.py](emwy_tools/track_runner/ui/base_controller.py).
- Arrow keys now have consistent behavior regardless of zoom level: plain LEFT/RIGHT always pan (no-op at fit-zoom), Shift+LEFT/RIGHT always do time navigation (frame scrub in seed mode, seed navigation in edit mode). Previously arrow keys changed meaning based on zoom level, which was confusing. Updated in [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py) and [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py).
- Updated [docs/TRACK_RUNNER_KEYBINDINGS.md](docs/TRACK_RUNNER_KEYBINDINGS.md) to document consistent arrow key behavior.

### Additions and New Features
- Created [emwy_tools/track_runner/key_input.py](emwy_tools/track_runner/key_input.py): keyboard input and signal handling module for interactive controls during `solve`, `refine`, and `encode` modes. Provides `RunControl` flag object, `KeyInputReader` context manager for non-blocking cbreak-mode key detection, `GracefulQuit` exception, and `install_sigint_handler()` for graceful Ctrl-C handling.
- Added keyboard controls to track runner solve and encode modes: press Q to quit after the current interval (progress saved to disk), P to pause/resume, Ctrl-C for graceful quit with clean message instead of traceback. Second Ctrl-C force-quits. Startup hint `(press Q to quit, P to pause)` printed before solve and encode.
- Created [tests/test_key_input.py](tests/test_key_input.py): 14 pytest tests covering `RunControl` flag logic, `GracefulQuit` exception propagation, `KeyInputReader` non-TTY fallback, `handle_key` quit/pause behavior, and `install_sigint_handler` first/second Ctrl-C behavior.

### Behavior or Interface Changes
- Improved track runner progress bars in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) and [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py): replaced thin line-drawing bar with block characters (full-block/light-shade), added dynamic terminal width expansion via `__rich_measure__`, and switched elapsed-time counters to ETA countdown displays.
- Added `BlockBarColumn` and `FrameETAColumn` classes in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) for reusable wide block-character progress bars and frame-throughput-based ETA estimation. `FrameETAColumn` supports both `multiprocessing.Value` (parallel) and list wrapper (sequential) counters.
- `FrameETAColumn` now throttles updates to once per 2 seconds and shows both ETA and elapsed time (e.g. `ETA 3:42  elapsed 1:15`).
- `BlockBarColumn` progress bar now expands to fill available terminal width instead of using a fixed 40-character width.
- Parallel solve wall-time log now includes total frame count and ETA in the periodic status line.

### Fixes and Maintenance
- Fixed ~50 second exit delay after Q-quit in parallel solve: added `_force_kill_pool()` helper that kills worker processes and deregisters the executor's management thread from both `concurrent.futures.process._python_exit` (atexit handler) and `threading._shutdown_locks` (interpreter shutdown). Both hooks block at exit by joining the non-daemon management thread.
- Fixed `CancelledError` crash when pressing Q during parallel solve: cancelled futures are now skipped instead of calling `.result()` on them.
- Fixed slow quit in parallel solve mode: `pool.shutdown(wait=False, cancel_futures=True)` is now called immediately on Q-quit instead of waiting for in-progress workers to finish.
- `solve` mode now resumes from saved intervals when the prior solve was interrupted instead of always clearing and starting over. A `solve_complete` flag in the intervals file tracks whether the last solve finished; only a completed solve triggers a full re-solve on the next run.
- Fixed Q keypress leaking to the shell prompt after exit: `KeyInputReader` now flushes stdin with `termios.tcflush()` before restoring terminal settings.
- Progress bar no longer jumps to 100% when solve is interrupted mid-run.
- Quit summary now includes elapsed time since Q was pressed (e.g. `quit took 0.3s`).

## 2026-03-13

### Additions and New Features
- Created [emwy_tools/track_runner/box_utils.py](emwy_tools/track_runner/box_utils.py): shared geometric helpers `center_to_corners`, `clamp_box_to_frame`, `compute_iou`, and `draw_transparent_rect` extracted from duplicated inline patterns across the track runner package.
- Created [tests/test_state_io_roundtrip.py](tests/test_state_io_roundtrip.py): pytest-based round-trip tests for [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) covering seeds, diagnostics, intervals, and fingerprint generation. Migrated self-test logic from `__main__` block.
- Created [emwy_tools/track_runner/cli_args.py](emwy_tools/track_runner/cli_args.py): argparse setup functions extracted from [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Includes `parse_args()`, `_add_seed_interval_arg()`, `_add_severity_arg()`, and `_add_encode_args()`. Separates CLI argument configuration from CLI orchestration logic.
- Created [emwy_tools/track_runner/video_io.py](emwy_tools/track_runner/video_io.py): extracted `VideoReader` and `VideoWriter` classes from [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py). Self-contained I/O module with no dependency on encoding logic. Updated callers in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) and [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) to import from `video_io` directly.
- Created [emwy_tools/track_runner/seed_color.py](emwy_tools/track_runner/seed_color.py): extracted color extraction and seed candidate functions from [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py). Includes `_clamp_box()`, `extract_jersey_color()`, `extract_color_histogram()`, `detection_to_torso_box()`, `suggest_seed_candidates()`, `normalize_seed_box()`, and `_build_seed_dict()`. Updated callers in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py), [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py), and [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py).
- Split monolithic `emwy_tools/tests/test_track_runner.py` (2527 lines) into 9 focused test files with `tr_` prefix: `test_tr_state_io.py`, `test_tr_config.py`, `test_tr_scoring.py`, `test_tr_propagator.py`, `test_tr_hypothesis.py`, `test_tr_review.py`, `test_tr_crop.py`, `test_tr_encoder.py`, `test_tr_interval_solver.py`. Shared test helpers moved to [emwy_tools/tests/tr_test_helpers.py](emwy_tools/tests/tr_test_helpers.py).

### Fixes and Maintenance
- Replaced inline bbox clamping patterns in [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py) (3 sites), [emwy_tools/track_runner/hypothesis.py](emwy_tools/track_runner/hypothesis.py) (2 sites) with `box_utils.clamp_box_to_frame()` calls.
- Replaced duplicated `_compute_iou()` in [emwy_tools/track_runner/hypothesis.py](emwy_tools/track_runner/hypothesis.py) with shared `box_utils.compute_iou()`.
- Updated `_compute_dice_coefficient()` in [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py) to use `box_utils.center_to_corners()` for coordinate conversion.
- Replaced 4 transparent rectangle drawing blocks in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py) with `box_utils.draw_transparent_rect()` calls.
- Extracted `read_video_metadata()` helper in [emwy_tools/track_runner/tr_config.py](emwy_tools/track_runner/tr_config.py), updated 3 call sites in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) and [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py).
- Extracted `_load_json_with_header()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) to deduplicate JSON loading boilerplate across `load_seeds`, `load_diagnostics`, and `load_intervals`.
- Fixed import ordering in [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py): moved `rich.progress` from local repo modules to PIP3 section, removed duplicate comment block.
- Fixed import ordering in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py): removed empty Standard Library section and duplicate local repo modules comment block.
- Removed bare `return` statements from void functions in [emwy_tools/track_runner/tr_config.py](emwy_tools/track_runner/tr_config.py) and [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py).
- Removed `if __name__ == "__main__"` self-test block from [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py): tests moved to [tests/test_state_io_roundtrip.py](tests/test_state_io_roundtrip.py).

### Additions and New Features
- Added `-S`/`--start` argument to interactive track runner modes (seed, edit, target) in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py): accepts a start time in seconds and seeks the UI to that position on launch. Seed and target modes seek to the nearest candidate frame; edit mode seeks to the nearest seed at or after the given time. Wired through [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py), [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py), [emwy_tools/track_runner/ui/target_controller.py](emwy_tools/track_runner/ui/target_controller.py), and [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py).

- Created [docs/TRACK_RUNNER_KEYBINDINGS.md](docs/TRACK_RUNNER_KEYBINDINGS.md): comprehensive keybinding reference for all track runner annotation modes (seed, target, edit), including common keys, mouse/trackpad input, zoom behavior, draw modes, toolbar buttons, and polish workflow.
- Added trackpad pan support in [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py): two-finger trackpad swipes now pan the image instead of zooming. Uses `event.phase()` and `event.hasPixelDelta()` to distinguish macOS trackpad events (pan) from mouse scroll wheel (zoom). Expands scene rect with pan margin on first trackpad gesture so scroll bars have range even at fit-to-view zoom. `fit_to_view()` resets scene rect to image bounds before fitting.
- Added zoom controls widget in [emwy_tools/track_runner/ui/zoom_controls.py](emwy_tools/track_runner/ui/zoom_controls.py): status bar widget with +/- buttons, percentage label, Fit button, and horizontal slider (10%-3000%). Bidirectionally synced with `FrameView` zoom via `zoom_changed` signal.
- Added `zoom_changed` signal to `FrameView` in [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py): emitted on wheel zoom, `set_zoom()`, and `fit_to_view()` with zoom percentage.
- Integrated zoom controls into `AnnotationWindow` status bar in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py), left of the progress bar.
- Added forward-backward LK flow consistency check in [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py): after forward optical flow, runs backward LK and rejects points with round-trip error > 1.0 pixel. Standard CV hygiene that reduces jitter from bad flow vectors.
- Added HSV histogram-based identity scoring in [emwy_tools/track_runner/hypothesis.py](emwy_tools/track_runner/hypothesis.py): `compute_identity_score()` uses `cv2.compareHist(HISTCMP_BHATTACHARYYA)` for runners >60px, blended 60/40 with template correlation. Falls back to mean-HSV for 30-60px and returns neutral 0.5 below 30px. Size thresholds validated against [docs/archive/SEED_VARIABILITY_FINDINGS.md](docs/archive/SEED_VARIABILITY_FINDINGS.md) empirical data.
- Added 2D HS histogram computation in `build_appearance_model()` in [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py). Stored as `hs_histogram` key for identity scoring. Sparse histograms (<50 non-zero bins) trigger mean-HSV fallback.
- Added velocity-adaptive crop cap in [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py): `CropController` now adapts velocity cap based on subject displacement EMA (`cap = max(base_cap, velocity_scale * ema_displacement)`). Fast runners get a higher cap so the crop keeps up. Config keys: `crop_velocity_scale` (default 2.0), `crop_displacement_alpha` (default 0.1).
- Added YOLO-guided auto-seed suggestion in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py): `suggest_seed_candidates()` ranks YOLO detections by Bhattacharyya histogram similarity to confirmed seeds. Single detection auto-highlights. Multi-detection auto-highlights only when best score < 0.5 AND margin > 0.15. First frame always requires explicit selection.
- Added accept/reject seed interaction in [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py): ENTER accepts auto-suggested seed, number keys 1-9 override to select a different candidate, manual draw overrides entirely. Status bar shows "ENTER=accept" when suggestion available.
- Added occlusion-risk flagging in [emwy_tools/track_runner/hypothesis.py](emwy_tools/track_runner/hypothesis.py): `compute_occlusion_risk()` sets `occlusion_risk=True` when any detection overlaps the target with IoU >= 0.15 (excluding the target itself at IoU >= 0.3). Diagnostic signal only, does not change blending weights.
- Added occlusion integration in [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py): `identify_weak_spans()` adds `likely_occlusion` failure reason for intervals with occlusion frames. Generates seed suggestions at occlusion exit frames (first frame after occlusion drops). Promotes severity to high when occlusion + low agreement co-occur.
- Added detection caching in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py): `solve_interval()` accepts optional `detection_cache` dict and stores `{frame_index: [detection_dicts]}` in the result. Cached detections skip YOLO inference on re-solve, reducing refinement cost.
- Added occlusion_risk propagation through `fuse_tracks()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py): OR-combines forward and backward occlusion flags per frame.
- Created [tests/test_track_runner.py](tests/test_track_runner.py): 22 tests covering all 8 CV enhancement work packages (flow consistency, histogram identity scoring, velocity-adaptive crop, seed suggestion, occlusion flagging, review occlusion integration, detection caching, fuse_tracks occlusion propagation).
- Added `direct_center` crop mode to [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py): centers the crop directly on the dense solved trajectory center, then smooths offline with forward-backward EMA. Pure offline signal processing with no deadband, no attack/release alpha, no online state. Recommended for telephoto footage where the operator already kept the runner roughly centered.
- Added `crop_mode` dispatch in `trajectory_to_crop_rects()`: reads `crop_mode` from config (`smooth` default, `direct_center` opt-in). Invalid modes raise `RuntimeError`. Malformed trajectory entries raise `RuntimeError` before dispatch.
- Updated telephoto config preset [TRACK_VIDEOS/canon_60d_600m_zoom.MP4.track_runner.config.yaml](TRACK_VIDEOS/canon_60d_600m_zoom.MP4.track_runner.config.yaml) to use `crop_mode: direct_center`.
- Documented direct-center crop mode pipeline and `crop_mode` parameter in [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md).
- Added 11 direct-center crop mode tests covering basic centering, smoothing, bounds clamping, velocity cap, reclamp, empty trajectory, min size guard, invalid mode, steady motion, default dispatch, and malformed trajectory.
- Enabled anti-aliasing render hints (Antialiasing, SmoothPixmapTransform, TextAntialiasing) on `FrameView` in [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py). Overlay edges and text now render smooth.
- Set cosmetic pens on `RectItem` and `PreviewBoxItem` in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py). Overlay line width stays constant regardless of zoom level.
- Added `fonts`, `theme`, and `severity` sections to [emwy_tools/track_runner/overlay_styles.yaml](emwy_tools/track_runner/overlay_styles.yaml). Fonts define UI and mono family fallback chains with configurable sizes. Theme defines dark UI depth colors. Severity defines color-coded badges for HIGH/MED/LOW interval quality.
- Added font accessor functions (`get_ui_font_family()`, `get_mono_font_family()`, `get_overlay_font_size()`, `get_status_font_size()`), theme color accessor (`get_theme_color()`), and severity style accessor (`get_severity_style()`) to [emwy_tools/track_runner/overlay_config.py](emwy_tools/track_runner/overlay_config.py). Font resolution probes `QFontDatabase.hasFamily()` per candidate and falls back gracefully.
- Applied consistent mono font family to all overlay labels (`RectItem`, `ScaleBarItem`, `PredictionLegendItem`) in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py) and `StatusPresenter` in [emwy_tools/track_runner/ui/status_presenter.py](emwy_tools/track_runner/ui/status_presenter.py). Set app-wide UI font with no-hinting for Retina clarity in [emwy_tools/track_runner/ui/theme.py](emwy_tools/track_runner/ui/theme.py).
- Expanded dark theme QSS in [emwy_tools/track_runner/ui/theme.py](emwy_tools/track_runner/ui/theme.py): toolbar depth separation via `border-bottom`, button rounded corners with hover/pressed/checked states, status bar top border. All colors loaded from `overlay_styles.yaml` theme section.
- Added `QProgressBar` to `AnnotationWindow` status bar in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py). Shows N/M progress with mode-colored fill. Wired `SeedController` and `EditController` to call `set_progress()` on frame advance. Resets on controller swap.
- Added severity badge and reason display to `StatusPresenter.update()` in [emwy_tools/track_runner/ui/status_presenter.py](emwy_tools/track_runner/ui/status_presenter.py). Edit mode now shows color-coded severity (red HIGH, amber MED, green LOW) with compact reason text (low agree, competitor, id swap). `EditController` passes `interval_info` from predictions dict.
- Created `KeyHintOverlay` in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py): persistent semi-transparent hint strip at bottom of frame view showing mode label and keybinding hints. Always visible, no auto-hide. Created during controller activation in `BaseAnnotationController`. Each controller implements `_get_keybinding_hints()` and `_get_mode_name()`.
- Added `V` key prediction peek-suppression in [emwy_tools/track_runner/ui/base_controller.py](emwy_tools/track_runner/ui/base_controller.py). Temporarily hides FWD/BWD/REFINED/AVG/legend overlays for the current frame. Auto-restores on frame advance. Seed box, scale bar, and key hints remain visible.
- Added per-overlay visibility toggles via checkable toolbar actions in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py) and [emwy_tools/track_runner/ui/base_controller.py](emwy_tools/track_runner/ui/base_controller.py). Color-coded swatch icons for FWD, BWD, REFINED, AVG, and Legend. Three-layer visibility model: available AND user_enabled AND NOT temporary_suppressed. Toggles reset to all-visible on mode switch.
- Created [tools/analyze_track_runner_json.py](tools/analyze_track_runner_json.py): v3 JSON-era analysis script that reads seeds, intervals, and diagnostics JSON files from `TRACK_VIDEOS/` and produces a text report, per-video CSVs, and a summary JSON in `output_smoke/`. Covers 16 metric categories: seed coverage, seeding modes, torso area variability, position range, jersey HSV by size bin, gap analysis, interval statistics, confidence breakdown, failure reasons, score distributions, meeting point error, fused track quality, diagnostics tiers, and cross-video comparisons.
- Created [docs/archive/TRACK_RUNNER_V3_FINDINGS.md](docs/archive/TRACK_RUNNER_V3_FINDINGS.md): empirical findings from v3 track runner data across three videos (IMG_3629, IMG_3830, canon_60d_600m_zoom). Key findings: seed density is the primary driver of low-confidence prevention (674/min achieves 1.7% low vs 14.3% at 44.5/min), appearance identity scoring is the main telephoto bottleneck (median identity 0.39, 61% weak_appearance), competitor margin strongly discriminates easy vs hard videos (median 1.0 vs 0.27).

### Removals and Deprecations
- Removed `run` subcommand from the track runner CLI in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py): the 290-line `_mode_run()` function conditionally ran seed, solve, refine (with interactive prompts), and encode as one kitchen-drawer command. The actual workflow is non-linear and each step is driven manually via its own subcommand. `run` was never used. Bare invocation now prints help and exits instead of defaulting to `run`. Removed run-only flags: `--refine`, `--gap-threshold`, `--ignore-diagnostics`, `--no-interactive-refine`. Updated [docs/TOOLS.md](docs/TOOLS.md) example to use an explicit subcommand.
- Removed `tools/measure_seed_variability.py` and `tools/plot_seed_variability.py`: replaced by [tools/analyze_track_runner_json.py](tools/analyze_track_runner_json.py) which reads v3 JSON data instead of YAML seeds. Historical measurements preserved in [docs/archive/SEED_VARIABILITY_FINDINGS.md](docs/archive/SEED_VARIABILITY_FINDINGS.md).
- Updated [docs/FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md) tools listing to reflect script replacement.

### Fixes and Maintenance
- Improved overlay box visibility in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py): added dark contrast outline behind colored borders on both `RectItem` and `PreviewBoxItem`. Increased base border thickness to 2px cosmetic. Boxes are now visible against any background (dark, light, or matching the box color). Removed DPI-division logic that made borders sub-pixel on Retina displays.
- Fixed `setTextFormat` crash in edit mode in [emwy_tools/track_runner/ui/status_presenter.py](emwy_tools/track_runner/ui/status_presenter.py): PySide6 requires `Qt.TextFormat.RichText` / `Qt.TextFormat.PlainText` enum values, not raw ints `1` / `0`.
- Fixed `cv2.cvtColor` crash when drawing a box that extends outside the frame in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py): added `_clamp_box()` helper that clamps box coordinates to frame bounds. `extract_jersey_color()` returns `(0, 0, 0)` and `extract_color_histogram()` returns a zero histogram for out-of-bounds regions instead of crashing.
- Limited trackpad pan range in [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py): scene rect pan margin set to 2% of image size on each side. Keeps image on screen while giving scroll bars enough range to pan.
- Fixed image shift when pressing P (partial mode) or A (approx mode) in [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py): changed `resizeAnchor` from `AnchorUnderMouse` to `AnchorViewCenter`. Status bar stylesheet changes (mode badge) caused a resize event on the FrameView, and `AnchorUnderMouse` shifted the view based on the cursor position during the internal layout change.
- Suppressed per-interval `[PRIOR]` output lines in refine mode in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py). Previously every reused interval printed its own line (388 lines on a typical video), flooding the terminal before newly-solved intervals appeared. Now only the summary count line is printed; `on_interval_complete` callbacks still fire for prior results.
- Replaced `TimeRemainingColumn` with `TimeElapsedColumn` in all three Rich progress bars in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py). The ETA column always showed `-:--:--` because parallel interval completions are bursty and Rich cannot estimate remaining time reliably. Elapsed time is always accurate and more useful alongside the wall-time throughput lines.
- Fixed `ndarray is not JSON serializable` crash when saving seeds in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py): `_build_seed_dict()` now calls `.tolist()` on the histogram before storing it in the seed dict. Previously the raw numpy array was stored, causing `json.dump()` to fail on every save. This also caused frame advance to stall after drawing a box (the save exception prevented `_advance()` from executing).
- Fixed `AttributeError: 'AnnotationWindow' object has no attribute '_progress_bar'` at startup in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py): `setChecked(True)` on the initial mode action fires `_on_mode_changed` -> `set_controller(None)` before `_progress_bar` is created. Added `hasattr` guard on progress bar access in `set_controller()`.
- Renamed colliding module filenames across sub-packages to prevent `sys.path` shadowing: `crop.py` -> `tr_crop.py` / `sb_crop.py`, `config.py` -> `tr_config.py` / `sa_config.py` / `sb_config.py`, `detection.py` -> `tr_detection.py` / `sa_detection.py`. Updated all imports in `cli.py`, `encoder.py`, `interval_solver.py`, `seed_controller.py`, `edit_controller.py`, `stabilize_building.py`, `stabilize.py`, `silence_annotator.py`, `sa_config.py`, and test files. Prevents wrong-module import when conftest adds multiple sub-package dirs to `sys.path`.

### Behavior or Interface Changes
- Improved CLI help text in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py): added epilog to main parser clarifying that global options must appear before the subcommand, and updated `--time-range` help string to note it is a global option.
- Added `-I` short flag for `--seed-interval` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) on seed and target subparsers. Example: `track_runner.py -i VIDEO seed -I 10`.
- Factored repeated subcommand args in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) into helpers: `_add_seed_interval_arg()`, `_add_severity_arg()`, `_add_encode_args()`. Each shared arg group is now defined once and called where needed, reducing inline duplication across seed, edit, target, and encode subparsers.
- Default display filter changed from `none` to `bilateral+clahe` in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py). Bilateral filter preserves edges while smoothing noise, better default for annotation work.
- Default zoom changed from 1:1 pixel mapping to fit-to-window in [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py). Large videos (e.g. 2816x1584) now show the full frame on launch instead of cropping to the top-left corner. Added `fit_to_view()` method with recursion guard, `showEvent()`/`resizeEvent()` overrides for deferred initial fit and resize refit. Min zoom lowered to 0.1, max zoom raised to 30.0.
- Zoom cycle (Z key) expanded from 4 levels to 8 in [emwy_tools/track_runner/ui/base_controller.py](emwy_tools/track_runner/ui/base_controller.py): fit -> 1x -> 1.5x -> 2.25x -> 3.375x -> 5x -> 8x -> 12x -> fit. Higher levels enable pixel-level annotation on large frames.
- Frame view border reduced from 3px solid to 2px top-only accent in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py). Mode button accent is now the primary mode indicator.
- `_get_default_status_text()` in controllers now returns a short mode summary instead of keybinding hints. Keybinding hints moved to the persistent `KeyHintOverlay` at bottom of frame view.
- `PredictionLegendItem` in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py) now uses `setPos()` for scene placement instead of `setRect()`. Fixes off-screen rendering bug where children were double-counted in coordinate space. Labels cached in `_label_items` list, eliminating fragile `childItems()` type-filtering in `reposition()`.

### Fixes and Maintenance
- Fixed widget accumulation bug in `AnnotationWindow.set_controller()` in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py). Mode label and filter button are now reused instead of recreated on every controller swap. Uses `_annotation_toolbar.clear()` with persistent widget references.
- Fixed `EditController._on_deactivated()` in [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py) to remove `StatusPresenter` widget and keybindings label from status bar on deactivation, preventing widget accumulation across mode switches.

- Added refined (fused) and consensus (FWD/BWD average) bbox overlays to track runner GUI. REFINED box (cyan solid, Z=4) shows the second-pass fused result; AVG box (amber dotted, Z=3) shows the FWD/BWD midpoint. Both render alongside existing FWD/BWD dashed overlays for visual quality assessment.
- Added `fused` and `consensus` entries to [emwy_tools/track_runner/overlay_styles.yaml](emwy_tools/track_runner/overlay_styles.yaml) predictions section. Added "dotted" as a valid line style in [emwy_tools/track_runner/overlay_config.py](emwy_tools/track_runner/overlay_config.py).
- Extended `_build_predictions_from_diagnostics()` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) to extract `fused_track` from intervals and compute consensus as average of FWD/BWD boxes.
- Added `_enforce_severity_gap()` in [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py): when severity is "high", enforces a 2-second minimum gap between target frames. Keeps the frame with worse agreement_score when two are too close. Reports dropped frame count to the user.
- Added `PredictionLegendItem` in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py): compact legend showing colored line swatches and labels for all four prediction overlays (FWD, BWD, REFINED, AVG). Automatically repositions to the corner farthest from the tracked bbox each frame. Created during controller activation when predictions are available.
- Interval quality metadata (severity, agreement, margin, failure reasons) now embedded in the predictions dict by `_build_predictions_from_diagnostics()` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Seed/target mode title bar shows severity, scores, and short failure reasons for the current frame's interval (e.g. "HIGH: agree=0.12 margin=0.08 (low agreement, identity swap)"). Added `_get_interval_quality_text()` to [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py).
- Added offline forward-backward EMA post-smoother to [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py): `_forward_backward_ema()`, `smooth_crop_trajectory()`, and `compute_crop_metrics()`. Reduces crop jitter for telephoto footage by smoothing center and size signals independently after the online crop pass.
- Added three new config keys: `crop_post_smooth_strength`, `crop_post_smooth_size_strength`, `crop_post_smooth_max_velocity`. All default to 0 (disabled) for backward compatibility.
- Added telephoto preset to [TRACK_VIDEOS/canon_60d_600m_zoom.MP4.track_runner.config.yaml](TRACK_VIDEOS/canon_60d_600m_zoom.MP4.track_runner.config.yaml) with crop post-smoothing values tuned for tight-zoom footage.
- Documented post-smoothing pipeline and telephoto preset in [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md) crop controller section.

- Extracted `BaseAnnotationController` in [emwy_tools/track_runner/ui/base_controller.py](emwy_tools/track_runner/ui/base_controller.py) from edit/seed controllers: shared event filter, mouse drawing, overlay management, zoom cycling, draw mode toggles (partial/approx), scale bar, and activation lifecycle. Eliminates ~300 lines of duplicated plumbing.
- Edit mode `U` key enters seed-add scrub mode for adding seeds at unseeded frames without leaving the edit session. ESC/Q returns to edit mode. New seeds are merged into the work list in timeline order; deleted seeds are purged on return. Added `_on_enter_add_mode()`, `_resume_from_add_mode()`, `_rebuild_filtered_indices()`, and `_restore_nav_position()` to [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py).
- `SeedController` now accepts optional `return_callback` and `start_frame` parameters for use as a sub-mode within edit mode. When `return_callback` is set, ESC/Q returns collected seeds to the caller instead of closing the window. Status bar hints update to show "ESC/q=return to edit".
- Duplicate seed detection in `SeedController._on_box_drawn()`: draws at frames that already have a seed are rejected with a status bar flash message "seed already exists at this frame".

### Behavior or Interface Changes
- `EditController` and `SeedController` now inherit from `BaseAnnotationController` instead of `QObject` directly. No change in external API.
- Edit mode `get_summary()` now includes an `"added"` count in the summary dict.
- `edit_seeds()` in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py) now passes `frame_filter` to `EditController` for use during seed list rebuilds after add-mode returns.

### Additions and New Features
- Added `torso_box` coordinate warning to the anchored interpolation section of [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md): `torso_box[0:2]` are top-left, never center coordinates. Prevents repeat of prior `_collect_anchor_knots()` bug.
- Created [emwy_tools/track_runner/overlay_styles.yaml](emwy_tools/track_runner/overlay_styles.yaml): centralized YAML palette for all track runner visual semantics (colors, line styles, opacity, thickness tiers). Covers seed status, predictions, tracking sources, workspace modes, draw mode badges, preview box, and encoder overlay blending.
- Created [emwy_tools/track_runner/overlay_config.py](emwy_tools/track_runner/overlay_config.py): loader module that reads `overlay_styles.yaml` once, caches the result, validates hex colors and opacity ranges, merges defaults into each style entry, and provides typed accessor functions for both UI hex strings and cv2 BGR tuples.
- Unified visual tokens across UI and encoder: seed visible is now `#22C55E` everywhere (was `(0,255,0)` in encoder), FWD prediction is `#EF4444` everywhere (was `(255,128,0)` in encoder), BWD prediction is `#FF00FF` everywhere (was `(0,128,255)` in encoder).

### Behavior or Interface Changes
- Encoder debug overlay colors now match UI overlay colors exactly. Previously the encoder used different BGR values from the UI hex colors for seed status, FWD predictions, and BWD predictions.
- All hardcoded color constants removed from 8 consumer files: `status_presenter.py`, `edit_controller.py`, `seed_controller.py`, `workspace.py`, `overlay_items.py`, `encoder.py`, `seeding.py`, `seed_editor.py`. Colors are now loaded from `overlay_styles.yaml` via `overlay_config`.
- Legacy cv2-based seeding and seed editor functions now use `overlay_config` for FWD/BWD prediction colors and preview box defaults instead of hardcoded BGR tuples.

### Additions and New Features
- Edit mode now auto-recenters the view on the current seed bbox when zoomed in and advancing frames (space key). Uses seed `cx`/`cy` position, falling back to FWD/BWD prediction average center for approximate/not-in-frame seeds. Added `_recenter_on_bbox()` and `_get_prediction_center()` to [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py).
- Edit mode seed rect overlay now shows for any seed that has coordinates, not just "visible"/"partial" status. The cyan SEED box is now always visible alongside the FWD/BWD prediction boxes when the seed has `cx`/`cy` values.
- Overlay box line thickness now scales with display DPI in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py). Pen width is divided by the device pixel ratio so lines appear the same physical size on Retina and standard displays.
- Reduced overlay box fill opacity from ~15% to ~6% across all `RectItem` overlays (SEED, FWD, BWD) for a much more transparent look that doesn't obscure the video frame.
- FWD/BWD prediction boxes now use dashed lines to visually distinguish them from the authoritative seed box. Seed box uses solid lines at 1.5x thickness. FWD/BWD render on top (z=5) so dashed lines are not hidden by the thicker seed box (z=1). Added `dashed` and `thickness_scale` parameters to `RectItem` in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py).
- Seed box in edit mode is now color-coded by status type: green for visible, amber for partial, orange for approximate/obstructed, gray for not_in_frame. Label shows status (e.g. "SEED (partial)"). Seed box thickness increased from 1.5x to 2x.
- Edit mode keybinding hints now shown as a permanent label on the right side of the status bar (gray monospace text) instead of appended to the window title. Keybindings stay visible at all times without cluttering the title bar. Fixed misleading "L=prev" label (was actually Left arrow key).
- Added jump navigation to edit mode: `]`/`[` jump forward/backward 10% of filtered seed list, `L` jumps to next low-confidence seed (score < 0.5, wraps around). Keybinding label updated to show new keys.
- Debug overlay accepted box now colored by tracking source type (seed=green-teal, propagated=yellow-orange, merged=cyan-blue, unknown=dark red) instead of always solid green, using `_source_color()` in [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py).
- Debug overlay shows both refined (solid, source-colored) and raw pre-anchor (dashed gray) tracking positions. Raw trajectory is saved before `anchor_to_seeds()` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) and passed as `raw_box` in debug state. On seed frames the boxes overlap; on propagated frames, divergence reveals anchor correction magnitude.

### Additions and New Features
- Created [docs/TRACK_RUNNER_DESIGN.md](docs/TRACK_RUNNER_DESIGN.md): design philosophy document covering core principles (human identity / machine geometry), signal hierarchy, dual scoring, separation of concerns, annotation UI principles, and trajectory erasure philosophy.
- Created [docs/TRACK_RUNNER_HISTORY.md](docs/TRACK_RUNNER_HISTORY.md): evolution timeline from v1 Kalman-based tracker through v2 interval solver to v3 PySide6 UI. Preserves key design decisions and rationale extracted from implementation plans.

### Behavior or Interface Changes
- Archived superseded track runner specs to `docs/archive/` via `git mv`: [docs/archive/TRACK_RUNNER_TOOL_PLAN.md](docs/archive/TRACK_RUNNER_TOOL_PLAN.md) (v1 plan), [docs/archive/TRACK_RUNNER_SPEC.md](docs/archive/TRACK_RUNNER_SPEC.md) (v1 as-built), [docs/archive/TRACK_RUNNER_V2_SPEC.md](docs/archive/TRACK_RUNNER_V2_SPEC.md) (v2 spec), [docs/archive/SEED_VARIABILITY_FINDINGS.md](docs/archive/SEED_VARIABILITY_FINDINGS.md) (measurement study).
- Rewrote [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md) to match the current codebase: added all 25 modules (including `common_tools/`), all 7 CLI subcommands, all 9 seed modes, propagator details (optical flow + patch correlation, stationary lock), hypothesis competitor tracking, cyclical prior detection, encode filter pipeline, post-fuse refinement, multi-seed anchored interpolation, and complete key constants table.
- Updated terminology throughout docs: drawing mode name "approx" is now "approximate" for clarity; "absence erasure" replaced with "trajectory erasure".

### Fixes and Maintenance
- Fixed debug overlay bounding box offset in `track_runner encode --debug`: box was shifted up and to the left by approximately `(-w/2, -h/2)` pixels relative to the runner's actual position. Root cause: `_collect_anchor_knots()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) read `torso_box[0]`, `torso_box[1]` as center coordinates, but `torso_box` stores `[x, y, w, h]` (top-left corner). Fix: use seed's `cx`/`cy` keys directly, with fallback conversion from `torso_box` when those keys are absent.
- Fixed seed frames showing wrong color in debug overlay: visible and partial seed frames appeared cyan (the "merged" tracking source color) instead of their seed_status colors (green for visible, amber for partial). The fuse step overwrites `source` to "merged" for all frames. Fix: `anchor_to_seeds()` now restores `source="seed"` and `seed_status` on visible and partial seed frames so the color system routes to the `seed_status` palette.
- Fixed test helper `_make_seed()` in [emwy_tools/tests/test_track_runner.py](emwy_tools/tests/test_track_runner.py): was storing center coords in `torso_box` (should be top-left). Now correctly computes `torso_box = [cx - w/2, cy - h/2, w, h]` and includes `cx`, `cy`, `w`, `h` top-level keys matching real seed format.
- Fixed test `test_trajectory_erasure_all_drawing_modes`: approximate seed test data was missing `cx`/`cy` keys causing KeyError, and assertion expected `None` for erased approximate frames when the code correctly fills them with an `approx_seed_hint` dict.
- Clarified `torso_box` coordinate convention in [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md): explicitly documented as `[x, y, w, h]` (top-left corner), not center. Added `cx`, `cy`, `w`, `h` fields to the seed JSON example and noted that code must use `cx`/`cy` for center coordinates, never `torso_box[0]`/`torso_box[1]`.
- Fixed `load_diagnostics()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) crashing with `TypeError` when `intervals` list contains non-dict entries. The score reconstruction loop now skips non-dict items. Also fixed `test_state_io_diagnostics_round_trip` to use realistic interval dicts that exercise the score reconstruction path.
- Fixed stale comment in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py):1157: changed "absence erasure" to "trajectory erasure" to match the renamed function `_apply_trajectory_erasure()`.
- Fixed partial seed frames losing color identity: `_apply_trajectory_erasure()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) blindly overwrote all frames within erasure radius, including visible/partial seed frames that `anchor_to_seeds()` had already pinned. Fix: builds a `protected_frames` set of visible/partial seed frame indices and skips them during erasure.
- Added FWD/BWD projection boxes to debug encode overlay: stitches `forward_track` and `backward_track` from solved intervals in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), passes them as `forward_box`/`backward_box` in debug states. Encoder's `draw_debug_overlay_cropped()` in [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py) now falls back to `state` dict for FWD/BWD boxes when `debug_state` parameter is not provided.

### Additions and New Features
- Added optional `output_resolution` config key under `processing` in track_runner: `[width, height]` list that controls final output dimensions independently of the crop window. When absent, output resolution defaults to the median of all crop rectangle dimensions (previously used first-frame dimensions).
- Debug overlay seed boxes now distinguished by annotation status: visible=bright green, partial=yellow, approximate=orange. `seed_status` field added to propagator `make_seed_state()` and carried through interval solver and CLI debug states. Non-seed sources: detection=green-teal, propagated=orange, hold_last=red-orange, fallback=dark orange, merged=cyan. Previously all seed types (including `human`) were either unmapped or shared one color. Source text label now shows status for seeds, e.g. `src:human(partial)`.
- Debug overlay now shows a small filled dot at the computed box center for drift diagnosis.
- Debug overlay shows coordinate diagnostic text on the first 10 frames (bottom-right): box center, crop rect, output size, and mapped corner. Also prints diagnostic values to stdout for the first 5 frames (both sequential and parallel encoder paths). Temporary diagnostics for investigating the constant box offset bug.

### Behavior or Interface Changes
- Fixed `crop_fill_ratio` being overridden by tiered adaptive fill system for all practical bounding box heights. The user's configured fill ratio is now always used directly. A setting of 0.10 now produces a wide shot with the runner at 10% of frame height, as expected.
- Output resolution now defaults to the median of all crop rectangle dimensions instead of the first frame's crop dimensions. This is more stable across videos where the runner's distance varies.

### Fixes and Maintenance
- Removed tiered fill ratio system from `CropController` in [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py): the `far_fill_ratio`, `far_threshold_px`, `very_far_fill_ratio`, and `very_far_threshold_px` parameters made the user-facing `crop_fill_ratio` setting effectively unreachable for typical footage. Existing YAML files with these keys will have them silently ignored.

### Developer Tests and Notes
- Added `test_crop_fill_ratio_always_applied` and `test_crop_output_resolution_median` to [emwy_tools/tests/test_track_runner.py](emwy_tools/tests/test_track_runner.py).
- Added 9 crop post-smoothing unit tests to [emwy_tools/tests/test_track_runner.py](emwy_tools/tests/test_track_runner.py): passthrough, jitter reduction, bounds clamping, constant velocity preservation, direction change, velocity cap, forward-backward EMA edge cases, interior symmetry, and metrics computation.

### Additions and New Features
- Added post-fuse refinement pass to interval solver in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py): after the first-pass independent FWD/BWD propagation and fusion, `refine_interval()` re-propagates each interval using the fused track as a soft spatial prior, then re-fuses. Reduces mid-interval wobble where both directions had decayed confidence. Always-on, no opt-in flag.
- Added `soft_prior` parameter to `_track_one_frame()` in [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py): optional dict with `cx`, `cy`, `weight` keys that blends estimated position toward a reference center. Only affects `cx`/`cy`, not `w`/`h`.
- Added `prior_track` parameter to `propagate_forward()` and `propagate_backward()` in [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py): optional dict keyed by absolute frame index. Prior weight is `min(PRIOR_WEIGHT_SCALE, fused_conf * PRIOR_WEIGHT_SCALE)` where `PRIOR_WEIGHT_SCALE = 0.3`. When None, behavior is unchanged from first pass.
- Added 6 refinement unit tests in [emwy_tools/tests/test_track_runner.py](emwy_tools/tests/test_track_runner.py): soft_prior None unchanged, pulls position, does not affect w/h, weight capped, short interval no crash, low confidence has small effect.
- Added "Post-fuse refinement pass" subsection to [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md): documents prior weight formula, pipeline order, and cx/cy-only blending.

### Decisions and Failures
- Interval scoring preserves first-pass FWD/BWD diagnostic signal. Refinement only affects output geometry (`fused_track`), not identity scores or competitor margins. This prevents refinement from hiding real identity ambiguity under smooth geometry.

## 2026-03-12

### Additions and New Features
- Added configurable encode filter pipeline to track_runner: filters apply after crop+resize during encoding to reduce noise and sharpen output. Two engines supported: OpenCV per-frame filters (`bilateral`, `clahe`, `sharpen`, `denoise`, `auto_levels`) run in Python, ffmpeg temporal filters (`hqdn3d`, `nlmeans`) run as `-vf` flags. Filter order is preserved. Use `--encode-filters bilateral,hqdn3d` on CLI or set `processing.encode_filters` in config YAML.
- Added `apply_denoise()` and `apply_auto_levels()` to [emwy_tools/common_tools/frame_filters.py](emwy_tools/common_tools/frame_filters.py): `denoise` uses `cv2.fastNlMeansDenoisingColored`, `auto_levels` does per-channel 1st/99th percentile histogram stretch. Added `apply_filter_pipeline()`, `get_ffmpeg_vf_string()`, and filter registry constants (`OPENCV_ENCODE_FILTERS`, `FFMPEG_ENCODE_FILTERS`, `ALL_ENCODE_FILTERS`).
- Added `encode_filters` parameter to `encode_cropped_video()`, `_encode_segment()`, and `encode_cropped_video_parallel()` in [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py). `VideoWriter` accepts optional `vf_string` for ffmpeg filters. When filters are active, resize uses `cv2.INTER_LANCZOS4` instead of `cv2.INTER_LINEAR`.
- Added `-F`/`--encode-filters` CLI flag to `encode` and `run` subparsers in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). CLI overrides config, config overrides default (empty list). Invalid filter names raise an error.
- Added `encode_filters: []` default to `processing` section in [emwy_tools/track_runner/config.py](emwy_tools/track_runner/config.py).
- Added `emwy_tools/common_tools/` package: consolidated shared modules (`tools_common.py`, `emwy_yaml_writer.py`, `frame_reader.py`) from `emwy_tools/` root into a dedicated subdirectory. All 10 import sites updated to use `import common_tools.X as X` pattern.
- Added [emwy_tools/common_tools/frame_filters.py](emwy_tools/common_tools/frame_filters.py): display-only image filters (bilateral, CLAHE, bilateral+clahe, sharpen, edge_enhance) for annotation UIs. Pure functions, no Qt dependencies, no effect on detection or color extraction.
- Added filter toggle button to [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py): "Filter: none" button in annotation toolbar cycles through filter presets. Filters are applied to displayed frames only; controllers retain raw BGR for detection and jersey color work.
- Added adjustable scrub step size in [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py): `[` and `]` keys cycle through step presets (0.1s, 0.2s, 0.5s, 1.0s, 2.0s, 5.0s). Toolbar shows clickable `Step: [ - ] 0.2s (6f) [ + ]` widget. Window title displays `Seed N/M | Frame F | Step Nf | Zoom Nx`. Hold Alt for 5x or Shift for 2x temporary step multiplier while scrubbing.
- Updated [docs/EMWY_TOOLS_MODULE_LAYOUT.md](docs/EMWY_TOOLS_MODULE_LAYOUT.md): directory tree and shared module descriptions reflect new `common_tools/` location and `frame_filters.py`.
- Added [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md): v3 spec document with seed status table (visible/partial/obstructed/not_in_frame), confidence decision grid with short-interval promotion, absence erasure rules, and v2-to-v3 differences. Clarifies that `not_in_frame` means runner is confirmed off-screen past the frame edge (definite), distinct from `obstructed` where the runner is still in-frame but hidden.
- Added obstructed seed support in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py): obstructed seeds with an approx area are now included as weak interval endpoints (conf=0.3). Seeds without an approx area remain excluded. Added `_prepare_usable_seed()` helper.
- Added interval-length-aware confidence scoring in [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py): `classify_confidence()` accepts `interval_length` parameter. Intervals of 5 frames or fewer get bumped one confidence tier (low->fair, fair->good, never to high). `score_interval()` passes `interval_length=len(forward_track)`.
- Added 7 new tests in [emwy_tools/tests/test_track_runner.py](emwy_tools/tests/test_track_runner.py): short-interval promotion (4 tests), obstructed seed filter inclusion/exclusion (2 tests), absence erasure all statuses (1 test).
- Added `anchor_to_seeds()` multi-seed anchored interpolation filter in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py). Post-stitch correction fits local windowed splines through seed positions: CubicSpline for cx/cy and PCHIP in log-space for w/h. Separate blend gains (0.5 for position, 0.3 for size) with squared confidence curve. Visible seeds hard-pinned; partial seeds guide fit but are not pinned. Axis-appropriate displacement caps and proximity skip zone (7 frames). Called in both `solve_all_intervals()` and `_mode_encode()`. Spec update in [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md). 14 unit tests added.

### Fixes and Maintenance
- Fixed partial and approx seeds not driving crop during encode in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) and [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py). Three compounding issues: (1) `fuse_tracks()` Dice overlap degraded confidence at seed frames, fixed by stamping seed confidence (1.0 for visible/partial, 0.3 for approx) onto trajectory after stitching via new `_stamp_seed_confidence()`. (2) `CropController.update()` multiplied smoothing alpha by confidence, causing near-zero response at low confidence, fixed by adding `alpha = max(alpha, 0.02)` floor. (3) Approx trajectory erasure replaced position with `None` which became center-frame fallback, fixed by inserting the approx seed's own position at low confidence instead. Also changed `trajectory_to_crop_rects()` to hold last known position with decaying confidence instead of center-frame snap when trajectory gaps occur. Seed status is now propagated into trajectory states via `seed_status` key.
- Fixed divergent trajectory erasure between solve and encode paths. Moved all erasure decision logic into `_apply_trajectory_erasure()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) so callers pass all seeds and the function decides what to erase. The four drawing modes: visible and partial (precise torso boxes) are kept; approximate (larger uncertain area) and not_in_frame (off-screen) are erased. Renamed from `_apply_absence_erasure`.
- Renamed status value from `"obstructed"` to `"approximate"` for seeds drawn in approx mode. Legacy `"obstructed"` seeds with `torso_box` are migrated to `"approximate"` on load; legacy `"obstructed"` seeds without `torso_box` (no position data) are dropped automatically on load. Updated across all UI controllers, interval solver, cli, seed editor, status presenter, and tests.
- Fixed FWD/BWD prediction overlays in [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py): `RectItem` now draws semi-transparent filled rectangles (alpha ~15%) with area-scaled border thickness (1px for small boxes, 2px for large), matching the old OpenCV `_draw_trajectory_preview()` style. Label font size also scales with box height. Previously overlays were opaque outlines with fixed 2px width that obscured the torso during annotation.
- Fixed progress bar in parallel solver showing 100% while intervals are still running in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py): switched from frame-level progress (which overcounts due to propagator including both interval endpoints) to interval-level progress. Bar now shows "intervals solved" and matches the "intervals complete: X/Y" text output.
- Fixed debug overlay in [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py) being oversized and opaque: all drawing elements (box thickness, crosshair length, text size, confidence bar) now scale with output resolution and tracked box size via `_compute_overlay_scale()`. Added transparency using `cv2.addWeighted` alpha blending (boxes at 55% opacity, text at 70% opacity). Overlay stays proportional whether runner fills the frame or is distant.

### Behavior or Interface Changes
- Short intervals (< 10 frames) in `classify_interval_severity()` in [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py) are unconditionally demoted from high to medium severity. FWD/BWD metrics are noisy on very short intervals so high severity inflated counts and wasted seed-targeting effort.
- Changed trajectory erasure in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py): all approximate and not_in_frame seeds trigger trajectory erasure. Only visible and partial seeds (precise torso boxes) are kept. Renamed constants to `APPROX_ERASE_RADIUS_S` and `NOT_IN_FRAME_ERASE_RADIUS_S`.
- Changed `classify_confidence()` signature in [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py): added optional `interval_length` parameter (default 0, no promotion). Existing callers are unaffected.

- Added [emwy_tools/track_runner/ui/](emwy_tools/track_runner/ui/) package: PySide6-based annotation window replacing all OpenCV `cv2.namedWindow` popup loops in track runner.
- Added [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py): `FrameView(QGraphicsView)` renders BGR frames via `QImage`/`QPixmap`, supports cursor-anchored zoom (1.25x per wheel tick, clamped 0.5x-10x) and `map_to_scene()` coordinate mapping.
- Added [emwy_tools/track_runner/ui/overlay_items.py](emwy_tools/track_runner/ui/overlay_items.py): `RectItem` (colored outline rect with optional label), `PreviewBoxItem` (semi-transparent green proposed box for polish preview), `ScaleBarItem` (zoom label in top-right corner, hidden at <=1.05x).
- Added [emwy_tools/track_runner/ui/theme.py](emwy_tools/track_runner/ui/theme.py): `apply_theme(app, mode)` supports dark/light/system modes; dark palette uses bg `#0F0F23`, text `#F8FAFC`, accent `#E11D48`; system detection via `app.styleHints().colorScheme()` with palette-brightness fallback.
- Added [emwy_tools/track_runner/ui/actions.py](emwy_tools/track_runner/ui/actions.py): `make_action()` factory for `QAction` with shortcut and tooltip; loads standard pixmap icons when a `QStyle.StandardPixmap` is provided.
- Added [emwy_tools/track_runner/ui/app_shell.py](emwy_tools/track_runner/ui/app_shell.py): `AppShell(QMainWindow)` base class; applies system theme on init; exposes `toggle_theme()` and `set_theme(mode)`.
- Added [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py): `AnnotationWindow(AppShell)` with `FrameView` as central widget; mode toolbar with mutually-exclusive Seed/Target/Edit `QActionGroup`; mode accent colors: Seed=`#0D9488`, Target=`#3B82F6`, Edit=`#8B5CF6`; saves window geometry to `QSettings` on close; `run()` enters the Qt event loop.
- Added [emwy_tools/track_runner/ui/status_presenter.py](emwy_tools/track_runner/ui/status_presenter.py): `StatusPresenter` QLabel showing `"Seed N/M  frame F  T.Ts  STATUS [conf S (L)]"`; per-status colors: visible=`#22C55E`, partial=`#F59E0B`, obstructed=`#F97316`, not_in_frame=`#94A3B8`.
- Added [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py): `SeedController(QObject)` replaces the `cv2.namedWindow` while-loop in `collect_seeds()`; QObject event filter on window and viewport handles keyboard (ESC/q=quit, SPACE=skip, LEFT/RIGHT=navigate, N=not_in_frame, P=partial, F=fwd_bwd_avg, A=approx_obstruction) and mouse drag for drawing boxes; FWD/BWD prediction boxes rendered as `RectItem` overlays; `ScaleBarItem` updated via `QTimer.singleShot` after wheel events.
- Added [emwy_tools/track_runner/ui/target_controller.py](emwy_tools/track_runner/ui/target_controller.py): `TargetController(SeedController)` subclass for `collect_seeds_at_frames()` with `pass_number=2` and `mode_str="suggested_refine"` defaults.
- Added [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py): `EditController(QObject)` replaces the `cv2.namedWindow` while-loop in `seed_editor.edit_seeds()`; keys: ESC/q=quit, SPACE/RIGHT=keep, LEFT=prev, D=delete, N=not_in_frame, P=partial, A=approx_obstruction, Y=YOLO polish, F=consensus polish, Z=zoom; `_YoloLoaderThread(QThread)` lazily loads YOLO weights on first `y` press; `_show_polish_preview()` adds a `PreviewBoxItem`; SPACE accepts pending polish; any other key rejects it; every committed op calls `save_callback` immediately for atomic mid-session persistence.
- Added `validate_seed()` to [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py): raises `ValueError` if `status == "obstructed"` and `torso_box` is absent. Called in `write_seeds()` before serialization.
- Added `a` key for positioned obstruction in seed and edit UIs. Draws a bounding box saved as `status: "obstructed"` with `torso_box`; replaces the old `o` key shortcut.
- Added `pyside6` to [pip_requirements.txt](pip_requirements.txt) and updated [docs/INSTALL.md](docs/INSTALL.md) with PySide6 6.x dependency note.
- Added [docs/EMWY_TOOLS_MODULE_LAYOUT.md](docs/EMWY_TOOLS_MODULE_LAYOUT.md): documents track_runner/ui/ split philosophy, promotion rule (2+ consumers), naming conventions, and non-goals.

### Fixes and Maintenance
- Fixed `AttributeError` on `_mode_label` in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py): moved `_mode_label` creation before mode toolbar setup so `_on_mode_changed` can reference it when `setChecked(True)` fires during `__init__`.
- Fixed `ModuleNotFoundError: No module named 'emwy_tools'` in [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py) and [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py): changed `from emwy_tools.track_runner import seeding` to `import seeding` to match the bare-import pattern used by the rest of the `ui/` package.
- Fixed `AttributeError` on `_active_controller` in [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py): moved `_active_controller` initialization before `setChecked(True)` which triggers `_on_mode_changed` -> `set_controller(None)`.
- Fixed `validate_seed()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py): changed from raising `ValueError` to `warnings.warn` for obstructed seeds missing `torso_box`, so legacy seeds do not block saving new work.
- Fixed mouse wheel zoom not working in seed and edit controllers: viewport event filter was consuming wheel events before `FrameView.wheelEvent` could process them. Now explicitly delegates wheel events to the FrameView.
- Fixed `KeyError: 'interval_score'` when loading diagnostics from disk: `write_solver_diagnostics()` flattens `interval_score` fields to top-level keys, but consumers expect `iv["interval_score"]`. Added reconstruction in `load_diagnostics()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) to rebuild the `interval_score` sub-dict from flat on-disk fields.
- Fixed FWD/BWD prediction overlays not showing in `-d seed` mode: `_mode_seed()` now loads predictions from diagnostics or solved-intervals files when available and passes them through `collect_seeds()` to `SeedController`.
- Added keybinding instructions to seed controller status bar and edit controller window title so users can see available shortcuts without burned-in frame text.
- Implemented `z` key zoom toggle in [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py) and replaced the stub in [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py): cycles through 1x, 1.5x, 2.25x, 3.375x zoom levels matching old opencv behavior. Centers on FWD/BWD prediction average (seed mode) or current seed position (edit mode).
- Added `set_zoom()` method to [emwy_tools/track_runner/ui/frame_view.py](emwy_tools/track_runner/ui/frame_view.py) for programmatic zoom with optional scene-point centering.
- Fixed missing `_current_seed` attribute in `EditController.__init__()`: `_load_current_seed()` now stores the seed dict so `_on_zoom_toggle()` and `_on_yolo_polish()` can reference it.
- Fixed `validate_seed()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py): changed from raising `ValueError` per-seed to returning frame index; `write_seeds()` collects all bad frames and prints a single summary on first save only, avoiding noisy repeated warnings.
- Added visual mode indicators for partial and approx draw modes in [emwy_tools/track_runner/ui/seed_controller.py](emwy_tools/track_runner/ui/seed_controller.py) and [emwy_tools/track_runner/ui/edit_controller.py](emwy_tools/track_runner/ui/edit_controller.py): colored status bar shows amber for partial mode, orange for approx mode, clears on box draw completion.
- Fixed partial/approx toggle mutual cancellation in both seed and edit controllers: entering partial mode now cancels approx mode and vice versa.
- Fixed target mode starting in seed mode: [emwy_tools/track_runner/ui/workspace.py](emwy_tools/track_runner/ui/workspace.py) now accepts `initial_mode` parameter. Target collection passes `initial_mode="target"`, seed editor passes `initial_mode="edit"`.
- Fixed edit controller partial box draw not clearing mode badge after `_partial_mode = False`.
- Changed arrow key behavior in seed, target, and edit controllers: at 1x zoom, bare LEFT/RIGHT advance frames as before. When zoomed in, bare LEFT/RIGHT pan the view (delegated to QGraphicsView) and Shift+LEFT/RIGHT advance frames. Shift+arrows always work regardless of zoom level.
- Fixed arrow key events not reaching controllers: installed event filter on `FrameView` (QGraphicsView) in addition to window and viewport, since QGraphicsView consumes arrow keys for scrolling before the window filter sees them.
- Added toolbar buttons to seed and edit controllers: Prev/Next (or Prev/Keep) navigation buttons and checkable Partial/Approx draw mode toggle buttons. Buttons sync with keyboard toggle state.

### Behavior or Interface Changes
- `collect_seeds()` in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) now uses `SeedController` + `AnnotationWindow` instead of a `cv2.namedWindow` while-loop. Behavior and keybindings preserved; window is now a native Qt window with dark theme and zoom.
- `collect_seeds_at_frames()` in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) now uses `TargetController` + `AnnotationWindow`.
- `edit_seeds()` in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py) now uses `EditController` + `AnnotationWindow`. Added `save_callback` parameter so callers can supply a write-through save function; each committed seed edit calls it immediately.
- `write_seeds()` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) upgraded to atomic write: uses `tempfile.mkstemp()` + `os.replace()` so the seeds file is never partially written.
- Removed all `cv2.destroyAllWindows()` calls from seeding and seed_editor modules. Window lifecycle is now managed by the Qt event loop.

### Decisions and Failures
- Chose QObject event filter pattern over subclassing `QWidget.keyPressEvent` to keep controllers decoupled from the window hierarchy. Controllers install themselves on the window and viewport and can be swapped per mode without modifying `AnnotationWindow`.
- Chose `QApplication.instance() or QApplication([])` guard so `collect_seeds()` can be called multiple times in the same process without crashing on a second `QApplication` construction.
- Positioned obstruction (`a` key) stores `torso_box` as the drawn box with no `jersey_hsv`, distinguishing it from legacy obstructed seeds that had no positional data.

## 2026-03-11

### Additions and New Features
- Added `target` subcommand to [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Standalone mode for adding seeds at weak interval frames after a solve. Accepts `--severity` (high/medium/low) to filter weak intervals and `--seed-interval` for spacing. Builds FWD/BWD prediction overlays from solved interval diagnostics. Requires a prior `solve` or `run` to generate diagnostics.
- Added shift-click zoom (1.5x) to the seed collection UI in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) and the seed editor in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py). Shift+click zooms to 1.5x centered on the click point; shift+click again or press `z` to return to full frame. Mouse coordinates map back to original frame space so drawn boxes remain accurate when zoomed. Shows "ZOOM 1.5x" indicator in top-right corner.
- Added `f` key (FWD/BWD average) to the seed collection UI in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py). When FWD and BWD predictions are both available and overlap sufficiently (intersection/(FWD+BWD) >= 0.3), pressing `f` auto-accepts the averaged box without requiring manual drawing. Silently ignored when predictions are missing or overlap is insufficient.
- Added `target_refine` to `VALID_SEED_MODES` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) for seeds collected via the new `target` subcommand.
- Added `refine` subcommand to [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Re-solves only changed/new intervals while reusing prior results for unchanged ones. Requires a prior `solve` run (errors with a clear message if no solved-intervals file exists). Complements `solve`, which now always clears prior results and re-solves everything fresh.
- Added seed confidence scores to the seed editor UI. `compute_seed_confidences()` in [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py) computes a composite score from adjacent interval agreement, competitor margin, and identity metrics. Confidence (high/medium/low/unknown) is displayed in the editor status bar when diagnostics are available.
- Added YOLO-based bbox polish (`y` key) and FWD/BWD consensus polish (`f` key) to the seed editor in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py). Both show a green preview box; press SPACE to accept or any other key to reject. YOLO polish runs detection in a local ROI with guardrails (center shift < 20%, area change < 30%, Dice >= 0.5) and blends 70% seed + 30% detection. FWD/BWD consensus blends seed with forward/backward predictions (60/20/20 or 70/30 weights). YOLO detector is lazily loaded on first `y` press.
- Added `bbox_polish` to `VALID_SEED_MODES` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) to distinguish polished seeds from manual redraws.
- Added `_refine_box_yolo()`, `_refine_box_consensus()`, and `_draw_preview_box()` helper functions to [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py).

### Fixes and Maintenance
- Removed dangerous `.get()` defaults from `emwy_tools/track_runner/` that silently masked missing required fields. Converted to direct `dict["key"]` access so missing keys crash immediately instead of producing wrong results.
  - `iv.get("interval_score", iv)` fell back to the entire interval dict, causing chained `.get("confidence", ...)` to silently read from the wrong dict. Fixed in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py), [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py).
  - `s.get("frame_index", s.get("frame", 0))` double fallback hid missing frame data by placing seeds at frame 0. Fixed in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py).
  - `state.get("conf", X)` used inconsistent defaults (1.0, 0.5, 0.1, 0.0) across files, meaning missing conf got different values in different code paths. Fixed in [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py), [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py), [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py), [emwy_tools/track_runner/hypothesis.py](emwy_tools/track_runner/hypothesis.py).
  - `iv.get("start_frame", 0)` / `iv.get("end_frame", 0)` created phantom zero-length intervals. Fixed in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py), [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py).
  - `seed.get("pass", 1)` silently defaulted to pass 1 causing wrong dedup decisions. Fixed in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py), [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py).
  - `seed.get("status", "visible")` assumed missing status meant visible. Fixed in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py), [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py).
  - `seed.get("cx", 0)` / `seed.get("cy", 0)` / `seed.get("w", 0)` / `seed.get("h", 0)` created invisible boxes at origin. Fixed in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py), [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py).
- Safe `.get()` defaults retained for optional config fields, display fallbacks, Counter-style access, and UI state initialization.
- Added `"conf": None` to all seed creation sites in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) (`_build_seed_dict` and inline absence dicts). Seeds start with `None` confidence until scored by FWD/BWD agreement. `solve_interval()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) treats `None` conf as 1.0 at interval boundaries (human-placed seeds are ground truth for propagation).

### Behavior or Interface Changes
- Changed confidence classification from 2-tier (high/low) to 4-tier (high/good/fair/low) in [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py). Old system classified everything as either TRUST or WEAK, lumping agreement=0.75 intervals with agreement=0.0. New tiers: high (agreement > 0.5 + margin > 0.5), good (agreement > 0.5 + margin > 0.2), fair (agreement > 0.2 + margin > 0.1), low (everything else). Only fair and low intervals generate seed suggestions. Requires a fresh `solve` to regenerate diagnostics.
- Updated display labels in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) and [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py) to show `[TRUST]`, `[GOOD]`, `[FAIR: reasons]`, `[WEAK: reasons]` instead of just TRUST/WEAK.
- Updated quality summary in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) to show all four tiers and count intervals needing seeds (fair + low only).
- Added `_validate_diagnostics_confidence()` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Raises a clear error telling the user to run `solve` if diagnostics are missing confidence data, instead of silently defaulting.
- Removed severity-based target frame caps from `_mode_target()` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). The caps (high ~40, medium ~80, low ~160) were misguided; the real fix was better confidence classification.
- Reduced FWD/BWD trajectory prediction overlays from 40% to 15% opacity and 2px to 1px border thickness in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) and [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py). Text labels reduced from 0.5 to 0.4 font scale. Prediction boxes are now much more transparent so the underlying frame content is clearly visible.
- Changed zoom from single-level toggle to three progressive levels (1.5x, 2.25x, 3.4x) via `z` key in seed collection and seed editor UIs. Each press zooms deeper; fourth press resets to full view. Zoom centers on FWD/BWD prediction average when available, falling back to frame center.
- Lowered FWD/BWD auto-accept overlap threshold from 0.3 to 0.1 for the `f` key in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py).
- Partial mode (`p` key) in the seed editor now preserves the current zoom level when transitioning to the draw box UI, so the user does not lose their zoom context while redrawing a partial seed.
- Added minimum area (10px) and maximum area (50% of frame) guardrails for drawn seed bounding boxes in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) and [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py). Prevents accidental clicks and giant boxes from being accepted as seeds.
- Added `rank_target_frames_by_severity()` to [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py). Ranks target frames by parent interval quality (lowest agreement score first, ties broken by competitor margin). Groups frames by score tier; within each tier, subsamples evenly across the video for spatial coverage instead of clustering at the start.
- Partial seeds now display gold/dark-gold boxes instead of cyan in the seed editor. Uses `(0, 200, 220)` BGR color matching the partial-mode draw color in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py).
- Seeds are now sorted by `frame_index` on both read and write in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py). `load_seeds()` sorts after validation and `write_seeds()` sorts before serialization, ensuring time-ordered navigation in the editor and human-readable JSON output.
- Recalibrated severity thresholds in [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py). Previous thresholds were too aggressive: `agreement < 0.5` or `margin < 0.2` alone triggered high severity even when FWD/BWD had near-perfect overlap. New scale: `agreement < 0.2` (poor) or identity swap is high; `agreement < 0.4` with `margin < 0.2` is high; `agreement < 0.4` or lone `margin < 0.2` is medium; everything else is low.

### Fixes and Maintenance
- Fixed `encode` subcommand crash ("diagnostics contain no trajectory data") in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). The diagnostics file intentionally excludes per-frame trajectory data to keep file size small. `_mode_encode()` now reconstructs the trajectory from the solved intervals file using `interval_solver.stitch_trajectories()`, with absence seed erasure applied from the seeds file. Also accepts an optional `intervals_path` parameter (derived from input file if not provided).
- Fixed progress bar showing 100% before all intervals are collected in parallel solve in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py). The shared frame counter could reach `total_frames` while future results were still being collected. Progress is now capped at 99% until all futures are collected, then set to 100%.
- Fixed `interval_score` lookup mismatch across [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py), [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), and [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py). The diagnostics file stores scores flat (e.g., `confidence`, `agreement_score` at top level), but code expected them nested under `interval_score`. Fallback `.get("interval_score", {})` returned empty dict, causing every interval to default to `"low"` confidence regardless of actual scores. Fixed fallback to `.get("interval_score", iv)` so flat-format diagnostics are read correctly. This was the root cause of `target --severity=high` showing 1215 frames (all of them) instead of just the ~116 truly low-confidence ones.

### Previous additions and new features
- Added `seed_editor.py` module to [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py). Interactive UI for reviewing, fixing, deleting, and redrawing existing seeds. Supports keep, delete, status change (not_in_frame, obstructed, partial), and mouse-drag redraw. Shows existing seed box in cyan, FWD/BWD prediction overlays, and status bar with seed index and frame info.
- Refactored [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) from flat argparse flags to subcommand architecture using `argparse.add_subparsers()`. Five modes: `run` (full pipeline, default), `seed` (collect and save), `edit` (review/fix seeds), `solve` (interval solver only), `encode` (encode from trajectory). Shared args (`-i`, `-c`, `-d`, `-w`, `--time-range`) on the parent parser; mode-specific args on each subparser.
- Split monolithic `main()` into `_mode_seed()`, `_mode_edit()`, `_mode_solve()`, `_mode_encode()`, and `_mode_run()` dispatch functions in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Common setup (config, probe, paths) stays in `main()`.
- Added `edit_redraw`, `solve_refine`, and `interactive_refine` to `VALID_SEED_MODES` in [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py).
- Updated trajectory prediction overlays in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py) and [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py) to use 40% opacity via `cv2.addWeighted()`. FWD/BWD boxes now show semi-transparent fills with solid borders so the underlying frame content remains visible behind them.
- Added `_build_predictions_from_diagnostics()` helper to [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Builds a frame-indexed dict of forward/backward predictions from solved interval diagnostics and passes it to all three `collect_seeds_at_frames()` call sites. The seeding UI now shows FWD (blue) and BWD (magenta) prediction boxes during refinement so the user can see where the solver thinks the runner is before drawing corrections.
- Added `classify_interval_severity()` to [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py). Classifies weak intervals into high/medium/low severity tiers using agreement score, competitor margin, failure reasons, and interval duration. Intervals longer than 10 seconds are promoted one severity level.
- Added `--severity` CLI flag to [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py). Accepts `high`, `medium`, or `low` to filter refinement targets by minimum severity tier. `--severity=high` shows only the worst intervals; `--severity=medium` shows high + medium.
- Added severity filtering to `generate_refinement_targets()` in [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py). When `severity` is set, only intervals at or above the given severity tier generate seed suggestions.
- Updated `_print_quality_summary()` in [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) to show severity breakdown (high/medium/low counts) and hint about `--severity=high` when weak intervals exist.
- Added solved-intervals persistence to retain interval results across runs. The JSON file (`*.track_runner.intervals.json`) stores fused tracks, scores, and margins keyed by a deterministic fingerprint of seed endpoints. On re-run after Ctrl+C, previously solved intervals load from disk and show `[PRIOR]`, skipping expensive re-solving. Stale results are avoided via fingerprint mismatch when seeds change.
- Added `default_intervals_path()`, `load_intervals()`, `write_intervals()`, and `interval_fingerprint()` to [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py) following the existing seeds/diagnostics pattern.
- Added `prior_intervals` and `on_interval_solved` parameters to `solve_all_intervals()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py). Prior results skip both parallel worker dispatch and sequential solving. New intervals are persisted to the solved-intervals file immediately after solving.
- Added `_load_prior_results()` helper to [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) to load previously solved intervals and build a write-through callback. Wired into all `solve_all_intervals()` call sites.

### Behavior or Interface Changes
- Replaced center-distance + scale-difference agreement metric with Dice coefficient (`2 * intersection / (area_a + area_b)`) in [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py). The old metric assigned low confidence to close-up runners because absolute pixel errors scaled with box size. Dice naturally handles scale -- two large boxes with 80% overlap score well regardless of absolute size.
- Updated `fuse_tracks()` in [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py) to use Dice-based agreement (`AGREE_DICE_THRESHOLD = 0.3`) instead of separate center and scale thresholds (`AGREE_CENTER_FRACTION`, `AGREE_SCALE_FRACTION`). Merged confidence is now scaled by Dice overlap quality.

### Behavior or Interface Changes
- `edit` mode now selectively invalidates only solved intervals that touch changed seeds, instead of deleting the entire solved-intervals file. Added `_invalidate_intervals_for_frames()` to [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py) which parses fingerprint keys to identify affected intervals. The `edit_seeds()` summary in [emwy_tools/track_runner/seed_editor.py](emwy_tools/track_runner/seed_editor.py) now includes `changed_frames` (set of modified frame indices) so the caller knows exactly which seeds changed.
- `solve` subcommand now clears prior solved intervals before solving, ensuring a full fresh re-solve every time. Previously it implicitly reused prior results.
- Renamed "interval cache" terminology to "solved intervals" / "prior results" across [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py), [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py), and [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py). The JSON key changed from `cached_intervals` to `solved_intervals`. Parameters renamed: `intervals_cache` to `prior_intervals`, `on_interval_cached` to `on_interval_solved`. Console output now shows `[PRIOR]` instead of `[CACHED]`.

### Fixes and Maintenance
- Fixed FWD/BWD prediction boxes not displaying in `edit` mode. The diagnostics file lacks per-frame tracks, so predictions were always empty. `_mode_edit()` now falls back to loading predictions from the solved-intervals file (`*.track_runner.intervals.json`), which stores complete forward/backward tracks per interval.
- Fixed `crop_aspect` config setting being ignored. `create_crop_controller()` in [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py) was reading from the nonexistent `config['settings']['crop']` path instead of `config['processing']`, causing it to always fall back to `1:1` square crops regardless of the user's config.
- Fixed `--time-range` flag being silently ignored during `--seed-only` seed collection. Time range is now parsed before seed collection and passed to `collect_seeds()` in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py).
- Fixed `_parse_time_range()` crashing on open-ended ranges like `200:` or `:500`. Now returns `None` for the missing endpoint instead of calling `float('')`.
- Added `time_range` parameter to `collect_seeds()` in [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py). Filters candidate frame indices to only those within the specified time range before presenting them to the user.
- Updated `--time-range` help text to indicate it applies to both seed collection and refinement.
- Changed partial mode draw box color from green to dark gold in the seeding UI. Provides visual feedback that partial mode is active when drawing the torso rectangle after pressing `p`.

- Added `partial` seed status for partially obstructed runners. Press `p` in the seeding UI to enter partial mode, then draw the torso box. Partial seeds have reliable position but unreliable appearance (jersey color contaminated by obstruction).
- Added `_apply_absence_erasure()` to `interval_solver.py`. After trajectory stitching, erases frames within 1.0s of `not_in_frame` seeds and 0.5s of `obstructed` seeds. Prevents garbage propagation data from persisting through absence zones.
- Added absence seed logging in `cli.py`. Prints breakdown of visible, partial, not_in_frame, and obstructed seed counts when non-visible seeds exist.

### Behavior or Interface Changes
- Interval solver now treats `partial` seeds as usable interval endpoints alongside `visible` seeds. Partial seeds provide position data (cx, cy, w, h) but are excluded from appearance model construction to avoid jersey color contamination.
- Renamed internal variable `visible_seeds` to `usable_seeds` in `interval_solver.py` and `cli.py` to reflect inclusion of partial seeds as interval endpoints.
- Removed `cyclical_prior` parameter from `solve_interval()`, `_solve_interval_worker()`, and `solve_all_intervals()` return dict. `_detect_cyclical_prior()` retained as unused utility for potential future bbox area refinement.
- Removed sequential interval 1 gate in `solve_all_intervals()`. All intervals are now dispatched to the parallel pool immediately, eliminating the ~5-minute sequential bottleneck before workers start.
- Added `backward_reader` parameter to `solve_interval()`. When provided, forward and backward propagation run concurrently in threads using separate `VideoReader` instances. `_solve_interval_worker()` creates a second reader automatically.

### Fixes and Maintenance
- Added `KeyboardInterrupt` handler to parallel solving loop in `solve_all_intervals()`. On Ctrl+C, cancels pending futures and calls `pool.shutdown(wait=False, cancel_futures=True)` to kill workers immediately instead of waiting for them to finish. Prevents orphaned worker processes from consuming CPU after interrupt.
- Added sequential-read optimization to `VideoReader.read_frame()` in `encoder.py`. Skips the `CAP_PROP_POS_FRAMES` seek when reading the next consecutive frame, avoiding expensive MKV keyframe searches during propagation.
- Added 30-second heartbeat output to `propagate_forward()` and `propagate_backward()` in `propagator.py`. When `debug=True`, prints frames completed, elapsed time, and rate every 30 seconds. Eliminates minutes of silence during optical flow propagation on large frames.
- Added `flush=True` to all debug print statements in `solve_interval()` propagation section to ensure output appears immediately.
- Added completion timing around the first sequential interval solve in `solve_all_intervals()`. Prints elapsed time when interval 1 finishes.
- Fixed degenerate 0-0 intervals caused by duplicate seeds at the same frame_index. `collect_seeds()` and `collect_seeds_at_frames()` now filter out candidate frames that already have seeds, bumping collisions to the next unused frame.
- Removed `_seeds_to_solver_format()` from `cli.py`. Seeds already contain `cx`, `cy`, `w`, `h`, `frame_index` from `_build_seed_dict()`. The converter was silently defaulting missing keys to 0 instead of failing, masking data problems.
- Added required-field validation in `solve_all_intervals()`: seeds missing `cx`, `cy`, `w`, `h`, or `frame_index` now raise `RuntimeError` instead of silently defaulting to zero.
- Added frame_index deduplication safety net in `solve_all_intervals()`. When multiple seeds share the same frame_index, only the latest pass is kept, with a warning printed.
- Added degenerate interval rejection in `solve_interval()`: raises `RuntimeError` when `start_frame >= end_frame`.

### Additions and New Features
- Added frame-level progress bar for parallel interval solving in `interval_solver.py`. Uses `multiprocessing.Value` as a shared atomic counter across worker processes, polled every 0.2s. Replaces the coarse interval-level bar that appeared frozen during long intervals. Wall-clock time and throughput printed every 30 seconds.
- Added `detect_roi()` method to `YoloDetector` in `detection.py`. Crops the frame to a region of interest around the predicted runner position before running YOLO, giving better detection resolution for small runners in large frames. Minimum crop size 320x320, default padding factor 3x. Wired into `solve_interval()` for all frames after the first.
- Added `on_interval_complete` callback parameter to `solve_all_intervals()` for real-time notification when intervals finish. Used by CLI to track weak intervals during solving.
- Added post-solve interactive seed collection in `cli.py`. After the solve completes, if weak intervals were found, the user is immediately prompted to add seeds at suggested frames rather than waiting for the separate refinement loop. New seeds trigger an automatic re-solve.
- Added `frame_counter` and `debug` parameters to `solve_interval()`. Debug mode prints per-frame detection count, competitor count, identity score, and margin.
- Replaced `tqdm` progress bars with `rich.progress` in interval solving and video encoding in track_runner. Interval-level progress in `solve_all_intervals()` and frame-level progress in `encode_cropped_video()` and `_encode_segment()` now use rich progress bars with bar, percentage, and ETA columns.
- Added simple print-based seed counter (`seed 3/12 frame 450`) to `collect_seeds()` and `collect_seeds_at_frames()` in `seeding.py` for progress visibility during interactive seeding (avoids cv2.imshow conflict with terminal progress bars).
- Added parallel interval solving via `concurrent.futures.ProcessPoolExecutor` in `interval_solver.py`. Each worker process creates its own `VideoReader` and YOLO detector. First interval runs sequentially (for cyclical prior detection), remaining intervals run in parallel.
- Added parallel video encoding via `encode_cropped_video_parallel()` in `encoder.py`. Splits frame range across N workers, each with its own `VideoReader` and ffmpeg pipe. Segments concatenated with `mkvmerge`.
- Wired up the existing `-w`/`--workers` CLI flag (previously unused). Defaults to half of CPU cores. Controls both parallel interval solving and parallel encoding.
- Created `emwy_tools/frame_reader.py` with `FrameReader` class that wraps
  `cv2.VideoCapture` with five seeking strategies: (1) msec seek, (2) frame index seek,
  (3) reopen + frame index seek, (4) sequential forward read fallback,
  (5) automatic remux to MKV via mkvmerge when all other strategies fail (fixes
  HEVC/H.265 in QuickTime MOV containers where OpenCV cannot seek at all). Temp MKV
  is cleaned up on close(). Module lives in shared `emwy_tools/` for use by any tool.
- Added `save_callback` parameter to `collect_seeds()` and `collect_seeds_at_frames()`
  for crash-safe incremental seed saving. Seeds are now written to disk after each new
  seed is collected, so a crash mid-collection no longer loses all work.
- Created `tests/test_seed_frame_reading.py` with 3 smoke tests: basic reads, sequential
  fallback when seeking is broken, and backward scrub handling.

### Behavior or Interface Changes
- `collect_seeds()` and `collect_seeds_at_frames()` now accept `debug` and `save_callback`
  parameters. The `--debug` CLI flag now enables verbose frame-reading output during
  seeding (previously only affected encoder overlay).

### Fixes and Maintenance
- Fixed frozen parallel solve progress bar: switched from sequential `future.result()` iteration to `concurrent.futures.as_completed()` so the bar updates as each worker finishes. Used `progress.console.print()` instead of bare `print()` to avoid rich live display conflicts.
- Added rich progress bar to the sequential solving path (previously had no interval-level progress bar in `-w 1` mode).
- Fixed spinning pinwheel on macOS after seed collection window closes by flushing
  the cv2 event loop with multiple `cv2.waitKey(1)` calls instead of a single one.
- Fixed strategy 3 in frame seeking: previously reopened the capture but retried the
  same msec-based seek that already failed; now uses frame index seek after reopen.
- Fixed sequential fallback (strategy 4) sharing the same `cv2.VideoCapture` with
  seek-based strategies 1-3. Failed seeks corrupted the cap's internal position, making
  sequential reads fail immediately. Strategy 4 now uses a dedicated `self._seq_cap`
  that is never touched by seek operations.
- Refreshed `docs/CODE_ARCHITECTURE.md` and `docs/FILE_STRUCTURE.md` to reflect the
  track_runner v2 rewrite: added track_runner v2 module map with all 12 modules and
  their responsibilities, added track_runner data flow diagram, added `tools/` directory,
  added new docs (`TRACK_RUNNER_V2_SPEC.md`, `SEED_VARIABILITY_FINDINGS.md`), removed
  stale `kalman.py` and `tracker.py` from the file tree, and added `TRACK_VIDEOS/` to
  generated artifacts.

### Decisions and Failures
- Replaced Kalman filter backbone with seed-driven interval solver after measurements showed
  9-13x bbox overestimation in diagnostics, jersey color unusable below 30px, and camera
  motion contaminating velocity state. The Kalman filter was optimized for radar tracking
  of uniform-speed objects; runners change speed, stop, and are occluded for long stretches.
- New philosophy: the human establishes identity at seed frames; the machine interpolates
  geometry between trusted anchor points and flags intervals where it is uncertain.
- Decision: tracks torso only (no full-person box estimation). Torso is more stable, more
  discriminative for jersey color, and avoids leg/arm articulation noise.
- Decision: competitor hypothesis tracking (up to 3 paths) runs alongside target tracking
  so the solver can quantify ambiguity rather than silently choosing the wrong person.

### Removals and Deprecations
- Deleted `emwy_tools/track_runner/kalman.py` and `emwy_tools/track_runner/tracker.py`.
  Both implemented the v1 Kalman filter tracking pipeline (Kalman predict/update, detection
  matching, bidirectional pass merging, jerk region detection, interpolation). These are
  replaced by the v2 interval_solver + propagator + hypothesis pipeline. No remaining
  imports of either module exist in the codebase.
- Rewrote `emwy_tools/track_runner/scoring.py` for v2: removed all v1 code (hard gates,
  weighted candidate scoring, `select_best`, `apply_hard_gates`, `score_candidates`,
  `_compute_color_score`, `_bbox_center`, and `kalman` import). New module has one job:
  take interval evidence and return confidence metrics. New functions:
  `score_interval()`, `compute_agreement()`, `compute_meeting_point_errors()`,
  and `classify_confidence()`.

### Behavior or Interface Changes
- Refactored `emwy_tools/track_runner/detection.py`: removed `HogDetector` class and HOG
  fallback logic. `create_detector()` now always returns a `YoloDetector` and raises
  `RuntimeError` if YOLO weights are unavailable instead of silently falling back to HOG.
  The detector is now a supporting cue used by `interval_solver`, not the backbone.
- Simplified `emwy_tools/track_runner/config.py` to v2: header changed from `track_runner: 1` to `track_runner: 2`. Removed all Kalman/tracker-specific sections (tracking, scoring, camera_compensation, jersey_color, seeding, experiment, io). Default config is now ~15 lines covering detection (model, confidence_threshold) and processing (crop_aspect, crop_fill_ratio, video_codec, crf). Removed `load_seeds()`, `write_seeds()`, `load_diagnostics()`, `write_diagnostics()`, `default_seeds_path()`, `default_diagnostics_path()` (moving to state_io.py). `validate_config()` updated to check top-level `detection` and `processing` sections instead of the old nested `settings` structure.
- Refactored `emwy_tools/track_runner/crop.py` to consume v2 trajectory dicts instead of the
  v1 frame_states list format.
- Seeds now stored as JSON instead of YAML (smaller files, no serialization edge cases).
- Diagnostics now stored per-interval instead of per-frame, making files much more compact.

### Additions and New Features
- Rewrote `emwy_tools/track_runner/cli.py` for v2 multi-pass orchestration. Removed all v1
  orchestration functions (_find_worst_streaks, _find_seedless_gaps, find_jerk_regions,
  _find_stall_regions, _find_big_movement_regions, _find_area_change_regions,
  _merge_streak_lists, _streaks_to_seed_frames, _tracking_quality_grade, _print_quality_report,
  _collect_predictions_for_streaks, _generate_interval_targets, _sanitize_seeds_for_yaml).
  Removed imports of tracker, kalman, numpy, and tools_common. New data flow: config load ->
  initial seeding (pass 1) -> interval_solver -> diagnostics -> optional --refine pass with
  review-guided target frames -> crop trajectory -> encode -> mux audio. New helpers:
  `_probe_video()` (ffprobe subprocess), `_parse_time_range()`, `_trajectory_to_crop_rects()`,
  `_print_quality_summary()`, and `_write_diagnostics()`. Seeds and diagnostics use state_io.
  New CLI flags: --refine, --gap-threshold, --time-range, --ignore-diagnostics.
- Rewrote `emwy_tools/track_runner/seeding.py` for v2 multi-pass review-driven workflow.
  Removed `find_overlapping_person()`, `estimate_full_person_from_torso()`,
  `_resolve_full_person_box()`, `_draw_prediction_box()`, and `_compute_iou()` (v1 concepts
  that estimated full-person boxes; v2 tracks torso only). Added `_build_seed_dict()` to
  produce v2 seed format (frame, time_s, torso_box, jersey_hsv, cx, cy, w, h, pass, source,
  mode, status) and `_draw_trajectory_preview()` for forward/backward overlay during
  refinement. Updated `collect_seeds()` and `collect_seeds_at_frames()` with `pass_number`,
  `mode`, and `existing_seeds` parameters so new seeds append without overwriting.
  No imports from interval_solver, review, or scoring.
- Created `emwy_tools/track_runner/state_io.py`: JSON read/write for seeds and diagnostics,
  replacing the previous YAML-based file I/O in config.py.
- Created `docs/TRACK_RUNNER_V2_SPEC.md`: v2 architecture specification covering the
  interval solver, propagator, hypothesis tracker, and seed-driven workflow.
- Created `emwy_tools/track_runner/review.py`: weak span identification and seed suggestion.
  Key functions: `identify_weak_spans()` (one suggestion per failure reason, deduped by frame),
  `generate_refinement_targets()` (three modes: suggested/interval/gap, comma-combinable,
  time_range-filtered), `format_review_summary()` (human-readable interval table + suggestion
  list), and `needs_refinement()` (bool fast-path check). Supports all seven failure reason
  strings: low_agreement, low_separation, weak_appearance, detector_conflict,
  stationary_ambiguity, likely_occlusion, likely_identity_swap.
- Created `emwy_tools/track_runner/interval_solver.py`: per-interval bounded solver that splits
  seed-to-seed intervals, propagates forward and backward, maintains competitor hypotheses,
  fuses tracks with confidence-weighted averaging on agreement and winner-takes-all on
  disagreement, scores each interval with scoring.py, and stitches all intervals into a full
  trajectory. Key functions: `solve_all_intervals()`, `solve_interval()`, `fuse_tracks()`,
  `stitch_trajectories()`, and `_detect_cyclical_prior()` (autocorrelation-based lap detection).
  Console output per interval: frame range, duration, agree/margin/identity scores, [TRUST/WEAK].
- Created `emwy_tools/track_runner/hypothesis.py`: competing path generation for interval solving.
  Maintains up to 3 competitor paths from YOLO detections that do not overlap the target.
  Key functions: `generate_competitors()`, `maintain_paths()`, `compute_identity_score()`,
  `compute_competitor_margin()`, `_compute_iou()`, and `_propagate_competitor_simple()`.
  Scale-gated identity scoring (>60px uses template correlation + HSV, 30-60px HSV only,
  <30px returns neutral 0.5). Competitor margin quantifies target ambiguity for downstream use.
- Created `emwy_tools/track_runner/propagator.py`: frame-to-frame local torso tracking using
  Lucas-Kanade optical flow and normalized patch correlation. Key functions:
  `build_appearance_model()`, `propagate_forward()`, `propagate_backward()`,
  `_track_one_frame()`, `_extract_features()`, `_compute_median_flow()`,
  `_estimate_scale_change()`, `_patch_correlation()`, and `make_seed_state()`.
  Implements scale-gated blending (>60px appearance-heavy, 30-60px balanced, <30px flow-only),
  stationary lock (5-frame near-zero-displacement streak triggers position-hold mode),
  and per-frame confidence decay with floor at 0.1.
- Updated `emwy_tools/track_runner/encoder.py` debug overlay for v2 tracking state format.
  `draw_debug_overlay_cropped()` now accepts `state` dict with keys `cx, cy, w, h, conf, source`
  and an optional `debug_state` dict. New overlay elements: solid green accepted torso box,
  dashed blue forward track box, dashed orange backward track box, red competitor box (low margin),
  confidence label (HIGH/MED/LOW), source label (seed/propagated/merged), interval ID `[start-end]`.
  Added helpers `_draw_dashed_rect()` and `_box_to_crop_coords()`. Updated `_source_color()` for
  v2 source values. Removed old v1 color constants and state fields (bbox, frame_index, confidence).
  No imports from `kalman.py` or `tracker.py`.
- Created `tools/measure_seed_variability.py`: self-contained measurement tool that loads seed and diagnostics YAML files and prints a comprehensive variability report with CSV export. Measures seed coverage, start-line static phase, torso area variability (344x range in Test-1), frame movement (65% of frame width), jersey HSV variability (hue spans 94% of range), torso-vs-full-person box relationship, diagnostics bbox overestimation (~9-13x too large), and cyclical lap patterns (~40s periods). Outputs raw and smoothed CSV to `output_smoke/`.
- Created `tools/plot_seed_variability.py`: generates 6-panel matplotlib plots per video showing raw scatter and 15s running-averaged signals for torso area, center X/Y, jersey hue, saturation/value, and tracker bbox vs seed area comparison. Saves PNG to `output_smoke/`.
- Created [docs/SEED_VARIABILITY_FINDINGS.md](docs/SEED_VARIABILITY_FINDINGS.md): analysis of seed variability measurements across Track_Test-1 and Track_Test-3. Key findings: 344x area ratio, jersey color spans 94% of hue range (unusable), tracker overestimates size by 9-13x, ~40s lap periods from center-x. Includes parameter ranges and six recommendations for the tracker rewrite.
- Created [docs/TRACK_RUNNER_SPEC.md](docs/TRACK_RUNNER_SPEC.md): comprehensive specification documenting how the track_runner tool (4505 lines, 11 files) actually works today, covering all modules, data flows, configuration defaults, bounding box format reference, and 11 known issues with error-prone patterns. Intended to guide a future rewrite.

### Removals and Deprecations
- Deleted `emwy_tools/tests/test_stabilize_building.py` (4 integration tests requiring ffmpeg/vid.stab).
- Deleted `emwy_tools/tests/test_emwy_yaml_writer.py` (5 unittest-based tests).
- Trimmed 24 low-value tests from `emwy_tools/tests/test_track_runner.py`: removed config key-existence checks (5), signature-inspection tests (6), trivially obvious tests (7), redundant debug overlay test (1), duplicate seeding test (1), low-value detection test (1), and 3 of 6 quality grade tests. Remaining: 60 tests.

### Additions and New Features
- Added `_find_big_movement_regions()` to detect regions where the tracked bbox has sudden large displacements normalized by person height, flagging possible wrong-person switches. Uses `movement_threshold=0.15` (lower than jerk detection's 0.3) to catch subtler jumps across all frame sources.
- Added `_find_area_change_regions()` to detect regions where the bbox area changes suddenly (>50% per frame gap), flagging possible target switches where the tracker locks onto a person of different size.
- `--add-seeds` now targets six signal sources: problem-region streaks, seedless gaps, stall regions, movement regions, area change regions, and interval-based targets (when `--seed-interval` is also provided). Summary print shows counts for all six source types.
- Added `_generate_interval_targets()` to produce regular-interval seed targets for `--add-seeds`, skipping frames near existing seeds (within 2*fps dedup distance).
- Added `bbox_all_frames` key to tracking diagnostics storing `[frame_idx, cx, cy, w, h]` for all frames with a bbox, enabling movement and area change analysis on subsequent `--add-seeds` runs.
- Added very-far adaptive crop tier: when the runner's bbox height is below `very_far_threshold_px` (default 60px), the fill ratio increases to `very_far_fill_ratio` (default 0.65) for a much tighter crop. Linear interpolation between very-far (60px) and far (120px) thresholds. A 54px runner now fills ~27% of the crop instead of ~15%.
- Lowered `min_crop_size` from 360 to 200 pixels, allowing tighter crops for very small/far subjects without the minimum clamping the adaptive fill ratio system.
- Added `max_v_log_h` cap (default 0.05) to Kalman size velocity in tracker, mirroring the existing `max_vy_fraction` vertical velocity cap. Prevents runaway bbox growth when the Kalman filter learns a growing-size trend.
- Added `max_bbox_area_fraction` hard gate (default 0.15) in scoring to reject any candidate detection whose area exceeds 15% of the frame area. Prevents the tracker from locking onto a nearby bystander filling the frame.
- Tightened default `hard_gate_scale_band` from 3.0 to 2.0 (allows up to 2x area change per frame instead of 3x) to reduce compounding size jumps.
- Frame dimensions (`frame_width`, `frame_height`) now passed into scoring config so the area fraction gate can compute the frame area.
- Added adaptive fill ratio to crop controller: when the runner is far away (small bounding box), the crop is tighter so the runner still fills a meaningful portion of the output frame. Controlled by `far_fill_ratio` (default 0.50) and `far_threshold_px` (default 120px) under `settings.crop`. Linear interpolation between far and baseline fill ratios.
- Split track_runner config into three separate YAML files: `{video}.track_runner.config.yaml` (settings only), `{video}.track_runner.seeds.yaml` (seed bounding boxes), and `{video}.track_runner.diagnostics.yaml` (tracking diagnostics). Keeps settings file small and manageable.
- Added `config.default_seeds_path()`, `config.default_diagnostics_path()`, `config.load_seeds()`, `config.write_seeds()`, `config.load_diagnostics()`, `config.write_diagnostics()` for handling the new file layout.
- Added backward compatibility warning when seeds are found in the main config file.

### Fixes and Maintenance
- Improved debug overlay bounding box visibility: added black outline behind the colored rectangle for contrast, crosshair at bbox center, and box coordinate text label below the frame info.

### Behavior or Interface Changes
- Changed left/right arrow scrub step in seed selection GUI from 0.5 seconds to 0.2 seconds for finer navigation.
- `default_config()` no longer includes a `seeds` key; seeds are stored in a separate file.
- CLI now reads/writes seeds and diagnostics from/to their own YAML files instead of embedding them in the main config.
- Migrated existing `Track_Test-1.mov` config from 38,502 lines to 56 lines by splitting seeds (2,794 lines) and diagnostics (35,213 lines) into separate files.

### Developer Tests and Notes
- Added tests for seeds/diagnostics round-trip, missing file handling, adaptive crop keys, and adaptive fill ratio behavior (far vs close runner).
- Removed `test_config_round_trip` (no longer applicable after seeds removal from default config).

## 2026-03-10

### Additions and New Features
- Added `_find_seedless_gaps()` helper to detect large stretches of video with no seeds and place seed targets every ~5 seconds within those gaps. Gaps shorter than 15 seconds are ignored.
- Added `_find_stall_regions()` helper to detect regions where the tracked bbox barely moves (< 2% of frame width), indicating the tracker may have latched onto a stationary person. Skips first/last 5 seconds of video.
- `--add-seeds` now targets three signal sources: problem-region streaks, seedless gaps, and stall regions. Targets are merged, deduplicated (within 2 seconds), and presented to the user with source labels.
- Per-frame bbox center positions (`bbox_positions`) now saved in `tracking_diagnostics` for stall detection on subsequent `--add-seeds` runs without re-tracking.
- Added motion jerkiness detection via `tracker.find_jerk_regions()` to flag sudden bbox jumps between consecutive detected frames (likely wrong-person switches). Uses `jerk_threshold` config key (default 0.3) to control sensitivity.
- `--add-seeds` GUI now shows forward (blue) and backward (magenta) prediction overlays at problem frames so users can see where each tracking pass thought the runner was.
- Per-frame forward/backward predictions stored in `tracking_diagnostics.predictions` for bad streak frames, along with `jerk_regions` list.
- Jerk regions are merged with prediction-gap streaks for `--add-seeds` targeting.

### Behavior or Interface Changes
- `tracker.run_tracker()` now returns a 4-tuple `(crop_rects, frame_states, forward_states, backward_states)` instead of a 2-tuple.
- Tracking quality grade downgrades by one letter when jerk regions are detected.
- Quality report now prints jerk region count when nonzero.
- Merged debug overlay into the single cropped output video. When `--debug` is passed, tracking bounding boxes and info text are drawn directly on the cropped/resized frames instead of producing a separate full-resolution debug video. Only one output video is produced regardless of `--debug`.
- Removed `encode_parallel()`, `encode_debug_video()`, and `draw_debug_overlay()` from encoder.py, replaced by `draw_debug_overlay_cropped()` which transforms tracking bbox coordinates into crop-space.
- Updated `--debug` help text to reflect the new behavior.

### Previous additions and new features
- Added `max_displacement_per_frame` hard gate (default 80 pixels) to track_runner scoring. This absolute pixel ceiling prevents wild crop jumps regardless of how wide the search radius grows during missed detection streaks. Configurable under `settings.scoring.max_displacement_per_frame`.
- Added absence markers to track_runner seeding UI: press `n` to mark the runner as "not in frame" and `o` to mark as "obstructed" during seed selection. These create minimal seed dicts with a `status` field instead of bounding box data.
- Tracker now handles absence marker seeds: `not_in_frame` drops confidence to floor and marks frames as `source: "absent"`, while `obstructed` bumps the missed streak but lets Kalman prediction continue normally.
- Gap interpolation now skips stretches containing absent frames, avoiding interpolation through regions where the runner is known to be gone.
- Quality report now displays absent frame count and percentage when nonzero.
- Minimum seed validation now filters to visible seeds only, so absence markers alone do not satisfy the seed requirement.
- `_find_worst_streaks()` now counts `absent` frames alongside `predicted` and `interpolated` for streak detection, so problem regions with absence markers are correctly identified for `--add-seeds`.
- Added parallel detection pass to track_runner: splits frame range across N worker processes, each with its own `cv2.VideoCapture` and YOLO detector instance. Controlled by `-w`/`--workers` flag (default: half of CPU cores).
- Added parallel forward+backward Kalman tracking passes using `ThreadPoolExecutor`. Both passes read from the same cached detections (read-only) and produce independent results, so no data races.
- Added parallel crop+debug encoding via `encode_parallel()` in encoder.py: single decode pass writes to both crop and debug ffmpeg pipes concurrently, saving one full video decode when `--debug` is used.
- Added `-w`/`--workers` CLI flag to track_runner for controlling parallel worker count. Default auto-detects to half of CPU cores.
- Added wall-clock timing instrumentation to track_runner CLI: prints elapsed time for tracking, encoding, and audio mux phases, plus total time at the end.
- Added `-d`/`--debug` CLI flag to track_runner (replaces `--write-debug-video`) that renders a full-resolution debug video with colored tracking bbox overlay (green=detected, yellow=predicted, orange=interpolated, red=lost), crop rectangle, frame number, source label, and confidence bar for visual inspection of tracking quality.
- Added `draw_debug_overlay()` and `encode_debug_video()` functions to `emwy_tools/track_runner/encoder.py` for debug video rendering.
- Added missing config keys to `default_config()`: `max_vy_fraction` and `velocity_freeze_streak` under `settings.tracking`, and `vertical_limit_scale` under `settings.scoring`, so all tracker tunables are in one place instead of scattered as hardcoded fallbacks.

### Fixes and Maintenance
- Fixed `_find_worst_streaks()` counting only `predicted` frames but missing `interpolated` frames. After gap interpolation (phase 5), predicted gaps were relabeled as `interpolated`, causing `--add-seeds` to report "no problem regions" even when many existed. Now counts both `predicted` and `interpolated` frames as missed-detection streaks.
- Fixed quality grade thresholds that were far too lenient (A was >= 15% detection). Raised to meaningful values: A >= 85%, B >= 70%, C >= 50%, D >= 30%.
- Fixed seed reinit logic in bidirectional tracking that always re-initialized Kalman at the init seed frame due to an `or` clause defeating the guard (`if seed is not init_seed or frame_idx == init_seed["frame_index"]`). Removed the `or` clause so the init seed is correctly skipped.
- Renamed `--write-debug-video` flag to `-d`/`--debug` for convenience.
- Increased `_find_worst_streaks` default `max_targets` from 10 to 24 so more problem regions are saved for `--add-seeds`.

### Previous additions and new features
- Added arrow key navigation (LEFT/RIGHT) to seeding UI for scrubbing forward/backward by 0.5 seconds when the runner is not visible at the exact seed interval frame.
- Added `--add-seeds` CLI flag to `track_runner`: reads saved problem regions from a previous render and opens the seed UI at those frames so the user can add targeted seeds. New seeds merge with existing ones and tracking re-runs.
- Normal render now saves `tracking_diagnostics` to the config YAML, including full `bad_streaks` data (start frame and length for each), so `--add-seeds` can read them back without re-running the tracker.
- `--add-seeds` now places multiple seed targets across long streaks (~1 every 5 seconds of drift) instead of a single midpoint, so long problem regions get adequate coverage.
- Normal render now prints problem regions and a `--add-seeds` hint when bad streaks are found.
- Added `collect_seeds_at_frames()` in `seeding.py` for collecting seeds at specific frame indices rather than fixed intervals.
- Added Kalman velocity freeze after 10+ consecutive missed detections to prevent predicted position from drifting away from last known location.
- Refactored `tracker.py` from forward-only to bidirectional tracking. Detection runs once and is cached, then Kalman runs both forward and backward from seeds. Per-frame results are merged by confidence, so frames before the first seed and after the last seed both get high-quality tracking.
- Added per-frame vertical velocity cap (`max_vy_fraction`, default 0.03x predicted person height per frame) on Kalman state to prevent upward drift. Scales with person size so closer runners get proportionally more slack.
- Added vertical displacement hard gate (`vertical_limit_scale`, default 0.5x predicted person height) to reject candidates that jump too far vertically. Scales with the tracked person's bounding box so a closer (larger) runner allows more vertical motion than a distant one.
- Added dynamic search radius widening in hard gates when detections are being missed (grows up to 3x after sustained miss streak), improving reacquisition after occlusion.
- Added quality report to render output: letter grade (A-F) based on detection rate and worst drift duration, problem region listing with frame counts and durations, and actionable next-step guidance.
- When `--add-seeds` is used, the quality report includes a before/after comparison showing detection rate, max streak, and problem region count changes.
- Added post-merge gap interpolation (phase 5) to bidirectional tracker: when the runner is obstructed or undetected across a stretch, the tracker linearly interpolates the bounding box between the last detected frame before the gap and the first detected frame after the gap, producing smooth camera transitions instead of a frozen crop that jumps when detection resumes.
- Quality report now shows interpolated frame count and percentage when gap smoothing is active.

### Behavior or Interface Changes
- Removed `--use-default-config` CLI flag from `track_runner`; auto-loading the per-input config file (or creating defaults) is now the default behavior. Use `-c`/`--config` to override with a specific path.
- Changed default `detect_interval` from 4 to 1 (detect every frame). Person tracking is a hard problem and skipping frames costs more in missed detections than it saves in speed.
- Lowered velocity freeze threshold from 10 to 3 consecutive missed detections (`velocity_freeze_streak` config key). With detect_interval=1, every miss is a real detection failure so velocity should freeze faster to prevent drift.

### Fixes and Maintenance
- Fixed problem regions in quality report displaying in length order instead of chronological order.
- Quality report now shows detection hit rate (matched/attempted) instead of raw frame percentage, making it clear how often detection succeeds when it runs.

### Previous additions and new features
- Created `emwy_tools/track_runner/tracker.py` with `run_tracker()` function: forward-pass tracking loop that orchestrates Kalman prediction, YOLO detection, candidate scoring, and crop control into per-frame crop rectangles.
- Wired full tracking pipeline into `emwy_tools/track_runner/cli.py`: YOLO detector init, seed collection (interactive or saved), tracker loop, cropped video encoding, and audio muxing. Tool now produces a cropped output video following a runner.
- Added `emwy_tools/run_tool.py` dispatcher script that lists available tools or runs one by name with passthrough args.
- Renamed `tools/` to `emwy_tools/` via `git mv` for branding and clarity.
- Created `emwy_tools/tools_common.py` with shared utilities: `ensure_file_exists()`, `check_dependency()`, `run_process()`, `parse_time_seconds()`, `fps_fraction_to_float()`, `probe_video_stream()`, `probe_duration_seconds()`.
- Split `emwy_tools/silence_annotator.py` (1867 lines) into `emwy_tools/silence_annotator/` sub-package with `detection.py`, `config.py`, and `silence_annotator.py` entry point.
- Split `emwy_tools/stabilize_building.py` (2282 lines) into `emwy_tools/stabilize_building/` sub-package with `config.py`, `crop.py`, `stabilize.py`, and `stabilize_building.py` entry point.
- Created `emwy_tools/video_scruncher/` placeholder sub-package.
- Created `emwy_tools/track_runner/track_runner.py` as shebang entry point (replaces `__main__.py`).
- Moved tool tests to `emwy_tools/tests/` with shared `conftest.py`.
- Created `emwy_tools/tests/test_tools_common.py` for shared utility tests.
- Updated `source_me.sh` to add `emwy_tools/` to PYTHONPATH.

### Behavior or Interface Changes
- All tools now invoked as `source source_me.sh && python emwy_tools/<tool>/<tool>.py` instead of `source source_me.sh && python tools/<tool>.py`.
- track_runner internal imports changed from fully-qualified (`import tools.track_runner.config`) to bare sibling imports (`import config`).
- Removed duplicated utility functions from all tools; now use `tools_common.*` instead.
- Removed duplicated `format_speed()` from silence_annotator; now uses `emwy_yaml_writer.format_speed()`.

### Fixes and Maintenance
- Refreshed README.md, INSTALL.md, and USAGE.md with correct Python 3.12 version, `source source_me.sh` bootstrap commands, `emwy_tools/` paths, and curated doc links.
- Refreshed CODE_ARCHITECTURE.md and FILE_STRUCTURE.md to match current repo layout: updated test file listings, fixed stale report filenames, added `source_me.sh` and `TRACK_RUNNER_TOOL_PLAN.md`, corrected `tools/` to `emwy_tools/`.
- Fixed `emwy_yaml_writer.build_silence_timeline_yaml()` to convert fps to string before quoting (was passing float to `yaml_quote()`).
- Removed unused `yaml` import from `emwy_tools/track_runner/cli.py` and `emwy_tools/tests/test_track_runner.py`.
- Removed shebangs from library modules (non-entry-point files).
- Set executable bit on all entry point scripts.
- Updated `tests/test_render_tooling.py` and `tests/test_integration_render.py` silence_annotator paths from `tools/` to `emwy_tools/silence_annotator/`.

### Developer Tests and Notes
- YOLO weights require ultralytics pip package for initial PT-to-ONNX export; cached after first run.
- Detection tests skip gracefully when ONNX weights or test videos are unavailable.
- All 555 tests pass (4 skipped) after reorganization.

## Unreleased
- Added four section title cards to the Writing_Webwork_with_AI_Agents EMWY YAML: "ChatGPT vs WebWork" (~01:47), "Amino Acid Isoelectric Points" (~05:58), "Codex vs Claude" (~09:17), and "Comparing Results" (~15:51).
- Added `-d`/`--debug` flag to `emwy_cli.py` that writes a timestamped debug log to `emwy_cli.log`, matching the TUI's existing `-d` debug log feature.
- Added `print_warning()` to `emwylib/core/utils.py` that prints to stderr and notifies the command reporter.
- Changed `_run_mkvmerge` to print a condensed mkvmerge warning count instead of silently swallowing warnings or dumping the entire verbose stderr.
- Pinned H.264 `-profile:v high -level:v 4.1` in `_video_codec_args` and `titlecard.py` so all segments produce identical SPS/PPS codec private data, eliminating mkvmerge "codec's private data does not match" warnings during concatenation.
- Removed redundant `-filter:v 'fps=N,format=yuv420p'` from `titlecard.py` encoding; now uses direct `-r` and `-pix_fmt` consistent with all other segment types.
- Replaced underscores with spaces in silence_annotator title card text derived from filenames for readable display.
- Improved YAML loader error messages to distinguish tool config files, non-emwy files, and wrong-version projects instead of a single generic error.
- Simplified README with a short quick start and curated documentation links.
- Refreshed CODE_ARCHITECTURE and FILE_STRUCTURE docs to match current layout and entry points.
- Updated INSTALL and added USAGE docs with verified commands and known gaps.
- Fixed README quick start command to include the required YAML flag.
- Raised on failed external commands and normalized whitespace in runCmd output.
- Defaulted output video_codec to libx264 to match the v2 spec and ffmpeg availability.
- Added x264 vs x265 guidance for YouTube uploads in the v2 spec output section.
- Removed shebangs from non-executable modules and test helpers; kept tool shebangs.
- Added a python3 shebang and executable bit for tools/video_scruncher.py.
- Defaulted titlecard movie encoding to libx264 for wider ffmpeg compatibility.
- Added pytest coverage for titlecard font loading and ffmpeg command assembly.
- Aligned titlecard encoding options with renderer settings to improve mkvmerge appends.
- Cleaned unused variables flagged by pyflakes in stabilize_building.py.
- Allowed mkvmerge warnings when output files are still produced.
- Added `tools/stabilize_building.py` standalone "bird on a building" stabilization tool (vid.stab via ffmpeg) with crop-to-content and a sidecar report.
- Added optional, budgeted border fill fallback for rare jerk frames when crop-only is infeasible.
- Improved stabilize_building motion rejection reporting with per-metric thresholds, reason codes, and a one-screen stderr summary.
- Fixed stabilize_building to treat vid.stab transforms as relative when deriving global motions and applying stabilization.
- Switched stabilize_building motion rejection from strict max thresholds to a budgeted outlier model (rare bad frames allowed; rejects sustained motion/zoom/rotation).
- Added `motion.required_thresholds_to_pass` to stabilize_building reports on motion rejection failures.
- Updated stabilize_building default motion thresholds to be permissive enough to pass phone clips with occasional extreme frames (tune down after confirming pipeline).
- Added a stderr note when stabilize_building uses an existing default config file so runs do not accidentally ignore new code defaults.
- Updated stabilize_building default border fill budgets to tolerate short jerk bursts while keeping the fill fraction constrained.
- Adjusted fill fallback crop selection to meet basic constraints without forcing safe-region containment, and emit a warning (not a hard fail) when fill can reach into the safe region.
- Fixed stabilize_building audio copying to select a single usable audio stream (avoid codec-none auxiliary tracks that can break muxing).
- Changed stabilize_building config behavior: when `-c` is omitted, no config file is read or written (code defaults only); added explicit `--write-default-config` and `--use-default-config` modes.
- Documented the stabilization tool in `docs/TOOLS.md`, `docs/FILE_STRUCTURE.md`, and `tools/README.md` and aligned the stabilization plan with the implementation approach.
- Added pytest coverage for `tools/stabilize_building.py` including crop-only and fill-fallback modes using tiny synthetic clips.
- Added concrete algorithm guidance for the stabilization tool (motion parsing, frame alignment, smoothing, crop computation) and a transform-only test suite idea.
- Specified a concrete crop-rectangle derivation (intersection of per-frame valid regions) and added minimal motion-path reliability heuristics.
- Clarified crop feasibility derivation from the motion path and defined minimum failure/unreliable-analysis rules for the stabilization tool.
- Clarified the stabilization tool contract to require exactly two decode passes per analysis and to base crop feasibility on analysis metadata.
- Tightened stabilization tool plan wording to remove remaining YAML-feature drift and standardize "crop infeasible" failure language.
- Clarified the stabilization tool outputs (stabilized video + sidecar report) and failure behavior as media preparation rather than YAML editing intent.
- Decided stabilization will ship as a standalone tool (like `tools/silence_annotator.py`) instead of adding new EMWY YAML v2 authoring fields.
- Resolved remaining stabilization-plan contradictions (determinism wording, crop-only enforcement, and precise crop constraint definitions).
- Tightened stabilization plan guarantees: removed bitwise reproducibility, committed to crop-only borders, and added explicit failure thresholds and motion/zoom/subtitle rules.
- Clarified the "bird on a building" mental model: globally align to keep the building static and fail when the building leaves the usable crop.
- Tightened the stabilization plan to default to crop-to-content with explicit failure on low overlap to keep the frame center in view.
- Expanded the stabilization feature plan with vid.stab-specific notes on determinism, caching, border fill, and failure modes.
- Added `docs/STABILIZATION_TOOL_PLAN.md` (renamed from `docs/STABILIZATION_FEATURE_PLAN.md`) documenting global video stabilization guarantees and an implementation plan.
- Updated CODE_ARCHITECTURE.md with detailed component descriptions and data flow.
- Added FILE_STRUCTURE.md documenting repository layout and file organization.
- Frozen TUI elapsed time once completion is printed.
- Fixed command total estimation for animated overlay text generators.
- Colorized dashboard and project panels to match the Nord-style palette.
- Shifted TUI command highlighting to a Nord-style, low-saturation palette.
- Added overlay_text animation cycle support with `{animate}` placeholders and YAML output.
- Updated silence_annotator defaults to emit animated fast-forward overlays.
- Updated `tools/config_silence.yml` and `docs/TOOLS.md` sample config to enable animated overlays.
- Documented overlay text animation fields and added YAML writer test coverage.
- Updated demo_codex overlay templates to use animated fast-forward text.
- Added CLI-style command highlighting for emwy_tui command logs.
- Fixed overlay compositing opacity filter for recent ffmpeg colorchannelmixer parsing.
- Reset emwy_tui debug log on each run instead of appending.
- Added pytest coverage for overlay ffmpeg behaviors.
- Removed deprecated Pillow mode arguments in titlecard image creation.
- Added pytest coverage for ffmpeg/sox/mkvmerge tooling behaviors.
- Relaxed tooling test duration bounds and added minimal assets to generator tests.
- Added pytest coverage for custom font_file rendering.
- Added ETA and improved elapsed time formatting in emwy_tui metrics.
- Fixed command total estimate to include chapter muxing and surfaced command total calculation in the TUI.
- Added a COMPLETE! ASCII banner in the TUI finish state.
- Added TUI command coloring and clearer ETA updates while sampling command durations.
- Moved ETA display onto the Commands line in the TUI dashboard.
- Added unit tests for TUI ETA and duration formatting.
- Updated demo_codex overlay text style to use a boxed background and adjusted overlay opacity.
- Softened TUI command log colors for a subtler look.
- Added estimated total time to the elapsed display in the TUI dashboard.
- Removed decimals from estimated ETA/total times in the TUI dashboard.
- Rounded estimated ETA/total times up to the next whole second.
- Delay ETA display until at least 8 commands have completed.
- Update ETA estimates only after command completion and adjust remaining-time formula.
- Adjusted ETA formula to weight the last steps (remaining + 3).
- Render overlay generator cards at overlay geometry size and error on missing font files.
- Added a unit test to confirm custom font paths are used during card rendering.
- Added system font discovery helper for cross-platform font tests.
- Improved vertical centering of overlay text and card text using font bounding boxes.
- Updated AGENTS guidance with notes for future Codex runs.
- Merge batching now occurs during segment/overlay generation instead of only at the end.
- Disabled tqdm in quiet mode to avoid multiprocessing lock errors in the TUI.
- Added a debug log mode for emwy_tui.py and colorized command output when rich is available.
- Added a subprocess fallback for fds_to_keep errors during command execution.
- Added `emwy_cli.py` and moved `emwy_tui.py` to the repo root.
- Added output merge batching controls for large timelines.
- Fixed overlay transparent blanks to preserve alpha so overlays do not show black boxes.
- Added a Textual TUI wrapper for emwy renders.
- Replaced deprecated scipy.ndimage.filters import in title card rendering.
- Defaulted cache directory for temporary render files to a per-run temp dir.
- Fixed title card ffmpeg profile for libx265 to avoid zero-byte output files.
- Fixed title card image rendering to use the temp directory pattern for ffmpeg input.
- Added silence annotator trim_leading_silence/trim_trailing_silence options (default true).
- Fixed title card rendering with newer Pillow versions (getbbox fallback).
- Standardized silence annotator outputs to use `<input>.*` filenames (including extensions).
- Allowed playback styles to supply overlay_text_style defaults for overlay templates.
- Added docs/TODO.md with MLT overlay export pre-render task.
- Renamed silence annotator fast playback style id to `fast_forward`.
- Added playback_styles to apply shared speed presets to source segments.
- Added default silence annotator intro title card output.
- Enforced matching audio/video speeds on source segments.
- Added overlay_text generator and overlay_text_styles for dedicated overlay labels.
- Added overlay template apply rules so fast-forward title cards can be authored once.
- Added overlay tracks with transparent blanks and overlay rendering support.
- Added `still` generator support and transparent card backgrounds for overlays.
- Documented overlay authoring and updated Shotcut export limitations.
- Updated silence annotator YAML to include fast-forward overlays.
- Fixed pyflakes runner to avoid null-separated sort errors.
- Documented MLT interop mapping and added export test coverage.
- Added silence annotator config file support and simplified CLI flags.
- Polished silence annotator config validation and defaults handling.
- Added MLT import/export specification docs.
- Added `pyproject.toml` and `MANIFEST.in` for packaging metadata.
- Added centralized version file and release history doc.
- Expanded pyflakes runner output with categorized error counts.
- Expanded pyflakes error categorization patterns.
- Expanded pyflakes syntax error matching.
- Added output for unclassified pyflakes errors.
- Filtered pyflakes summaries to true error lines and added warning category.
- Filtered first/random/last pyflakes output to error lines only.
- Implemented MKV chapter export from segment titles.
- Reshaped README introduction to lead with the EMWY acronym and MLT compatibility.
- Clarified the EMWY acronym in the README.
- Resolved AGENTS documentation links to use `docs/` paths.
- Added `.DS_Store` to `.gitignore`.
- Fixed documentation links to `docs/PYTHON_STYLE.md`.
- Moved contributor guidance to `docs/DEVELOPMENT.md`.
- Renamed `docs/ARCHITECTURE.md` to `docs/CODE_ARCHITECTURE.md`.
- Added documentation scaffolding and agent descriptions.
- Introduced pip requirements file for development tooling.
- Documented installation, CLI usage, cookbook recipes, and troubleshooting tips.
- Added v2 sample project with `.emwy.yaml` extension and run script.
- Added MLT exporter module for v2 YAML projects.
- Split media wrappers into `emwylib/media` for ffmpeg and sox helpers.
- Added `paired_audio` expansion for generator entries when playlists are aligned.
- Made `timeline.segments` the required authoring surface; playlists/stack are compiled-only.
- Removed `take` support from v2 loader and timeline.
- Updated rendering to process and mux A/V per segment before concatenation.
- Added CLI flags for temp retention and cache directory (`--keep-temp`, `--cache-dir`).
- Added title/chapter card backgrounds (image, color, gradient) with font overrides.

## v1.0.0
- Initial public release of emwy with YAML v2 parser and CLI.
