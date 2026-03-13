"""
stabilize.py

Vidstab pipeline, ffmpeg commands, and motion analysis for stabilize_building.
"""

# Standard Library
import hashlib
import json
import os
import sys
import tempfile
import time

# PIP3 modules
import yaml

# local repo modules
import common_tools.tools_common as tools_common
import sb_crop

#============================================

def check_vidstab_filters() -> None:
	"""
	Verify ffmpeg exposes vidstabdetect and vidstabtransform filters.
	"""
	cmd = ["ffmpeg", "-hide_banner", "-filters"]
	proc = tools_common.run_process(cmd, capture_output=True)
	text = proc.stdout
	if "vidstabdetect" not in text or "vidstabtransform" not in text:
		raise RuntimeError("ffmpeg is missing vid.stab filters (vidstabdetect/vidstabtransform)")
	return

#============================================

def ffmpeg_version_fingerprint() -> dict:
	"""
	Get a minimal ffmpeg toolchain fingerprint.

	Returns:
		dict: Fingerprint fields.
	"""
	cmd = ["ffmpeg", "-hide_banner", "-version"]
	proc = tools_common.run_process(cmd, capture_output=True)
	lines = [line.strip() for line in proc.stdout.splitlines() if line.strip() != ""]
	version_line = lines[0] if len(lines) > 0 else ""
	config_line = ""
	for line in lines[:15]:
		if line.lower().startswith("configuration:"):
			config_line = line
			break
	return {
		"ffmpeg_version": version_line,
		"ffmpeg_configuration": config_line,
	}

#============================================

def file_identity(input_file: str) -> dict:
	"""
	Build an input file identity snapshot for caching and reporting.

	Args:
		input_file: Input file path.

	Returns:
		dict: Identity mapping.
	"""
	abs_path = os.path.abspath(input_file)
	stat = os.stat(abs_path)
	return {
		"path": abs_path,
		"size": int(stat.st_size),
		"mtime_ns": int(stat.st_mtime_ns),
	}

#============================================

def stable_hash_mapping(data: dict) -> str:
	"""
	Hash a mapping deterministically to a short hex string.

	Args:
		data: Mapping to hash.

	Returns:
		str: Hex digest (sha256).
	"""
	text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	return hashlib.sha256(text.encode("utf-8")).hexdigest()

#============================================

def escape_ffmpeg_filter_value(value: str) -> str:
	"""
	Escape a value for ffmpeg filter arguments.

	Args:
		value: Raw value.

	Returns:
		str: Escaped value.
	"""
	text = str(value)
	text = text.replace("\\", "\\\\")
	text = text.replace(":", "\\:")
	text = text.replace(",", "\\,")
	text = text.replace("'", "\\'")
	text = text.replace("[", "\\[")
	text = text.replace("]", "\\]")
	return text

#============================================

def rgb_hex(red: int, green: int, blue: int) -> str:
	"""
	Format an RGB triplet as a #rrggbb string.

	Args:
		red: 0..255.
		green: 0..255.
		blue: 0..255.

	Returns:
		str: Hex color string.
	"""
	r = max(0, min(255, int(red)))
	g = max(0, min(255, int(green)))
	b = max(0, min(255, int(blue)))
	return f"#{r:02x}{g:02x}{b:02x}"

#============================================

def count_frames_in_trf(trf_path: str) -> int:
	"""
	Count frames in a vid.stab transforms file by counting 'Frame ' lines.

	Args:
		trf_path: Path to .trf file.

	Returns:
		int: Frame count.
	"""
	count = 0
	with open(trf_path, "r", encoding="utf-8", errors="replace") as handle:
		for line in handle:
			if line.startswith("Frame "):
				count += 1
	if count <= 0:
		raise RuntimeError("vidstabdetect produced no frames in transforms file")
	return count

#============================================

