"""
detection.py

Audio analysis and silence detection functions.
"""

# Standard Library
import os
import tempfile
import json
import wave
import math

# PIP3 modules
import numpy

# local repo modules
import common_tools.tools_common as tools_common

#============================================

AUTO_THRESHOLD_STEP_DB = 2.0
AUTO_THRESHOLD_MAX_DB = -5.0
AUTO_THRESHOLD_MAX_TRIES = 20

#============================================

def make_temp_wav() -> str:
	"""
	Create a temporary wav filename.

	Returns:
		str: Temporary wav path.
	"""
	temp_handle, temp_path = tempfile.mkstemp(prefix="silence-", suffix=".wav")
	os.close(temp_handle)
	return temp_path

#============================================

def extract_audio(input_file: str, wav_path: str) -> str:
	"""
	Extract audio from a video file using ffmpeg.

	Args:
		input_file: Video file path.
		wav_path: Output wav path.

	Returns:
		str: Output wav path.
	"""
	cmd = [
		"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
		"-i", input_file,
		"-vn", "-sn",
		"-acodec", "pcm_s16le",
		"-ar", "48000",
	]
	cmd += ["-ac", "1"]
	cmd.append(wav_path)
	tools_common.run_process(cmd, capture_output=True)
	if not os.path.isfile(wav_path):
		raise RuntimeError("audio extraction failed")
	return wav_path

#============================================

