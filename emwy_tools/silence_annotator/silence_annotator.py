#!/usr/bin/env python3

"""
silence_annotator.py

Analyze a video or audio file and identify time ranges of silence versus content.
Outputs machine-readable timestamps, including optional EMWY v2 YAML.
"""

# Standard Library
import argparse
import decimal
import os

# PIP3 modules
import numpy

# local repo modules
import config
import detection
import emwy_yaml_writer
import tools_common

#============================================

def parse_args():
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed command-line arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Detect silence ranges in a video or audio file using Python audio."
	)
	parser.add_argument(
		'-i', '--input', dest='input_file', required=True,
		help="Input video file path."
	)
	parser.add_argument(
		'-a', '--audio', dest='audio_file', default=None,
		help="Optional wav file path to skip extraction."
	)
	parser.add_argument(
		'-k', '--keep-wav', dest='keep_wav', action='store_true',
		help="Keep extracted wav file."
	)
	parser.add_argument(
		'-K', '--no-keep-wav', dest='keep_wav', action='store_false',
		help="Remove extracted wav file after analysis."
	)
	parser.add_argument(
		'-d', '--debug', dest='debug', action='store_true',
		help="Enable verbose debug output and write a debug file."
	)
	parser.add_argument(
		'-c', '--config', dest='config_file', default=None,
		help="Path to a silence annotator config YAML."
	)
	parser.add_argument(
		'-l', '--trim-leading-silence', dest='trim_leading_silence',
		help="Trim leading silence from output.",
		action='store_true'
	)
	parser.add_argument(
		'-L', '--keep-leading-silence', dest='trim_leading_silence',
		help="Keep leading silence in output.",
		action='store_false'
	)
	parser.add_argument(
		'-t', '--trim-trailing-silence', dest='trim_trailing_silence',
		help="Trim trailing silence from output.",
		action='store_true'
	)
	parser.add_argument(
		'-T', '--keep-trailing-silence', dest='trim_trailing_silence',
		help="Keep trailing silence in output.",
		action='store_false'
	)
	parser.add_argument(
		'-e', '--trim-edge-silence', dest='trim_edge_silence',
		help=argparse.SUPPRESS,
		action='store_true'
	)
	parser.add_argument(
		'-E', '--keep-edge-silence', dest='trim_edge_silence',
		help=argparse.SUPPRESS,
		action='store_false'
	)
	parser.add_argument(
		'-s', '--min-silence', dest='min_silence', type=float, default=None,
		help="Override minimum silence seconds."
	)
	parser.add_argument(
		'-m', '--min-content', dest='min_content', type=float, default=None,
		help="Override minimum content seconds."
	)
	parser.add_argument(
		'-S', '--silence-speed', dest='silence_speed', type=float, default=None,
		help="Override silence speed multiplier."
	)
	parser.add_argument(
		'-C', '--content-speed', dest='content_speed', type=float, default=None,
		help="Override content speed multiplier."
	)
	parser.add_argument(
		'-N', '--no-fast-forward-overlay', dest='fast_forward_overlay',
		help="Disable fast-forward overlay text.",
		action='store_false'
	)
	parser.set_defaults(keep_wav=False)
	parser.set_defaults(fast_forward_overlay=None)
	parser.set_defaults(debug=False)
	parser.set_defaults(trim_edge_silence=None)
	parser.set_defaults(trim_leading_silence=None)
	parser.set_defaults(trim_trailing_silence=None)
	args = parser.parse_args()
	return args

#============================================

def merge_segments(segments: list, gap_threshold: float = 0.0) -> list:
	"""
	Merge overlapping or adjacent segments.

	Args:
		segments: List of segments with start/end.
		gap_threshold: Merge segments when gap is less than or equal to this.

	Returns:
		list: Merged segments.
	"""
	if len(segments) == 0:
		return []
	sorted_segments = sorted(segments, key=lambda item: item['start'])
	merged = []
	current = {
		'start': sorted_segments[0]['start'],
		'end': sorted_segments[0]['end'],
	}
	for segment in sorted_segments[1:]:
		gap = segment['start'] - current['end']
		if gap <= gap_threshold:
			if segment['end'] > current['end']:
				current['end'] = segment['end']
		else:
			current['duration'] = current['end'] - current['start']
			merged.append(current)
			current = {'start': segment['start'], 'end': segment['end']}
	current['duration'] = current['end'] - current['start']
	merged.append(current)
	return merged