def run_vidstabdetect(input_file: str, trf_path: str, detect: dict,
	start_seconds: float | None, duration_seconds: float | None) -> None:
	"""
	Run vidstabdetect to generate a transforms file.

	Args:
		input_file: Input media file.
		trf_path: Output transforms file path.
		detect: Detect settings mapping.
		start_seconds: Optional start seconds.
		duration_seconds: Optional duration seconds.
	"""
	cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
	if start_seconds is not None:
		cmd += ["-ss", f"{start_seconds}"]
	if duration_seconds is not None:
		cmd += ["-t", f"{duration_seconds}"]
	cmd += ["-i", input_file]
	cmd += ["-an", "-sn"]
	result_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabdetect="
		f"fileformat=ascii:"
		f"tripod={detect['reference_frame']}:"
		f"shakiness={detect['shakiness']}:"
		f"accuracy={detect['accuracy']}:"
		f"stepsize={detect['stepsize']}:"
		f"mincontrast={detect['mincontrast']}:"
		f"result={result_path}"
	)
	cmd += ["-vf", filter_text, "-f", "null", "-"]
	tools_common.run_process(cmd, capture_output=True)
	if not os.path.isfile(trf_path):
		raise RuntimeError("vidstabdetect did not produce a transforms file")
	return

#============================================

def run_global_motions_from_trf(trf_path: str, width: int, height: int, fps: float,
	frame_count: int, transform: dict, output_dir: str | None = None) -> tuple[str, dict, str]:
	"""
	Generate a global_motions.trf using vidstabtransform debug on synthetic frames.

	This avoids decoding the source media again for crop feasibility computation.

	Args:
		trf_path: Path to transforms file.
		width: Source width.
		height: Source height.
		fps: Source fps.
		frame_count: Number of frames in the range.
		transform: Transform settings mapping.

	Returns:
		tuple[str, dict, str]: (global_motions_text, debug_meta, output_path)
	"""
	temp_dir_handle = None
	temp_dir = output_dir
	if temp_dir is None:
		temp_dir_handle = tempfile.TemporaryDirectory(prefix="stabilize-build-", dir=None)
		temp_dir = temp_dir_handle.name
	os.makedirs(temp_dir, exist_ok=True)
	motions_path = os.path.join(temp_dir, "global_motions.trf")
	input_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabtransform="
		f"input={input_path}:"
		"relative=1:"
		"optzoom=0:"
		"zoom=0:"
		"crop=black:"
		f"optalgo={transform['optalgo']}:"
		f"smoothing={transform['smoothing']}:"
		"debug=1"
	)
	source_spec = f"color=black:size={width}x{height}:rate={fps}"
	cmd = [
		"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
		"-f", "lavfi", "-i", source_spec,
		"-frames:v", str(frame_count),
		"-an", "-sn",
		"-vf", filter_text,
		"-f", "null", "-",
	]
	start_time = time.time()
	tools_common.run_process(cmd, cwd=temp_dir, capture_output=True)
	elapsed = time.time() - start_time
	if not os.path.isfile(motions_path):
		raise RuntimeError("vidstabtransform debug did not produce global_motions.trf")
	with open(motions_path, "r", encoding="utf-8", errors="replace") as handle:
		text = handle.read()
	if temp_dir_handle is not None:
		temp_dir_handle.cleanup()
	return text, {
		"generated_in_seconds": elapsed,
		"frame_count": frame_count,
	}, motions_path

#============================================

def parse_global_motions_text(text: str) -> list:
	"""
	Parse global_motions.trf text into per-frame transform dicts.

	Args:
		text: global_motions.trf content.

	Returns:
		list: List of per-frame transforms.
	"""
	lines = [line.rstrip("\n") for line in text.splitlines()]
	frames = []
	i = 0
	while i < len(lines):
		line = lines[i].strip()
		i += 1
		if line == "" or line.startswith("#"):
			continue
		parts = [p for p in line.split(" ") if p != ""]
		if len(parts) < 6:
			raise RuntimeError("global_motions.trf parse error: expected 6 fields")
		try:
			dx = float(parts[1])
			dy = float(parts[2])
			angle = float(parts[3])
			zoom_percent = float(parts[4])
			flag = int(float(parts[5]))
		except ValueError as exc:
			raise RuntimeError("global_motions.trf parse error: non-numeric field") from exc
		info = {
			"dx": dx,
			"dy": dy,
			"angle": angle,
			"zoom_percent": zoom_percent,
			"flag": flag,
			"missing": False,
			"is_reference": False,
			"fields_count": None,
			"error": None,
		}
		if i < len(lines):
			next_line = lines[i].strip()
			if next_line.startswith("#"):
				i += 1
				comment = next_line[1:].strip()
				if comment.lower().startswith("no fields"):
					if len(frames) == 0:
						info["is_reference"] = True
						info["missing"] = False
					else:
						info["missing"] = True
				else:
					comment_parts = [p for p in comment.split(" ") if p != ""]
					if len(comment_parts) >= 2:
						try:
							info["error"] = float(comment_parts[0])
							info["fields_count"] = int(float(comment_parts[1]))
						except ValueError:
							pass
		frames.append(info)
	if len(frames) == 0:
		raise RuntimeError("global_motions.trf had no frame transforms")
	return frames

