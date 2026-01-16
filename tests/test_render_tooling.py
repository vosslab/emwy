
"""
Pytest coverage for ffmpeg, sox, and mkvmerge tooling.
"""

# Standard Library
import json
import os
import shutil
import subprocess
import sys
import tempfile

# PIP3 modules
import pytest
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# tests helpers
TESTS_DIR = os.path.abspath(os.path.dirname(__file__))
if TESTS_DIR not in sys.path:
	sys.path.insert(0, TESTS_DIR)
from font_utils import find_system_ttf

# local repo modules
from emwylib.core.project import EmwyProject

#============================================

AV_TOOLS = ("ffmpeg", "ffprobe", "mkvmerge")
MISSING_AV_TOOLS = [tool for tool in AV_TOOLS if shutil.which(tool) is None]
HAVE_AV_TOOLS = len(MISSING_AV_TOOLS) == 0
SKIP_AV_REASON = f"missing tools: {', '.join(MISSING_AV_TOOLS)}"

FFPROBE_TOOLS = ("ffmpeg", "ffprobe")
MISSING_FFPROBE_TOOLS = [tool for tool in FFPROBE_TOOLS if shutil.which(tool) is None]
HAVE_FFPROBE_TOOLS = len(MISSING_FFPROBE_TOOLS) == 0
SKIP_FFPROBE_REASON = f"missing tools: {', '.join(MISSING_FFPROBE_TOOLS)}"

SOX_TOOLS = ("ffmpeg", "ffprobe", "mkvmerge", "sox")
MISSING_SOX_TOOLS = [tool for tool in SOX_TOOLS if shutil.which(tool) is None]
HAVE_SOX_TOOLS = len(MISSING_SOX_TOOLS) == 0
SKIP_SOX_REASON = f"missing tools: {', '.join(MISSING_SOX_TOOLS)}"

CUSTOM_FONT_PATH = find_system_ttf()
HAVE_CUSTOM_FONT = CUSTOM_FONT_PATH is not None
SKIP_FONT_REASON = "missing system TTF/OTF font"

#============================================