#============================================

def clamp_segments(segments: list, duration: float) -> list:
	"""
	Clamp segment start and end times to the audio duration.

	Args:
		segments: List of segments with start/end.
		duration: Total audio duration.

	Returns:
		list: Clamped segments.
	"""
	clamped = []
	for segment in segments:
		start = max(0.0, segment['start'])
		end = min(duration, segment['end'])
		if end <= start:
			continue
		clamped.append({
			'start': start,
			'end': end,
			'duration': end - start,
		})
	return clamped

#============================================

def normalize_silences(silences: list, duration: float,
	min_silence: float, min_content: float) -> list:
	"""
	Normalize silence segments with minimum duration and gap rules.

	Args:
		silences: List of silence segments.
		duration: Total audio duration.
		min_silence: Minimum silence duration.
		min_content: Minimum content duration between silences.

	Returns:
		list: Normalized silence segments.
	"""
	silences = clamp_segments(silences, duration)
	silences = merge_segments(silences, gap_threshold=0.0)
	if min_silence > 0:
		silences = [seg for seg in silences if seg['duration'] >= min_silence]
	if len(silences) == 0:
		return []
	if min_content > 0:
		if silences[0]['start'] < min_content:
			silences[0]['start'] = 0.0
		if (duration - silences[-1]['end']) < min_content:
			silences[-1]['end'] = duration
		silences = merge_segments(silences, gap_threshold=min_content)
		silences = clamp_segments(silences, duration)
	return silences

#============================================

def trim_leading_trailing_silences(silences: list, duration: float,
	trim_leading: bool = True, trim_trailing: bool = True) -> list:
	"""
	Remove leading/trailing silence segments that touch the bounds.

	Args:
		silences: List of silence segments.
		duration: Total audio duration.

	Returns:
		list: Trimmed silence segments.
	"""
	if len(silences) == 0:
		return silences
	epsilon = 0.0001
	trimmed = list(silences)
	if trim_leading and trimmed and trimmed[0]['start'] <= epsilon:
		trimmed = trimmed[1:]
	if trim_trailing and trimmed and trimmed[-1]['end'] >= (duration - epsilon):
		trimmed = trimmed[:-1]
	return trimmed

#============================================

def compute_contents(silences: list, duration: float) -> list:
	"""
	Compute content segments as the complement of silence.

	Args:
		silences: List of silence segments.
		duration: Total audio duration.

	Returns:
		list: Content segments with start/end/duration.
	"""
	if len(silences) == 0:
		return [{'start': 0.0, 'end': duration, 'duration': duration}]
	contents = []
	current = 0.0
	for silence in silences:
		if silence['start'] > current:
			contents.append({
				'start': current,
				'end': silence['start'],
				'duration': silence['start'] - current,
			})
		current = silence['end']
	if current < duration:
		contents.append({
			'start': current,
			'end': duration,
			'duration': duration - current,
		})
	return contents

#============================================

def seconds_to_millis(seconds: float) -> int:
	"""
	Convert seconds to integer milliseconds using half-up rounding.

	Args:
		seconds: Time in seconds.

	Returns:
		int: Time in milliseconds.
	"""
	value = decimal.Decimal(str(seconds))
	millis = value * decimal.Decimal(1000)
	millis = millis.quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP)
	result = int(millis)
	if result < 0:
		result = 0
	return result

#============================================

def format_timestamp(seconds: float) -> str:
	"""
	Format seconds as HH:MM:SS.mmm.

	Args:
		seconds: Time in seconds.

	Returns:
		str: Formatted timestamp.
	"""
	total_millis = seconds_to_millis(seconds)
	hours = total_millis // 3600000
	remainder = total_millis % 3600000
	minutes = remainder // 60000
	remainder = remainder % 60000
	seconds_part = remainder // 1000
	millis_part = remainder % 1000
	return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}.{millis_part:03d}"

#============================================

def add_timecodes(segments: list) -> list:
	"""
	Add timecode strings to segments.

	Args:
		segments: List of segments.

	Returns:
		list: Segments with timecode fields.
	"""
	decorated = []
	for segment in segments:
		segment_copy = dict(segment)
		segment_copy['start_tc'] = format_timestamp(segment['start'])
		segment_copy['end_tc'] = format_timestamp(segment['end'])
		segment_copy['duration_tc'] = format_timestamp(segment['duration'])
		decorated.append(segment_copy)
	return decorated