#============================================

def scale_ratio_from_zoom_percent(zoom_percent: float) -> float:
	"""
	Convert a zoom percentage into a scale ratio.

	Args:
		zoom_percent: Zoom in percent (0.5 means +0.5%).

	Returns:
		float: Scale ratio.
	"""
	return 1.0 + zoom_percent / 100.0

#============================================

def motion_reliability_ok(width: int, height: int, transforms: list, rejection: dict) -> tuple[bool, list, dict]:
	"""
	Check minimal motion-path reliability heuristics.

	Args:
		width: Frame width.
		height: Frame height.
		transforms: Per-frame transforms list.
		rejection: Rejection settings.

	Returns:
		tuple[bool, list, dict]: (ok, reasons, stats)
	"""
	reasons = []
	non_reference = [item for item in transforms if not item.get("is_reference")]
	missing = sum(1 for item in non_reference if item.get("missing"))
	missing_fraction = float(missing) / float(len(non_reference)) if len(non_reference) > 0 else 1.0
	dx_values = [float(item["dx"]) for item in transforms if not item.get("missing")]
	dy_values = [float(item["dy"]) for item in transforms if not item.get("missing")]
	angle_values = [float(item["angle"]) for item in transforms if not item.get("missing")]
	zoom_values = [float(item["zoom_percent"]) for item in transforms if not item.get("missing")]
	if len(dx_values) == 0 or len(dy_values) == 0:
		reasons.append("unreliable_motion_missing")
		return False, reasons, {"missing_fraction": missing_fraction}
	max_abs_angle = max(abs(v) for v in angle_values) if len(angle_values) > 0 else 0.0
	max_abs_zoom_percent = max(abs(v) for v in zoom_values) if len(zoom_values) > 0 else 0.0
	mad_dx = sb_crop.mad(dx_values)
	mad_dy = sb_crop.mad(dy_values)
	mad_tx_fraction = mad_dx / float(width)
	mad_ty_fraction = mad_dy / float(height)
	if missing_fraction > float(rejection["max_missing_fraction"]):
		reasons.append("unreliable_motion_missing")
	if mad_tx_fraction > float(rejection["max_mad_fraction"]) or mad_ty_fraction > float(rejection["max_mad_fraction"]):
		reasons.append("unreliable_motion_mad")
	max_scale_jump = 0.0
	max_abs_angle_frame = None
	max_abs_zoom_frame = None
	max_scale_jump_frame = None
	max_scale_jump_pair = None
	worst_angles = []
	worst_zooms = []
	worst_scale_jumps = []
	usable_indices = [idx for idx, item in enumerate(transforms) if not item.get("missing") and not item.get("is_reference")]
	for idx, item in enumerate(transforms):
		if item.get("missing") or item.get("is_reference"):
			continue
		worst_angles.append((idx, abs(float(item["angle"]))))
		worst_zooms.append((idx, abs(float(item["zoom_percent"]))))
	if len(worst_angles) > 0:
		worst_angles_sorted = sorted(worst_angles, key=lambda t: t[1], reverse=True)
		max_abs_angle_frame = worst_angles_sorted[0][0]
	if len(worst_zooms) > 0:
		worst_zooms_sorted = sorted(worst_zooms, key=lambda t: t[1], reverse=True)
		max_abs_zoom_frame = worst_zooms_sorted[0][0]
	for i in range(len(usable_indices) - 1):
		idx0 = usable_indices[i]
		idx1 = usable_indices[i + 1]
		s0 = scale_ratio_from_zoom_percent(float(transforms[idx0]["zoom_percent"]))
		s1 = scale_ratio_from_zoom_percent(float(transforms[idx1]["zoom_percent"]))
		if s0 <= 0:
			continue
		jump = abs((s1 / s0) - 1.0)
		worst_scale_jumps.append((idx1, jump, idx0, idx1))
		if jump > max_scale_jump:
			max_scale_jump = jump
			max_scale_jump_frame = idx1
			max_scale_jump_pair = (idx0, idx1)

	def _budget_stats(bad_set: set[int]) -> dict:
		bad_count = 0
		max_run = 0
		run = 0
		for idx in usable_indices:
			is_bad = idx in bad_set
			if is_bad:
				bad_count += 1
				run += 1
				if run > max_run:
					max_run = run
			else:
				run = 0
		total_frames = len(usable_indices)
		ratio = float(bad_count) / float(total_frames) if total_frames > 0 else 1.0
		return {
			"bad_frames": bad_count,
			"total_frames": total_frames,
			"bad_frames_ratio": ratio,
			"max_consecutive_bad_frames": max_run,
		}

	threshold_angle = float(rejection["max_abs_angle_rad"])
	threshold_zoom = float(rejection["max_abs_zoom_percent"])
	threshold_scale_jump = float(rejection["max_scale_jump"])
	angle_bad = {idx for idx, value in worst_angles if value > threshold_angle}
	zoom_bad = {idx for idx, value in worst_zooms if value > threshold_zoom}
	scale_bad = {item[0] for item in worst_scale_jumps if item[1] > threshold_scale_jump}
	angle_budget = _budget_stats(angle_bad)
	zoom_budget = _budget_stats(zoom_bad)
	scale_budget = _budget_stats(scale_bad)
	combined_bad = angle_bad | zoom_bad | scale_bad
	combined_budget = _budget_stats(combined_bad)

	mode = rejection.get("mode", "budgeted")
	outlier_max_frames_ratio = float(rejection.get("outlier_max_frames_ratio", 0.0))
	outlier_max_consecutive = int(rejection.get("outlier_max_consecutive_frames", 0))
	if mode == "max":
		if max_abs_angle > threshold_angle:
			reasons.append("unreliable_motion_angle")
		if max_abs_zoom_percent > threshold_zoom:
			reasons.append("unreliable_motion_zoom")
		if max_scale_jump > threshold_scale_jump:
			reasons.append("unreliable_motion_scale")
	else:
		if angle_budget["bad_frames_ratio"] > outlier_max_frames_ratio or angle_budget["max_consecutive_bad_frames"] > outlier_max_consecutive:
			reasons.append("unreliable_motion_angle")
		if zoom_budget["bad_frames_ratio"] > outlier_max_frames_ratio or zoom_budget["max_consecutive_bad_frames"] > outlier_max_consecutive:
			reasons.append("unreliable_motion_zoom")
		if scale_budget["bad_frames_ratio"] > outlier_max_frames_ratio or scale_budget["max_consecutive_bad_frames"] > outlier_max_consecutive:
			reasons.append("unreliable_motion_scale")

	stats = {
		"missing_fraction": missing_fraction,
		"mad_tx_fraction": mad_tx_fraction,
		"mad_ty_fraction": mad_ty_fraction,
		"max_scale_jump": max_scale_jump,
		"max_abs_angle_rad": max_abs_angle,
		"max_abs_zoom_percent": max_abs_zoom_percent,
		"max_abs_angle_frame": max_abs_angle_frame,
		"max_abs_zoom_percent_frame": max_abs_zoom_frame,
		"max_scale_jump_frame": max_scale_jump_frame,
		"max_scale_jump_pair": max_scale_jump_pair,
		"top_5_abs_angle": [
			{"frame": idx, "abs_angle_rad": value}
			for idx, value in sorted(worst_angles, key=lambda t: t[1], reverse=True)[:5]
		],
		"top_5_abs_zoom_percent": [
			{"frame": idx, "abs_zoom_percent": value}
			for idx, value in sorted(worst_zooms, key=lambda t: t[1], reverse=True)[:5]
		],
		"top_5_scale_jumps": [
			{"frame": item[0], "scale_jump": item[1], "pair": [item[2], item[3]]}
			for item in sorted(worst_scale_jumps, key=lambda t: t[1], reverse=True)[:5]
		],
		"rejection_mode": mode,
		"angle_outliers": angle_budget,
		"zoom_outliers": zoom_budget,
		"scale_jump_outliers": scale_budget,
		"combined_outliers": combined_budget,
	}
	return len(reasons) == 0, reasons, stats