def _run(cmd: str) -> None:
	"""
	Run a shell command, raising on failure.
	"""
	subprocess.run(cmd, shell=True, check=True,
		stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

#============================================

def _probe_duration(path: str) -> float:
	"""
	Return container duration (seconds) from ffprobe.
	"""
	cmd = f"ffprobe -v error -show_entries format=duration -of json \"{path}\""
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	duration = data.get("format", {}).get("duration")
	return float(duration) if duration is not None else 0.0

#============================================

def _probe_stream_types(path: str) -> set:
	"""
	Return stream types (video/audio/etc) from ffprobe.
	"""
	cmd = f"ffprobe -v error -show_entries stream=codec_type -of json \"{path}\""
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	return {stream.get("codec_type") for stream in data.get("streams", [])}

#============================================

def _probe_chapters(path: str) -> list:
	"""
	Return chapter entries from ffprobe.
	"""
	cmd = f"ffprobe -v error -show_chapters -of json \"{path}\""
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	return data.get("chapters", [])

#============================================

def _write_speed_yaml(path: str, asset_path: str, output_path: str) -> None:
	"""
	Write a simple project with mixed playback speeds.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 25")
	lines.append("  resolution: [320, 240]")
	lines.append("  audio: {sample_rate: 48000, channels: mono}")
	lines.append("")
	lines.append("assets:")
	lines.append("  video:")
	lines.append(f"    source: {{file: \"{asset_path}\"}}")
	lines.append("  playback_styles:")
	lines.append("    normal: {speed: 1}")
	lines.append("    fast: {speed: 2}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append(
		"    - source: {asset: source, in: \"00:00.0\", out: \"00:01.0\", "
		"style: normal}"
	)
	lines.append(
		"    - source: {asset: source, in: \"00:01.0\", out: \"00:02.0\", "
		"style: fast}"
	)
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _write_fill_missing_yaml(path: str, output_path: str) -> None:
	"""
	Write a project that fills missing streams via generators.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 25")
	lines.append("  resolution: [320, 240]")
	lines.append("  audio: {sample_rate: 48000, channels: mono}")
	lines.append("")
	lines.append("assets:")
	lines.append("  video: {}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append("    - generator:")
	lines.append("        kind: silence")
	lines.append("        duration: \"00:01.0\"")
	lines.append("        fill_missing: {video: black}")
	lines.append("    - generator:")
	lines.append("        kind: black")
	lines.append("        duration: \"00:01.0\"")
	lines.append("        fill_missing: {audio: silence}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _write_chapter_yaml(path: str, asset_path: str, output_path: str) -> None:
	"""
	Write a project that emits a single chapter.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 25")
	lines.append("  resolution: [320, 240]")
	lines.append("  audio: {sample_rate: 48000, channels: mono}")
	lines.append("")
	lines.append("assets:")
	lines.append("  video:")
	lines.append(f"    source: {{file: \"{asset_path}\"}}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append(
		"    - source: {asset: source, in: \"00:00.0\", out: \"00:01.0\", "
		"title: \"Intro\"}"
	)
	lines.append(
		"    - source: {asset: source, in: \"00:01.0\", out: \"00:02.0\", "
		"title: \"Hidden\", chapter: false}"
	)
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _write_batch_yaml(path: str, asset_path: str, output_path: str) -> None:
	"""
	Write a project that triggers merge batching.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 25")
	lines.append("  resolution: [320, 240]")
	lines.append("  audio: {sample_rate: 48000, channels: mono}")
	lines.append("")
	lines.append("assets:")
	lines.append("  video:")
	lines.append(f"    source: {{file: \"{asset_path}\"}}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append("    - source: {asset: source, in: \"00:00.0\", out: \"00:01.0\"}")
	lines.append("    - source: {asset: source, in: \"00:01.0\", out: \"00:02.0\"}")
	lines.append("    - source: {asset: source, in: \"00:02.0\", out: \"00:03.0\"}")
	lines.append("    - source: {asset: source, in: \"00:03.0\", out: \"00:04.0\"}")
	lines.append("    - source: {asset: source, in: \"00:04.0\", out: \"00:05.0\"}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	lines.append("  merge_batch_threshold: 2")
	lines.append("  merge_batch_size: 2")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _write_font_yaml(path: str, output_path: str, font_file: str) -> None:
	"""
	Write a project that uses a custom font file.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 25")
	lines.append("  resolution: [320, 240]")
	lines.append("  audio: {sample_rate: 48000, channels: mono}")
	lines.append("")
	lines.append("assets:")
	lines.append("  cards:")
	lines.append("    font_style:")
	lines.append("      kind: chapter_card_style")
	lines.append(f"      font_file: \"{font_file}\"")
	lines.append("      font_size: 48")
	lines.append("      text_color: \"#ffffff\"")
	lines.append("      background: {kind: color, color: \"#101820\"}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append("    - generator:")
	lines.append("        kind: chapter_card")
	lines.append("        title: \"Custom Font\"")
	lines.append("        duration: \"00:01.0\"")
	lines.append("        style: font_style")
	lines.append("        fill_missing: {audio: silence}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _write_silence_config(path: str) -> None:
	"""
	Write a minimal silence annotator config.
	"""
	lines = []
	lines.append("silence_annotator: 1")
	lines.append("settings:")
	lines.append("  detection:")
	lines.append("    threshold_db: -40")
	lines.append("    min_silence: 0.4")
	lines.append("    min_content: 0.4")
	lines.append("  trim_leading_silence: false")
	lines.append("  trim_trailing_silence: false")
	lines.append("  overlay:")
	lines.append("    enabled: false")
	lines.append("  title_card:")
	lines.append("    enabled: false")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

@pytest.mark.skipif(not HAVE_SOX_TOOLS, reason=SKIP_SOX_REASON)
def test_speed_sync_duration() -> None:
	"""
	Ensure mixed playback styles yield expected output duration.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mp4")
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 2 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		_write_speed_yaml(yaml_path, source_path, output_path)
		project = EmwyProject(yaml_path)
		project.run()
		duration = _probe_duration(output_path)
		assert duration > 1.4
		assert duration < 1.7

#============================================

@pytest.mark.skipif(not HAVE_SOX_TOOLS, reason=SKIP_SOX_REASON)
def test_fill_missing_generators() -> None:
	"""
	Ensure fill_missing generates both streams for video-only and audio-only generators.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		_write_fill_missing_yaml(yaml_path, output_path)
		project = EmwyProject(yaml_path)
		project.run()
		stream_types = _probe_stream_types(output_path)
		assert "video" in stream_types
		assert "audio" in stream_types
		duration = _probe_duration(output_path)
		assert duration > 1.9
		assert duration < 2.1

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_chapters_from_titles() -> None:
	"""
	Ensure chapter export honors chapter: false.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mp4")
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 2 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		_write_chapter_yaml(yaml_path, source_path, output_path)
		project = EmwyProject(yaml_path)
		project.run()
		chapters = _probe_chapters(output_path)
		assert len(chapters) == 1
		title = chapters[0].get("tags", {}).get("title")
		assert title == "Intro"

#============================================

@pytest.mark.skipif(not HAVE_FFPROBE_TOOLS, reason=SKIP_FFPROBE_REASON)
def test_silence_annotator_segments() -> None:
	"""
	Ensure silence annotator finds expected content/silence segments.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mp4")
		config_path = os.path.join(temp_dir, "silence_config.yaml")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25:duration=3 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000:duration=1 "
			"-f lavfi -i anullsrc=channel_layout=mono:sample_rate=48000:duration=1 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000:duration=1 "
			"-filter_complex \"[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]\" "
			"-map 0:v -map \"[a]\" "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		_write_silence_config(config_path)
		annotator = os.path.join(REPO_ROOT, "tools", "silence_annotator.py")
		cmd = (
			f"\"{sys.executable}\" \"{annotator}\" "
			f"-i \"{source_path}\" -c \"{config_path}\""
		)
		_run(cmd)
		yaml_path = f"{source_path}.emwy.yaml"
		with open(yaml_path, "r", encoding="utf-8") as handle:
			data = yaml.safe_load(handle)
		segments = data.get("timeline", {}).get("segments", [])
		assert len(segments) == 3

#============================================

@pytest.mark.skipif(not HAVE_SOX_TOOLS, reason=SKIP_SOX_REASON)
def test_sox_tempo_duration() -> None:
	"""
	Ensure sox tempo changes duration as expected.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.wav")
		output_path = os.path.join(temp_dir, "speed.wav")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 2 "
			"-c:a pcm_s16le -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		cmd = f"sox \"{source_path}\" \"{output_path}\" tempo -s 2.0"
		_run(cmd)
		duration = _probe_duration(output_path)
		assert duration > 0.9
		assert duration < 1.1

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_mkvmerge_concatenation_streams() -> None:
	"""
	Ensure mkvmerge concatenation preserves audio and video streams.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		clip_a = os.path.join(temp_dir, "a.mkv")
		clip_b = os.path.join(temp_dir, "b.mkv")
		output_path = os.path.join(temp_dir, "out.mkv")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 1 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{clip_a}\""
		)
		_run(cmd)
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=880:sample_rate=48000 "
			"-t 1 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{clip_b}\""
		)
		_run(cmd)
		cmd = f"mkvmerge \"{clip_a}\" + \"{clip_b}\" -o \"{output_path}\""
		_run(cmd)
		stream_types = _probe_stream_types(output_path)
		assert "video" in stream_types
		assert "audio" in stream_types
		duration = _probe_duration(output_path)
		assert duration > 1.8
		assert duration < 2.2

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_merge_batching_outputs() -> None:
	"""
	Ensure merge batching produces intermediate concat files.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mp4")
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 5 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		_write_batch_yaml(yaml_path, source_path, output_path)
		project = EmwyProject(yaml_path, cache_dir=temp_dir, keep_temp=True)
		project.run()
		concat_files = [
			name for name in os.listdir(temp_dir)
			if name.endswith(".mkv") and "concat-" in name
		]
		assert len(concat_files) >= 2
		assert os.path.exists(output_path)

#============================================

@pytest.mark.skipif(not HAVE_SOX_TOOLS, reason=SKIP_SOX_REASON)
@pytest.mark.skipif(not HAVE_CUSTOM_FONT, reason=SKIP_FONT_REASON)
def test_custom_font_file() -> None:
	"""
	Ensure custom font_file renders without error.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		_write_font_yaml(yaml_path, output_path, CUSTOM_FONT_PATH)
		project = EmwyProject(yaml_path)
		project.run()
		assert os.path.exists(output_path)
		stream_types = _probe_stream_types(output_path)
		assert "video" in stream_types
		assert "audio" in stream_types