#============================================

def build_segment_list(silences: list, contents: list) -> list:
	"""
	Build an ordered segment list with kind labels.

	Args:
		silences: Silence segments with timecodes.
		contents: Content segments with timecodes.

	Returns:
		list: Ordered segments with kind.
	"""
	segments = []
	for segment in silences:
		item = dict(segment)
		item['kind'] = 'silence'
		segments.append(item)
	for segment in contents:
		item = dict(segment)
		item['kind'] = 'content'
		segments.append(item)
	segments.sort(key=lambda entry: entry['start'])
	return segments

#============================================

def default_output_path(input_file: str) -> str:
	"""
	Build a default output report path.

	Args:
		input_file: Input file path.

	Returns:
		str: Output file path.
	"""
	return f"{input_file}.emwy.yaml"

#============================================

def default_debug_path(input_file: str) -> str:
	"""
	Build a default debug output path.

	Args:
		input_file: Input file path.

	Returns:
		str: Debug output file path.
	"""
	return f"{input_file}.silence.debug.txt"

#============================================

def default_plot_path(input_file: str) -> str:
	"""
	Build a default debug plot path.

	Args:
		input_file: Input file path.

	Returns:
		str: Debug plot path.
	"""
	return f"{input_file}.silence.debug.png"

#============================================

def default_output_media_path(input_file: str) -> str:
	"""
	Build a default output media path for EMWY YAML.

	Args:
		input_file: Input file path.

	Returns:
		str: Output media file path.
	"""
	base, _ = os.path.splitext(input_file)
	return f"{base}.silencefast.mkv"

#============================================

def write_yaml_report(output_file: str, yaml_text: str) -> None:
	"""
	Write report to YAML.

	Args:
		output_file: YAML output path.
		yaml_text: YAML content.
	"""
	with open(output_file, 'w', encoding='utf-8') as handle:
		handle.write(yaml_text)
	return

#============================================

def write_text_report(output_file: str, text: str) -> None:
	"""
	Write text to a file.

	Args:
		output_file: Output file path.
		text: Text to write.
	"""
	with open(output_file, 'w', encoding='utf-8') as handle:
		handle.write(text)
	return

#============================================

def write_debug_plot(output_file: str, frame_db: numpy.ndarray,
	smooth_db: numpy.ndarray, threshold_db: float, frame_seconds: float,
	hop_seconds: float) -> None:
	"""
	Write a debug loudness plot.

	Args:
		output_file: Output plot path.
		frame_db: Frame dBFS values.
		threshold_db: Silence threshold in dBFS.
		frame_seconds: Frame window size in seconds.
		hop_seconds: Hop size in seconds.
	"""
	if frame_db.size == 0:
		return
	try:
		import matplotlib.pyplot as pyplot
	except ImportError as exc:
		raise RuntimeError("matplotlib is required for --debug plots") from exc
	times = numpy.arange(frame_db.size) * hop_seconds + (frame_seconds * 0.5)
	plotter = pyplot
	plotter.figure(figsize=(12, 4))
	plotter.plot(times, frame_db, linewidth=0.6, alpha=0.4, label="raw")
	if smooth_db is not None and smooth_db.size == frame_db.size:
		plotter.plot(times, smooth_db, linewidth=1.0, label="smooth")
	plotter.axhline(threshold_db, color='red', linestyle='--', linewidth=1.0)
	plotter.xlabel("Seconds")
	plotter.ylabel("dBFS")
	plotter.title("Frame RMS Loudness")
	plotter.legend(loc="upper right")
	plotter.tight_layout()
	plotter.savefig(output_file)
	plotter.close()
	return

#============================================