def probe_audio_stream(input_file: str) -> dict:
	"""
	Probe audio stream metadata using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		dict: Audio metadata fields.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-select_streams", "a:0",
		"-show_entries", "stream=sample_rate,channels",
		"-of", "json",
		input_file,
	]
	proc = tools_common.run_process(cmd, capture_output=True)
	data = json.loads(proc.stdout)
	streams = data.get('streams', [])
	if len(streams) == 0:
		raise RuntimeError("no audio stream found for metadata")
	stream = streams[0]
	sample_rate = int(stream.get('sample_rate', 0))
	channels = int(stream.get('channels', 0))
	if sample_rate <= 0:
		raise RuntimeError("invalid audio sample rate from ffprobe")
	if channels <= 0:
		raise RuntimeError("invalid audio channel count from ffprobe")
	return {
		'sample_rate': sample_rate,
		'channels': channels,
	}

#============================================

def get_wav_duration_seconds(audio_path: str) -> float:
	"""
	Get wav duration in seconds.

	Args:
		audio_path: Audio file path.

	Returns:
		float: Duration in seconds.
	"""
	with wave.open(audio_path, 'rb') as wav_handle:
		sample_rate = wav_handle.getframerate()
		total_frames = wav_handle.getnframes()
	if sample_rate <= 0:
		raise RuntimeError("audio sample rate must be positive")
	if total_frames <= 0:
		raise RuntimeError("audio duration must be positive")
	duration = total_frames / float(sample_rate)
	return duration

#============================================

def get_wav_info(audio_path: str) -> dict:
	"""
	Get wav metadata.

	Args:
		audio_path: Audio file path.

	Returns:
		dict: Wav info.
	"""
	with wave.open(audio_path, 'rb') as wav_handle:
		channels = wav_handle.getnchannels()
		sample_rate = wav_handle.getframerate()
		sample_width = wav_handle.getsampwidth()
		total_frames = wav_handle.getnframes()
	if sample_rate <= 0:
		raise RuntimeError("audio sample rate must be positive")
	if total_frames <= 0:
		raise RuntimeError("audio duration must be positive")
	if channels <= 0:
		raise RuntimeError("audio channel count must be positive")
	return {
		'channels': channels,
		'sample_rate': sample_rate,
		'sample_width': sample_width,
		'total_frames': total_frames,
		'duration': total_frames / float(sample_rate),
	}

#============================================

def amplitude_to_db(value: float) -> float:
	"""
	Convert linear amplitude to dBFS.

	Args:
		value: Linear amplitude.

	Returns:
		float: dBFS value.
	"""
	if value is None or value <= 0:
		return None
	return 20.0 * math.log10(value)

#============================================

def scan_wav_for_silence(audio_path: str, threshold_db: float,
	min_silence: float, frame_seconds: float, hop_seconds: float,
	smooth_frames: int, include_series: bool = False) -> tuple:
	"""
	Scan wav samples for silence segments.

	Args:
		audio_path: Audio file path.
		threshold_db: Silence threshold in dBFS.
		min_silence: Minimum silence duration in seconds.
		frame_seconds: Frame window size in seconds.
		hop_seconds: Hop size in seconds.
		smooth_frames: Smoothing window in frames.

	Returns:
		tuple: (raw_silences, stats)
	"""
	info = get_wav_info(audio_path)
	channels = info['channels']
	sample_rate = info['sample_rate']
	sample_width = info['sample_width']
	total_frames = info['total_frames']
	if sample_width not in (1, 2, 4):
		raise RuntimeError("unsupported wav sample width")
	max_amplitude = float(2 ** (8 * sample_width - 1))
	threshold_amp = 10 ** (threshold_db / 20.0)
	threshold_int = int(max_amplitude * threshold_amp)
	if threshold_int < 1:
		threshold_int = 1
	frame_size = max(1, int(sample_rate * frame_seconds))
	hop_size = max(1, int(sample_rate * hop_seconds))
	dtype_map = {
		1: numpy.dtype('u1'),
		2: numpy.dtype('<i2'),
		4: numpy.dtype('<i4'),
	}
	raw_silences = []
	with wave.open(audio_path, 'rb') as wav_handle:
		data = wav_handle.readframes(total_frames)
	samples = numpy.frombuffer(data, dtype=dtype_map[sample_width])
	if sample_width == 1:
		samples = samples.astype(numpy.int16) - 128
	if samples.size == 0:
		stats = {
			'channels': channels,
			'sample_rate': sample_rate,
			'sample_width': sample_width,
			'total_frames': total_frames,
			'duration': total_frames / float(sample_rate),
			'threshold_int': threshold_int,
			'threshold_db': threshold_db,
			'frame_size': frame_size,
			'frame_seconds': frame_seconds,
			'hop_seconds': hop_seconds,
			'smooth_frames': smooth_frames,
			'frame_count': 0,
			'below_frames': 0,
			'below_pct': 0.0,
			'longest_run_sec': 0.0,
			'runs_over_min': 0,
			'max_amp': None,
			'rms_amp': None,
		}
		if include_series:
			stats['frame_db'] = numpy.array([], dtype=numpy.float64)
		return [], stats
	frame_count = samples.size // channels
	if samples.size != frame_count * channels:
		samples = samples[:frame_count * channels]
	if frame_count == 0:
		stats = {
			'channels': channels,
			'sample_rate': sample_rate,
			'sample_width': sample_width,
			'total_frames': total_frames,
			'duration': total_frames / float(sample_rate),
			'threshold_int': threshold_int,
			'threshold_db': threshold_db,
			'frame_size': frame_size,
			'frame_seconds': frame_seconds,
			'hop_seconds': hop_seconds,
			'smooth_frames': smooth_frames,
			'frame_count': 0,
			'below_frames': 0,
			'below_pct': 0.0,
			'longest_run_sec': 0.0,
			'runs_over_min': 0,
			'max_amp': None,
			'rms_amp': None,
		}
		if include_series:
			stats['frame_db'] = numpy.array([], dtype=numpy.float64)
		return [], stats
	if channels > 1:
		samples = samples.reshape(frame_count, channels)
		samples = numpy.mean(samples, axis=1, dtype=numpy.float64)
		samples = samples.astype(numpy.int64, copy=False).reshape(frame_count, 1)
		channels = 1
	else:
		samples = samples.reshape(frame_count, 1)
	usable_frames = (frame_count - frame_size) // hop_size + 1
	if usable_frames <= 0:
		stats = {
			'channels': channels,
			'sample_rate': sample_rate,
			'sample_width': sample_width,
			'total_frames': total_frames,
			'duration': total_frames / float(sample_rate),
			'threshold_int': threshold_int,
			'threshold_db': threshold_db,
			'frame_size': frame_size,
			'frame_seconds': frame_seconds,
			'hop_seconds': hop_seconds,
			'smooth_frames': smooth_frames,
			'frame_count': 0,
			'below_frames': 0,
			'below_pct': 0.0,
			'longest_run_sec': 0.0,
			'runs_over_min': 0,
			'max_amp': None,
			'rms_amp': None,
		}
		if include_series:
			stats['frame_db'] = numpy.array([], dtype=numpy.float64)
		return [], stats
	starts = numpy.arange(usable_frames) * hop_size
	ends = starts + frame_size
	frame_db = numpy.empty(usable_frames, dtype=numpy.float64)
	sum_sq = 0.0
	max_abs = 0
	for index, (start_idx, end_idx) in enumerate(zip(starts, ends)):
		window = samples[start_idx:end_idx]
		window_int = window.astype(numpy.int64, copy=False)
		abs_max = int(numpy.max(numpy.abs(window_int)))
		if abs_max > max_abs:
			max_abs = abs_max
		mean_sq = float(numpy.mean(window_int.astype(numpy.float64) ** 2))
		sum_sq += mean_sq * window_int.size
		rms = math.sqrt(mean_sq)
		rms_norm = rms / max_amplitude
		db = amplitude_to_db(rms_norm)
		if db is None:
			db = -120.0
		frame_db[index] = db
	smooth_db = None
	if smooth_frames > 1:
		window = numpy.ones(smooth_frames, dtype=numpy.float64) / smooth_frames
		smooth_db = numpy.convolve(frame_db, window, mode='same')
		mask = smooth_db < threshold_db
	else:
		mask = frame_db < threshold_db
	mask_int = mask.astype(numpy.int8)
	diff = numpy.diff(mask_int)
	start_idxs = numpy.where(diff == 1)[0] + 1
	end_idxs = numpy.where(diff == -1)[0] + 1
	if mask[0]:
		start_idxs = numpy.concatenate(
			(numpy.array([0], dtype=numpy.int64), start_idxs)
		)
	if mask[-1]:
		end_idxs = numpy.concatenate(
			(end_idxs, numpy.array([len(mask)], dtype=numpy.int64))
		)
	longest_run = 0
	runs_over_min = 0
	for start_idx, end_idx in zip(start_idxs, end_idxs):
		start_idx = int(start_idx)
		end_idx = int(end_idx)
		run_len = end_idx - start_idx
		run_seconds = run_len * hop_seconds + (frame_seconds - hop_seconds)
		if run_seconds >= min_silence:
			raw_silences.append({
				'start': start_idx * hop_seconds,
				'end': (end_idx - 1) * hop_seconds + frame_seconds,
				'duration': run_seconds,
			})
			runs_over_min += 1
		if run_len > longest_run:
			longest_run = run_len
	below_frames = int(numpy.sum(mask))
	below_pct = 0.0
	if mask.size > 0:
		below_pct = (below_frames / float(mask.size)) * 100.0
	rms_amp = None
	max_amp = None
	if sum_sq > 0 and frame_count > 0:
		rms_amp = math.sqrt(sum_sq / float(frame_count * channels)) / max_amplitude
		max_amp = max_abs / max_amplitude
	stats = {
		'channels': channels,
		'sample_rate': sample_rate,
		'sample_width': sample_width,
		'total_frames': total_frames,
		'duration': total_frames / float(sample_rate),
		'threshold_int': threshold_int,
		'threshold_db': threshold_db,
		'frame_size': frame_size,
		'frame_seconds': frame_seconds,
		'hop_seconds': hop_seconds,
		'smooth_frames': smooth_frames,
		'frame_count': int(mask.size),
		'below_frames': below_frames,
		'below_pct': below_pct,
		'longest_run_sec': longest_run * hop_seconds + (frame_seconds - hop_seconds),
		'runs_over_min': runs_over_min,
		'max_amp': max_amp,
		'rms_amp': rms_amp,
	}
	if include_series:
		stats['frame_db'] = frame_db
		if smooth_db is not None:
			stats['smooth_db'] = smooth_db
	return raw_silences, stats

#============================================

def build_debug_report(audio_path: str, threshold_db: float, min_silence: float,
	stats: dict, auto_attempts: list = None, threshold_used: float = None) -> str:
	"""
	Build a debug report for Python silence detection.

	Args:
		audio_path: Audio file path.
		threshold_db: Silence threshold in dBFS.
		min_silence: Minimum silence duration in seconds.
		stats: Scan statistics.
		auto_attempts: Auto-threshold attempts.
		threshold_used: Effective threshold.

	Returns:
		str: Debug report text.
	"""
	lines = []
	lines.append(f"audio_path: {audio_path}")
	lines.append(f"threshold_db: {threshold_db:.2f}")
	lines.append(f"min_silence: {min_silence:.3f}")
	lines.append("")
	lines.append("wav_info:")
	lines.append(f"channels: {stats['channels']}")
	lines.append(f"sample_rate: {stats['sample_rate']}")
	lines.append(f"sample_width: {stats['sample_width']}")
	lines.append(f"total_frames: {stats['total_frames']}")
	lines.append(f"duration: {stats['duration']:.3f}")
	lines.append(f"frame_seconds: {stats['frame_seconds']:.3f}")
	lines.append(f"hop_seconds: {stats['hop_seconds']:.3f}")
	lines.append(f"frame_count: {stats['frame_count']}")
	lines.append(f"smooth_frames: {stats['smooth_frames']}")
	lines.append("")
	lines.append("silence_scan:")
	lines.append(f"threshold_int: {stats['threshold_int']}")
	lines.append(f"below_frames: {stats['below_frames']}")
	lines.append(f"below_pct: {stats['below_pct']:.2f}")
	lines.append(f"longest_run_sec: {stats['longest_run_sec']:.3f}")
	lines.append(f"runs_over_min: {stats['runs_over_min']}")
	if stats['rms_amp'] is not None:
		lines.append(f"rms_amp: {stats['rms_amp']:.6f}")
	if stats['max_amp'] is not None:
		lines.append(f"max_amp: {stats['max_amp']:.6f}")
	lines.append("")
	if auto_attempts is not None and len(auto_attempts) > 0:
		lines.append("auto_threshold_attempts:")
		for attempt in auto_attempts:
			lines.append(
				f"- threshold_db: {attempt['threshold_db']:.2f} "
				f"raw: {attempt['raw_count']} "
				f"normalized: {attempt['normalized_count']}"
			)
		lines.append("")
	if threshold_used is not None:
		lines.append("threshold_used:")
		lines.append(f"{threshold_used:.2f}")
		lines.append("")
	return "\n".join(lines)

#============================================

def auto_find_silence(audio_path: str, duration: float, threshold_db: float,
	min_silence: float, min_content: float, frame_seconds: float,
	hop_seconds: float, smooth_frames: int, step_db: float,
	max_db: float, max_tries: int) -> dict:
	"""
	Auto-raise threshold until silence is detected.

	Args:
		audio_path: Audio file path.
		duration: Total duration in seconds.
		threshold_db: Starting threshold in dBFS.
		min_silence: Minimum silence duration in seconds.
		min_content: Minimum content duration in seconds.
		frame_seconds: Frame window size in seconds.
		hop_seconds: Hop size in seconds.
		smooth_frames: Smoothing window in frames.
		step_db: Threshold increment in dB.
		max_db: Maximum threshold in dBFS.
		max_tries: Maximum adjustment attempts.

	Returns:
		dict: Auto adjustment results.
	"""
	# late import to avoid circular dependency with silence_annotator
	import silence_annotator
	attempts = []
	current = threshold_db
	tries = 0
	while True:
		current += step_db
		if current > max_db:
			break
		tries += 1
		if tries > max_tries:
			break
		raw_silences, scan_stats = scan_wav_for_silence(
			audio_path, current, min_silence, frame_seconds,
			hop_seconds, smooth_frames
		)
		silences = silence_annotator.normalize_silences(raw_silences, duration,
			min_silence, min_content)
		attempts.append({
			'threshold_db': current,
			'raw_count': len(raw_silences),
			'normalized_count': len(silences),
		})
		if len(silences) > 0:
			return {
				'found': True,
				'threshold_db': current,
				'raw_silences': raw_silences,
				'silences': silences,
				'scan_stats': scan_stats,
				'attempts': attempts,
			}
	return {
		'found': False,
		'attempts': attempts,
	}
