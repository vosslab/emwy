#!/usr/bin/env python3

"""
stabilize_building.py

Global "bird on a building" stabilization as a standalone media-prep tool.

This tool is intentionally strict:
- It performs global alignment so the reference frame (building) is static.
- It enforces a single static crop for the entire output (no per-frame crop/zoom).
- It can optionally fall back to a budgeted border fill on rare jerk frames.
- It fails if crop constraints cannot be met and fill budgets are exceeded.
"""

# Standard Library
import argparse
import math
import os

# local repo modules
import config
import crop
import stabilize
import common_tools.tools_common as tools_common

#============================================

def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed CLI args.
	"""
	parser = argparse.ArgumentParser(
		description="Stabilize 'bird on a building' footage (global align + static crop)."
	)
	parser.add_argument(
		"-i", "--input", dest="input_file", required=True,
		help="Input media file path."
	)
	parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output stabilized media file path."
	)
	parser.add_argument(
		"-c", "--config", dest="config_file", default=None,
		help="Optional config YAML path (if missing, defaults are written and then read)."
	)
	parser.add_argument(
		"--write-default-config", dest="write_default_config", action="store_true",
		help="Write the default config file for this input and exit 0."
	)
	parser.add_argument(
		"--use-default-config", dest="use_default_config", action="store_true",
		help="Read the per-input default config file (error if missing)."
	)
	parser.add_argument(
		"--start", dest="start", default=None,
		help="Optional start time (seconds or HH:MM:SS[.ms])."
	)
	parser.add_argument(
		"--duration", dest="duration", default=None,
		help="Optional duration (seconds)."
	)
	parser.add_argument(
		"--end", dest="end", default=None,
		help="Optional end time (seconds or HH:MM:SS[.ms])."
	)
	parser.add_argument(
		"--copy-subs", dest="copy_subs", action="store_true",
		help="Copy subtitle streams if present (no timing or placement edits)."
	)
	parser.add_argument(
		"--no-copy-audio", dest="copy_audio", action="store_false",
		help="Do not copy audio streams (video-only output)."
	)
	parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files under the cache directory."
	)
	parser.set_defaults(copy_audio=True)
	parser.set_defaults(copy_subs=False)
	parser.set_defaults(keep_temp=False)
	parser.set_defaults(write_default_config=False)
	parser.set_defaults(use_default_config=False)
	return parser.parse_args()

#============================================

def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	tools_common.ensure_file_exists(args.input_file)
	tools_common.check_dependency("ffmpeg")
	tools_common.check_dependency("ffprobe")
	stabilize.check_vidstab_filters()
	if args.config_file is not None and args.use_default_config:
		raise RuntimeError("use -c/--config or --use-default-config, not both")
	if args.config_file is not None and args.write_default_config:
		raise RuntimeError("use -c/--config or --write-default-config, not both")
	if args.use_default_config and args.write_default_config:
		raise RuntimeError("use --use-default-config or --write-default-config, not both")
	if args.write_default_config:
		config_path = config.default_config_path(args.input_file)
		if os.path.exists(config_path):
			raise RuntimeError(f"default config already exists: {config_path}")
		config.write_config_file(config_path, config.default_config())
		print(f"Wrote default config: {config_path}")
		return
	if args.output_file is None or str(args.output_file).strip() == "":
		raise RuntimeError("missing required -o/--output")
	start_seconds = tools_common.parse_time_seconds(args.start)
	duration_seconds = tools_common.parse_time_seconds(args.duration)
	end_seconds = tools_common.parse_time_seconds(args.end)
	if duration_seconds is not None and end_seconds is not None:
		raise RuntimeError("use --duration or --end, not both")
	if end_seconds is not None and start_seconds is None:
		raise RuntimeError("--end requires --start")
	if start_seconds is not None and start_seconds < 0:
		raise RuntimeError("--start must be >= 0")
	if duration_seconds is not None and duration_seconds <= 0:
		raise RuntimeError("--duration must be > 0")
	if end_seconds is not None and end_seconds <= 0:
		raise RuntimeError("--end must be > 0")
	if end_seconds is not None and start_seconds is not None:
		duration_seconds = float(end_seconds) - float(start_seconds)
		if duration_seconds <= 0:
			raise RuntimeError("--end must be > --start")
	config_path_file = None
	config_path_for_errors = "<code defaults>"
	config_source = "code_defaults"
	config_data = config.default_config()
	if args.use_default_config:
		config_path_file = config.default_config_path(args.input_file)
		if not os.path.exists(config_path_file):
			raise RuntimeError(f"default config not found: {config_path_file}")
		config_data = config.load_config(config_path_file)
		config_path_for_errors = config_path_file
		config_source = "default_config"
	elif args.config_file is not None:
		config_path_file = args.config_file
		config_path_for_errors = config_path_file
		if os.path.exists(config_path_file):
			config_data = config.load_config(config_path_file)
			config_source = "explicit_config"
		else:
			config.write_config_file(config_path_file, config.default_config())
			print(f"Wrote default config: {config_path_file}")
			config_data = config.load_config(config_path_file)
			config_source = "explicit_config_written"
	settings = config.build_settings(config_data, config_path_for_errors, args.input_file)
	video = tools_common.probe_video_stream(args.input_file)
	width = int(video["width"])
	height = int(video["height"])
	fps = float(video["fps"])
	min_height_px_setting = int(settings["crop"]["min_height_px"])
	min_height_ratio_setting = float(settings["crop"]["min_height_ratio"])
	effective_min_height_px = min_height_px_setting
	if effective_min_height_px <= 0:
		effective_min_height_px = int(round(float(height) * min_height_ratio_setting))
	if effective_min_height_px <= 0:
		raise RuntimeError("effective min height must be positive")
	cache_dir_raw = settings["io"]["cache_dir"]
	cache_dir = os.path.abspath(cache_dir_raw)
	os.makedirs(cache_dir, exist_ok=True)
	toolchain = stabilize.ffmpeg_version_fingerprint()
	identity = stabilize.file_identity(args.input_file)
	analysis_key = stabilize.stable_hash_mapping({
		"input": identity,
		"range": {"start": start_seconds, "duration": duration_seconds},
		"video": {"width": width, "height": height, "fps_fraction": video["fps_fraction"]},
		"detect": settings["engine"]["detect"],
		"toolchain": toolchain,
	})
	run_key = stabilize.stable_hash_mapping({
		"analysis_key": analysis_key,
		"transform": settings["engine"]["transform"],
		"crop": settings["crop"],
		"border": settings["border"],
		"rejection": settings["rejection"],
		"toolchain": toolchain,
	})
	trf_path = os.path.join(cache_dir, f"{analysis_key}.transforms.trf")
	report_path = f"{args.output_file}.stabilize_building.report.{settings['io']['report_format']}"
	config_path_abs = None
	if config_path_file is not None:
		config_path_abs = os.path.abspath(config_path_file)
	report = {
		"stabilize_building": 1,
		"config_path": config_path_abs,
		"config_source": config_source,
		"input": identity,
		"output": os.path.abspath(args.output_file),
		"range": {"start": start_seconds, "duration": duration_seconds},
		"settings": settings,
		"toolchain": toolchain,
		"cache_dir_abs": cache_dir,
		"analysis_key": analysis_key,
		"run_key": run_key,
		"result": {"pass": False, "mode": None, "message": None},
		"motion": {},
		"crop": {},
		"border": {},
		"streams": {},
		"warnings": [],
	}
	audio_stream = None
	if args.copy_audio:
		streams = stabilize.probe_all_streams(args.input_file)
		audio_stream = stabilize.select_audio_stream_for_copy(streams)
		if audio_stream is None:
			report["warnings"].append("no usable audio stream found; output will be video-only")
		if audio_stream is not None:
			disposition = audio_stream.get("disposition", {})
			default_value = 0
			if isinstance(disposition, dict):
				default_value = int(disposition.get("default", 0))
			report["streams"]["audio_selected"] = {
				"index": int(audio_stream.get("index", -1)),
				"codec_name": audio_stream.get("codec_name"),
				"codec_tag_string": audio_stream.get("codec_tag_string"),
				"channels": audio_stream.get("channels"),
				"sample_rate": audio_stream.get("sample_rate"),
				"default": default_value,
			}
	report["crop"]["effective_min_height_px"] = effective_min_height_px
	if not os.path.isfile(trf_path):
		print("Running vidstabdetect (pass 1/2): motion analysis")
		temp_trf = os.path.join(cache_dir, f"{analysis_key}.tmp.trf")
		if os.path.isfile(temp_trf):
			os.remove(temp_trf)
		stabilize.run_vidstabdetect(
			args.input_file,
			temp_trf,
			settings["engine"]["detect"],
			start_seconds,
			duration_seconds,
		)
		os.replace(temp_trf, trf_path)
	else:
		print("Cache hit: reusing motion analysis transforms")
	frame_count = stabilize.count_frames_in_trf(trf_path)
	if frame_count <= 1:
		raise RuntimeError("insufficient frames for stabilization")
	print("Computing crop feasibility from motion path")
	global_dir = None
	if args.keep_temp:
		global_dir = os.path.join(cache_dir, f"{run_key}.global_motions")
	global_text, debug_meta, global_path = stabilize.run_global_motions_from_trf(
		trf_path, width, height, fps, frame_count, settings["engine"]["transform"], output_dir=global_dir
	)
	if args.keep_temp:
		report["motion"]["global_motions_path"] = global_path
	report["motion"]["global_motions_driver"] = {
		"width": width,
		"height": height,
		"fps": fps,
		"frame_count": frame_count,
	}
	transforms = stabilize.parse_global_motions_text(global_text)
	report["motion"]["frame_count"] = len(transforms)
	report["motion"]["debug_meta"] = debug_meta
	ok_motion, motion_reasons, motion_stats = stabilize.motion_reliability_ok(
		width, height, transforms, settings["rejection"]
	)
	motion_thresholds = {
		"mode": settings["rejection"]["mode"],
		"max_missing_fraction": settings["rejection"]["max_missing_fraction"],
		"max_mad_fraction": settings["rejection"]["max_mad_fraction"],
		"max_scale_jump": settings["rejection"]["max_scale_jump"],
		"max_abs_angle_rad": settings["rejection"]["max_abs_angle_rad"],
		"max_abs_zoom_percent": settings["rejection"]["max_abs_zoom_percent"],
		"outlier_max_frames_ratio": settings["rejection"]["outlier_max_frames_ratio"],
		"outlier_max_consecutive_frames": settings["rejection"]["outlier_max_consecutive_frames"],
	}
	report["motion"]["stats"] = motion_stats
	report["motion"]["thresholds"] = motion_thresholds
	report["motion"]["rejection"] = {
		"pass": bool(ok_motion),
		"reasons": motion_reasons,
	}
	if not ok_motion:
		failure_code = "unreliable_motion_multiple"
		if len(motion_reasons) == 1:
			failure_code = motion_reasons[0]
		combined = motion_stats.get("combined_outliers", {})
		required = {
			"max_abs_angle_rad": motion_stats.get("max_abs_angle_rad"),
			"max_abs_zoom_percent": motion_stats.get("max_abs_zoom_percent"),
			"max_scale_jump": motion_stats.get("max_scale_jump"),
			"outlier_frames_ratio": combined.get("bad_frames_ratio"),
			"outlier_max_consecutive_frames": combined.get("max_consecutive_bad_frames"),
		}
		report["motion"]["required_thresholds_to_pass"] = required
		report["result"]["pass"] = False
		report["result"]["mode"] = "motion_rejection"
		report["result"]["message"] = failure_code
		stabilize.write_report(report_path, report, settings["io"]["report_format"])
		stabilize.print_unreliable_motion_summary(motion_stats, motion_thresholds, motion_reasons, fps, start_seconds)
		raise RuntimeError(failure_code)
	crop_rect = crop.compute_static_crop(width, height, transforms)
	report["crop"]["crop_to_content_rect"] = crop_rect
	if crop_rect["w"] > 0 and crop_rect["h"] > 0:
		report["crop"]["crop_to_content_area_ratio"] = (
			(float(crop_rect["w"]) * float(crop_rect["h"])) / (float(width) * float(height))
		)
		report["crop"]["crop_to_content_zoom_factor"] = float(width) / float(crop_rect["w"])
	ok_crop, crop_reasons = crop.crop_constraints_ok(
		width, height, crop_rect,
		settings["crop"]["min_area_ratio"],
		effective_min_height_px,
		settings["crop"]["center_safe_margin"],
	)
	if not ok_crop:
		border_mode = settings["border"]["mode"]
		report["crop"]["crop_to_content_reasons"] = crop_reasons
		report["border"]["mode"] = border_mode
		if border_mode != "crop_prefer_fill_fallback":
			report["result"]["pass"] = False
			report["result"]["mode"] = "crop_only"
			report["result"]["message"] = "crop infeasible"
			stabilize.write_report(report_path, report, settings["io"]["report_format"])
			raise RuntimeError("global stabilization unsuitable for this material (crop infeasible)")
		fill = settings["border"]["fill"]
		fill_crop_rect = crop_rect
		ok_fill_crop, fill_crop_reasons = crop.crop_basic_constraints_ok(
			width,
			height,
			fill_crop_rect,
			settings["crop"]["min_area_ratio"],
			effective_min_height_px,
		)
		if not ok_fill_crop:
			fill_crop_rect = crop.compute_minimum_centered_crop(
				width,
				height,
				settings["crop"]["min_area_ratio"],
				effective_min_height_px,
			)
			ok_fill_crop, fill_crop_reasons = crop.crop_basic_constraints_ok(
				width,
				height,
				fill_crop_rect,
				settings["crop"]["min_area_ratio"],
				effective_min_height_px,
			)
		report["crop"]["fill_crop_rect"] = fill_crop_rect
		if not ok_fill_crop:
			report["result"]["pass"] = False
			report["result"]["mode"] = "fill_fallback"
			report["result"]["message"] = "fill crop infeasible"
			report["crop"]["fill_crop_reasons"] = fill_crop_reasons
			stabilize.write_report(report_path, report, settings["io"]["report_format"])
			raise RuntimeError("global stabilization unsuitable for this material (fill crop infeasible)")
		fill_stats = crop.compute_fill_budget(
			transforms,
			width,
			height,
			fill_crop_rect,
			fill["max_area_ratio"],
			fill["max_frames_ratio"],
			fill["max_consecutive_frames"],
		)
		report["border"]["fill_budget"] = fill_stats
		zoom_factor = float(width) / float(fill_crop_rect["w"]) if fill_crop_rect["w"] > 0 else 1.0
		max_gap_out = float(fill_stats.get("max_gap_px", 0.0)) * zoom_factor
		fill_band_px = int(math.ceil(max_gap_out)) + 2
		report["border"]["fill_band_px"] = fill_band_px
		safe_margin_px = float(min(width, height)) * float(settings["crop"]["center_safe_margin"])
		report["border"]["safe_margin_px"] = safe_margin_px
		if float(fill_band_px) > safe_margin_px:
			report["warnings"].append("fill band exceeds center_safe_margin; fill may reach into the safe region")
		if not bool(fill_stats.get("pass")):
			report["result"]["pass"] = False
			report["result"]["mode"] = "fill_fallback"
			report["result"]["message"] = "fill budget exceeded"
			stabilize.write_report(report_path, report, settings["io"]["report_format"])
			raise RuntimeError("global stabilization unsuitable for this material (fill budget exceeded)")
		fill_color_info = crop.compute_center_patch_median_color(
			args.input_file,
			width,
			height,
			start_seconds,
			duration_seconds,
			fill["patch_fraction"],
			fill["sample_frames"],
		)
		report["border"]["fill_color"] = fill_color_info
		report["crop"]["rect"] = fill_crop_rect
		if args.copy_subs:
			report["warnings"].append("subtitles copied unchanged; crop may remove visible subtitle regions")
		print("Running vidstabtransform (pass 2/2): stabilize + crop + fill + encode")
		stabilize.render_stabilized_output_with_fill(
			args.input_file,
			args.output_file,
			trf_path,
			settings["engine"]["transform"],
			fill_crop_rect,
			width,
			height,
			fps,
			fill_color_info["color"],
			fill_band_px,
			audio_stream,
			args.copy_subs,
			start_seconds,
			duration_seconds,
		)
		report["result"]["pass"] = True
		report["result"]["mode"] = "fill_fallback"
		report["result"]["message"] = "ok"
		stabilize.write_report(report_path, report, settings["io"]["report_format"])
		return
	if args.copy_subs:
		report["warnings"].append("subtitles copied unchanged; crop may remove visible subtitle regions")
	print("Running vidstabtransform (pass 2/2): stabilize + crop + encode")
	report["border"]["mode"] = settings["border"]["mode"]
	report["crop"]["rect"] = crop_rect
	stabilize.render_stabilized_output(
		args.input_file,
		args.output_file,
		trf_path,
		settings["engine"]["transform"],
		crop_rect,
		width,
		height,
		audio_stream,
		args.copy_subs,
		start_seconds,
		duration_seconds,
	)
	report["result"]["pass"] = True
	report["result"]["mode"] = "crop_only"
	report["result"]["message"] = "ok"
	stabilize.write_report(report_path, report, settings["io"]["report_format"])
	return

#============================================

if __name__ == "__main__":
	main()