def print_debug_summary(args: argparse.Namespace, audio_path: str,
	temp_wav: str, output_file: str, output_media_file: str,
	raw_silences: list, silences: list, contents: list,
	scan_stats: dict = None, auto_attempts: list = None,
	threshold_used: float = None, debug_plot: str = None,
	threshold_db: float = None, min_silence: float = None,
	min_content: float = None) -> None:
	"""
	Print verbose debug summary.

	Args:
		args: Parsed arguments.
		audio_path: Audio file path.
		temp_wav: Temporary wav path if created.
		output_file: YAML report path.
		output_media_file: Output media file in YAML.
		raw_silences: Silence ranges before normalization.
		silences: Normalized silence ranges.
		contents: Content ranges.
		scan_stats: Wav scan stats.
		auto_attempts: Auto threshold attempts.
		threshold_used: Effective threshold.
	"""
	print("")
	print("Debug")
	print(f"Audio path: {audio_path}")
	print(f"Temp wav: {temp_wav if temp_wav is not None else '[none]'}")
	print(f"Keep wav: {args.keep_wav}")
	print("Channels: mono (forced)")
	if threshold_db is not None:
		print(f"Threshold dB: {threshold_db:.2f}")
	if threshold_used is not None and threshold_db is not None:
		if threshold_used != threshold_db:
			print(f"Threshold used: {threshold_used:.2f} (auto)")
	if min_silence is not None:
		print(f"Min silence: {min_silence:.3f}")
	if min_content is not None:
		print(f"Min content: {min_content:.3f}")
	print(f"Raw silence ranges: {len(raw_silences)}")
	print(f"Normalized silence ranges: {len(silences)}")
	print(f"Content ranges: {len(contents)}")
	if scan_stats is not None:
		rms_db = detection.amplitude_to_db(scan_stats.get('rms_amp'))
		max_db = detection.amplitude_to_db(scan_stats.get('max_amp'))
		if rms_db is not None:
			print(f"RMS amplitude dB: {rms_db:.2f}")
		if max_db is not None:
			print(f"Max amplitude dB: {max_db:.2f}")
		print("Silence scan:")
		print(f"  Threshold int: {scan_stats['threshold_int']}")
		print(f"  Frame seconds: {scan_stats['frame_seconds']:.3f}")
		print(f"  Hop seconds: {scan_stats['hop_seconds']:.3f}")
		print(f"  Frame count: {scan_stats['frame_count']}")
		print(f"  Smooth frames: {scan_stats['smooth_frames']}")
		print(f"  Below frames: {scan_stats['below_frames']} "
			f"({scan_stats['below_pct']:.2f}%)")
		print(f"  Longest run: {scan_stats['longest_run_sec']:.3f}s")
		print(f"  Runs >= min: {scan_stats['runs_over_min']}")
	if auto_attempts is not None and len(auto_attempts) > 0:
		print("Auto threshold attempts:")
		for attempt in auto_attempts:
			print(f"  {attempt['threshold_db']:.2f} "
				f"raw:{attempt['raw_count']} "
				f"norm:{attempt['normalized_count']}")
	print(f"Report file: {output_file}")
	print(f"Output media: {output_media_file}")
	if debug_plot is not None:
		print(f"Debug plot: {debug_plot}")
	print("")
	return

#============================================

def print_summary(input_file: str, duration: float, silences: list,
	contents: list, output_file: str,
	silence_speed: float, content_speed: float,
	debug_file: str = None, debug_plot: str = None,
	threshold_used: float = None, threshold_initial: float = None) -> None:
	"""
	Print a human-readable summary.

	Args:
		input_file: Input file path.
		duration: Total audio duration.
		silences: Silence segments.
		contents: Content segments.
		output_file: Output report path.
	"""
	silence_total = sum(seg['duration'] for seg in silences)
	content_total = sum(seg['duration'] for seg in contents)
	if duration > 0:
		silence_pct = (silence_total / duration) * 100.0
		content_pct = (content_total / duration) * 100.0
	else:
		silence_pct = 0.0
		content_pct = 0.0
	print("")
	print("Silence Annotator Summary")
	print(f"Input: {input_file}")
	print(f"Duration: {format_timestamp(duration)} ({duration:.3f}s)")
	print(f"Silence: {format_timestamp(silence_total)} ({silence_pct:.2f}%)")
	print(f"Content: {format_timestamp(content_total)} ({content_pct:.2f}%)")
	print(f"Silence ranges: {len(silences)}")
	print(f"Content ranges: {len(contents)}")
	print(f"Report: {output_file}")
	if debug_file is not None:
		print(f"Debug file: {debug_file}")
	if debug_plot is not None:
		print(f"Debug plot: {debug_plot}")
	if threshold_used is not None and threshold_initial is not None:
		if threshold_used != threshold_initial:
			print(f"Threshold used: {threshold_used:.2f} (auto)")
	print(f"Silence speed: {emwy_yaml_writer.format_speed(silence_speed)}")
	print(f"Content speed: {emwy_yaml_writer.format_speed(content_speed)}")
	print("")
	return