#============================================

def print_unreliable_motion_summary(stats: dict, thresholds: dict, reasons: list,
	fps: float, start_seconds: float | None) -> None:
	"""
	Print a one-screen summary of the motion rejection metrics.

	Args:
		stats: Computed stats mapping.
		thresholds: Thresholds mapping.
		reasons: Rejection reason codes.
	"""
	print("FAIL unreliable motion", file=sys.stderr)
	print(f"reasons={reasons}", file=sys.stderr)
	print(
		f"missing_fraction={stats.get('missing_fraction')} (max {thresholds.get('max_missing_fraction')})",
		file=sys.stderr,
	)
	print(
		f"mad_tx/width={stats.get('mad_tx_fraction')} mad_ty/height={stats.get('mad_ty_fraction')} "
		f"(max {thresholds.get('max_mad_fraction')})",
		file=sys.stderr,
	)
	print(
		f"max_scale_jump={stats.get('max_scale_jump')} (max {thresholds.get('max_scale_jump')})",
		file=sys.stderr,
	)
	print(
		f"max_abs_angle_rad={stats.get('max_abs_angle_rad')} (max {thresholds.get('max_abs_angle_rad')})",
		file=sys.stderr,
	)
	print(
		f"max_abs_zoom_percent={stats.get('max_abs_zoom_percent')} (max {thresholds.get('max_abs_zoom_percent')})",
		file=sys.stderr,
	)
	mode = thresholds.get("mode")
	if mode == "budgeted":
		max_ratio = thresholds.get("outlier_max_frames_ratio")
		max_run = thresholds.get("outlier_max_consecutive_frames")
		angle = stats.get("angle_outliers", {})
		zoom = stats.get("zoom_outliers", {})
		scale = stats.get("scale_jump_outliers", {})
		combined = stats.get("combined_outliers", {})
		print(
			f"outlier_budget: max_frames_ratio={max_ratio} max_consecutive_frames={max_run}",
			file=sys.stderr,
		)
		print(
			f"angle_outliers: ratio={angle.get('bad_frames_ratio')} run={angle.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
		print(
			f"zoom_outliers: ratio={zoom.get('bad_frames_ratio')} run={zoom.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
		print(
			f"scale_outliers: ratio={scale.get('bad_frames_ratio')} run={scale.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
		print(
			f"any_outliers: ratio={combined.get('bad_frames_ratio')} run={combined.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
	angle_frame = stats.get("max_abs_angle_frame")
	zoom_frame = stats.get("max_abs_zoom_percent_frame")
	scale_frame = stats.get("max_scale_jump_frame")
	if angle_frame is not None:
		seconds = float(angle_frame) / float(fps) + (float(start_seconds) if start_seconds is not None else 0.0)
		print(f"max_abs_angle_frame={angle_frame} (t={seconds:.3f}s)", file=sys.stderr)
	if zoom_frame is not None:
		seconds = float(zoom_frame) / float(fps) + (float(start_seconds) if start_seconds is not None else 0.0)
		print(f"max_abs_zoom_frame={zoom_frame} (t={seconds:.3f}s)", file=sys.stderr)
	if scale_frame is not None:
		seconds = float(scale_frame) / float(fps) + (float(start_seconds) if start_seconds is not None else 0.0)
		print(f"max_scale_jump_frame={scale_frame} (t={seconds:.3f}s)", file=sys.stderr)
	return

#============================================

def write_report(report_path: str, report: dict, report_format: str) -> None:
	"""
	Write a report sidecar file.

	Args:
		report_path: Report path.
		report: Report mapping.
		report_format: "yaml" or "json".
	"""
	os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
	if report_format == "json":
		text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
	else:
		text = yaml.safe_dump(report, sort_keys=True)
	with open(report_path, "w", encoding="utf-8") as handle:
		handle.write(text)
	return

#============================================

def probe_all_streams(input_file: str) -> list:
	"""
	Probe all streams metadata using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		list: List of stream mappings.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-show_entries", "stream=index,codec_type,codec_name,codec_tag_string,channels,sample_rate,disposition",
		"-of", "json",
		input_file,
	]
	proc = tools_common.run_process(cmd, capture_output=True)
	data = json.loads(proc.stdout)
	streams = data.get("streams", [])
	if not isinstance(streams, list):
		raise RuntimeError("invalid ffprobe stream list")
	return streams

#============================================

def select_audio_stream_for_copy(streams: list) -> dict | None:
	"""
	Select an audio stream to map/copy.

	Args:
		streams: Stream mappings from ffprobe.

	Returns:
		dict | None: Selected audio stream mapping, or None.
	"""
	audio_streams = []
	for stream in streams:
		if not isinstance(stream, dict):
			continue
		if stream.get("codec_type") != "audio":
			continue
		codec_name = stream.get("codec_name")
		if codec_name is None:
			continue
		if str(codec_name).strip().lower() == "none":
			continue
		audio_streams.append(stream)
	if len(audio_streams) == 0:
		return None
	defaults = []
	for stream in audio_streams:
		disposition = stream.get("disposition", {})
		if isinstance(disposition, dict) and int(disposition.get("default", 0)) == 1:
			defaults.append(stream)
	if len(defaults) > 0:
		return defaults[0]
	return audio_streams[0]

#============================================

def render_stabilized_output(input_file: str, output_file: str, trf_path: str,
	transform: dict, crop_rect: dict, output_width: int, output_height: int,
	audio_stream: dict | None, copy_subs: bool, start_seconds: float | None,
	duration_seconds: float | None) -> None:
	"""
	Render stabilized output using vidstabtransform + crop + scale.

	Args:
		input_file: Input media file.
		output_file: Output media file.
		trf_path: Transforms file path.
		transform: Transform settings mapping.
		crop_rect: Crop rectangle dict.
		audio_stream: Selected audio stream mapping to copy, or None.
		copy_subs: Copy subtitle streams.
		start_seconds: Optional start seconds.
		duration_seconds: Optional duration seconds.
	"""
	cx = int(crop_rect["x"])
	cy = int(crop_rect["y"])
	cw = int(crop_rect["w"])
	ch = int(crop_rect["h"])
	cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
	if start_seconds is not None:
		cmd += ["-ss", f"{start_seconds}"]
	if duration_seconds is not None:
		cmd += ["-t", f"{duration_seconds}"]
	cmd += ["-i", input_file]
	cmd += ["-map", "0:v:0"]
	if audio_stream is not None:
		audio_index = int(audio_stream.get("index", -1))
		if audio_index >= 0:
			cmd += ["-map", f"0:{audio_index}"]
	if copy_subs:
		cmd += ["-map", "0:s?"]
	cmd += ["-map_metadata", "0"]
	input_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabtransform="
		f"input={input_path}:"
		"relative=1:"
		"optzoom=0:"
		"zoom=0:"
		"crop=black:"
		f"optalgo={transform['optalgo']}:"
		f"smoothing={transform['smoothing']}"
		f",crop=w={cw}:h={ch}:x={cx}:y={cy}"
		f",scale={int(output_width)}:{int(output_height)}"
	)
	cmd += ["-vf", filter_text]
	cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
	if audio_stream is not None:
		cmd += ["-c:a", "copy"]
	if copy_subs:
		cmd += ["-c:s", "copy"]
	cmd.append(output_file)
	tools_common.run_process(cmd, capture_output=True)
	if not os.path.isfile(output_file):
		raise RuntimeError("output render failed")
	return

#============================================

def render_stabilized_output_with_fill(input_file: str, output_file: str, trf_path: str,
	transform: dict, crop_rect: dict, output_width: int, output_height: int, fps: float,
	fill_color: str, fill_band_px: int, audio_stream: dict | None, copy_subs: bool,
	start_seconds: float | None, duration_seconds: float | None) -> None:
	"""
	Render stabilized output with a constant border fill color.

	This is only used in the border-fill fallback mode when crop-only is infeasible.

	Args:
		input_file: Input media file.
		output_file: Output media file.
		trf_path: Transforms file path.
		transform: Transform settings mapping.
		crop_rect: Fixed crop rectangle in source pixels.
		output_width: Output width.
		output_height: Output height.
		fps: Output fps for the fill source.
		fill_color: Fill color "#rrggbb".
		fill_band_px: Border band width in output pixels.
		audio_stream: Selected audio stream mapping to copy, or None.
		copy_subs: Copy subtitle streams.
		start_seconds: Optional start seconds.
		duration_seconds: Optional duration seconds.
	"""
	band = int(fill_band_px)
	if band < 1:
		raise RuntimeError("fill_band_px must be >= 1")
	if band * 2 >= int(output_width) or band * 2 >= int(output_height):
		raise RuntimeError("fill_band_px too large for output resolution")
	cx = int(crop_rect["x"])
	cy = int(crop_rect["y"])
	cw = int(crop_rect["w"])
	ch = int(crop_rect["h"])
	if cw <= 0 or ch <= 0:
		raise RuntimeError("invalid crop rectangle for fill mode")
	input_path = escape_ffmpeg_filter_value(trf_path)
	cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
	if start_seconds is not None:
		cmd += ["-ss", f"{start_seconds}"]
	if duration_seconds is not None:
		cmd += ["-t", f"{duration_seconds}"]
	cmd += ["-i", input_file]
	cmd += ["-f", "lavfi", "-i", f"color=c={fill_color}:size={int(output_width)}x{int(output_height)}:rate={fps}"]
	if audio_stream is not None:
		audio_index = int(audio_stream.get("index", -1))
		if audio_index >= 0:
			cmd += ["-map", f"0:{audio_index}"]
	if copy_subs:
		cmd += ["-map", "0:s?"]
	cmd += ["-map_metadata", "0"]
	center_w = int(output_width) - 2 * band
	center_h = int(output_height) - 2 * band
	filter_text = (
		f"[0:v]vidstabtransform=input={input_path}:relative=1:optzoom=0:zoom=0:crop=black:"
		f"optalgo={transform['optalgo']}:smoothing={transform['smoothing']},"
		f"crop=w={cw}:h={ch}:x={cx}:y={cy},"
		f"scale={int(output_width)}:{int(output_height)},format=rgba,split=5[v0][v1][v2][v3][v4];"
		f"[v0]crop=w={center_w}:h={center_h}:x={band}:y={band}[center];"
		f"[v1]crop=w={int(output_width)}:h={band}:x=0:y=0,colorkey=black:0.00001:0[top];"
		f"[v2]crop=w={int(output_width)}:h={band}:x=0:y={int(output_height) - band},colorkey=black:0.00001:0[bottom];"
		f"[v3]crop=w={band}:h={int(output_height)}:x=0:y=0,colorkey=black:0.00001:0[left];"
		f"[v4]crop=w={band}:h={int(output_height)}:x={int(output_width) - band}:y=0,colorkey=black:0.00001:0[right];"
		f"[1:v]format=rgba[base];"
		f"[base][left]overlay=0:0:shortest=1[t1];"
		f"[t1][right]overlay={int(output_width) - band}:0:shortest=1[t2];"
		f"[t2][top]overlay=0:0:shortest=1[t3];"
		f"[t3][bottom]overlay=0:{int(output_height) - band}:shortest=1[t4];"
		f"[t4][center]overlay={band}:{band}:shortest=1[vout]"
	)
	cmd += ["-filter_complex", filter_text]
	cmd += ["-map", "[vout]"]
	cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
	if audio_stream is not None:
		cmd += ["-c:a", "copy"]
	if copy_subs:
		cmd += ["-c:s", "copy"]
	cmd.append(output_file)
	tools_common.run_process(cmd, capture_output=True)
	if not os.path.isfile(output_file):
		raise RuntimeError("output render failed")
	return