#============================================

def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	tools_common.ensure_file_exists(args.input_file)
	if args.audio_file is not None:
		tools_common.ensure_file_exists(args.audio_file)
	config_path = args.config_file
	if config_path is None:
		config_path = config.default_config_path(args.input_file)
	if not os.path.exists(config_path):
		config.write_config_file(config_path, config.default_config())
		print(f"Wrote default config: {config_path}")
	loaded_config = config.load_config(config_path)
	settings = config.build_settings(loaded_config, config_path)
	if args.trim_edge_silence is not None:
		if args.trim_leading_silence is None:
			settings['trim_leading_silence'] = args.trim_edge_silence
		if args.trim_trailing_silence is None:
			settings['trim_trailing_silence'] = args.trim_edge_silence
	if args.trim_leading_silence is not None:
		settings['trim_leading_silence'] = args.trim_leading_silence
	if args.trim_trailing_silence is not None:
		settings['trim_trailing_silence'] = args.trim_trailing_silence
	if args.min_silence is not None:
		settings['min_silence'] = args.min_silence
	if args.min_content is not None:
		settings['min_content'] = args.min_content
	if args.silence_speed is not None:
		settings['silence_speed'] = args.silence_speed
	if args.content_speed is not None:
		settings['content_speed'] = args.content_speed
	if args.fast_forward_overlay is False:
		settings['overlay_enabled'] = False
	if settings['threshold_db'] > 0:
		raise RuntimeError("threshold must be 0 or negative dBFS")
	if settings['min_silence'] <= 0:
		raise RuntimeError("min_silence must be positive")
	if settings['min_content'] <= 0:
		raise RuntimeError("min_content must be positive")
	if settings['silence_speed'] <= 0:
		raise RuntimeError("silence_speed must be positive")
	if settings['content_speed'] <= 0:
		raise RuntimeError("content_speed must be positive")
	if settings['title_card_enabled']:
		if settings['title_card_duration'] <= 0:
			raise RuntimeError("title_card duration must be positive")
		if settings['title_card_font_size'] <= 0:
			raise RuntimeError("title_card font_size must be positive")
	overlay_geometry = None
	if settings['overlay_enabled']:
		overlay_geometry = settings['overlay_geometry']
		if settings['overlay_opacity'] < 0 or settings['overlay_opacity'] > 1:
			raise RuntimeError("fast_forward_opacity must be between 0 and 1")
		if settings['overlay_font_size'] <= 0:
			raise RuntimeError("fast_forward_font_size must be positive")
	if settings['frame_seconds'] <= 0:
		raise RuntimeError("frame_seconds must be positive")
	if settings['hop_seconds'] <= 0:
		raise RuntimeError("hop_seconds must be positive")
	if settings['smooth_frames'] <= 0:
		raise RuntimeError("smooth_frames must be positive")
	if settings['hop_seconds'] > settings['frame_seconds']:
		raise RuntimeError("hop_seconds must be <= frame_seconds")
	needs_ffmpeg = args.audio_file is None
	if needs_ffmpeg:
		tools_common.check_dependency("ffmpeg")
	tools_common.check_dependency("ffprobe")
	temp_wav = None
	audio_path = args.audio_file
	if audio_path is None:
		temp_wav = detection.make_temp_wav()
		audio_path = detection.extract_audio(args.input_file, temp_wav)
	else:
		audio_ext = os.path.splitext(audio_path)[1].lower()
		if audio_ext not in ('.wav', '.wave'):
			raise RuntimeError("audio_file must be wav when using --audio")
	audio_duration = detection.get_wav_duration_seconds(audio_path)
	raw_silences, scan_stats = detection.scan_wav_for_silence(
		audio_path, settings['threshold_db'], settings['min_silence'],
		settings['frame_seconds'], settings['hop_seconds'],
		settings['smooth_frames'], include_series=args.debug
	)
	silences = normalize_silences(raw_silences, audio_duration,
		settings['min_silence'], settings['min_content'])
	if settings['trim_leading_silence'] or settings['trim_trailing_silence']:
		silences = trim_leading_trailing_silences(silences, audio_duration,
			settings['trim_leading_silence'], settings['trim_trailing_silence'])
	threshold_used = settings['threshold_db']
	auto_attempts = []
	if settings['auto_threshold'] and len(silences) == 0:
		auto_result = detection.auto_find_silence(audio_path, audio_duration,
			settings['threshold_db'], settings['min_silence'],
			settings['min_content'], settings['frame_seconds'],
			settings['hop_seconds'], settings['smooth_frames'],
			settings['auto_step_db'], settings['auto_max_db'],
			settings['auto_max_tries'])
		auto_attempts = auto_result['attempts']
		if auto_result['found']:
			raw_silences = auto_result['raw_silences']
			silences = auto_result['silences']
			scan_stats = auto_result['scan_stats']
			threshold_used = auto_result['threshold_db']
			if args.debug and 'frame_db' not in scan_stats:
				raw_silences, scan_stats = detection.scan_wav_for_silence(
					audio_path, threshold_used, settings['min_silence'],
					settings['frame_seconds'], settings['hop_seconds'],
					settings['smooth_frames'],
					include_series=True
				)
				silences = normalize_silences(raw_silences, audio_duration,
					settings['min_silence'], settings['min_content'])
	debug_file = None
	plot_file = None
	if args.debug:
		debug_file = default_debug_path(args.input_file)
		plot_file = default_plot_path(args.input_file)
		debug_text = detection.build_debug_report(audio_path, settings['threshold_db'],
			settings['min_silence'], scan_stats, auto_attempts, threshold_used)
		write_text_report(debug_file, debug_text)
		write_debug_plot(plot_file, scan_stats.get('frame_db', numpy.array([])),
			scan_stats.get('smooth_db'), threshold_used,
			scan_stats['frame_seconds'], scan_stats['hop_seconds'])
	contents = compute_contents(silences, audio_duration)
	silences = add_timecodes(silences)
	contents = add_timecodes(contents)
	segments = build_segment_list(silences, contents)
	output_file = default_output_path(args.input_file)
	output_media_file = default_output_media_path(args.input_file)
	intro_title = None
	if settings['title_card_enabled']:
		base_name = os.path.splitext(os.path.basename(args.input_file))[0]
		# replace underscores with spaces for readable title card text
		display_name = base_name.replace("_", " ")
		intro_title = settings['title_card_text'].replace("{name}", display_name)
	video_meta = tools_common.probe_video_stream(args.input_file)
	audio_meta = detection.probe_audio_stream(args.input_file)
	profile = {
		'fps': video_meta['fps'],
		'width': video_meta['width'],
		'height': video_meta['height'],
		'sample_rate': audio_meta['sample_rate'],
		'channels': 'mono',
	}
	yaml_text = emwy_yaml_writer.build_silence_timeline_yaml(
		args.input_file, output_media_file, profile, "source",
		segments,
		settings['silence_speed'], settings['content_speed'],
		overlay_text_template=settings['overlay_text'] if settings['overlay_enabled'] else None,
		overlay_animate=settings['overlay_animate'] if settings['overlay_enabled'] else None,
		overlay_geometry=overlay_geometry,
		overlay_opacity=settings['overlay_opacity'],
		overlay_font_size=settings['overlay_font_size'],
		overlay_text_color=settings['overlay_text_color'],
		intro_title=intro_title,
		intro_duration=settings['title_card_duration'],
		intro_font_size=settings['title_card_font_size'],
		intro_text_color=settings['title_card_text_color'],
		playback_styles={
			'content': settings['content_speed'],
			'fast_forward': settings['silence_speed'],
		},
		segment_style_map={
			'content': 'content',
			'silence': 'fast_forward',
		},
		overlay_apply_style="fast_forward",
	)
	write_yaml_report(output_file, yaml_text)
	if args.debug:
		print_debug_summary(args, audio_path, temp_wav, output_file,
			output_media_file, raw_silences, silences, contents, scan_stats,
			auto_attempts, threshold_used, plot_file,
			threshold_db=settings['threshold_db'],
			min_silence=settings['min_silence'],
			min_content=settings['min_content'])
	print_summary(args.input_file, audio_duration, silences, contents, output_file,
		settings['silence_speed'], settings['content_speed'], debug_file,
		plot_file, threshold_used, settings['threshold_db'])
	if temp_wav is not None and args.keep_wav is False:
		os.remove(temp_wav)
	return

#============================================

if __name__ == '__main__':
	main()
