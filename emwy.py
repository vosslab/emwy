#!/usr/bin/env python3

import argparse
import os
import re
import shutil
import subprocess
import time
import yaml
from decimal import Decimal
from fractions import Fraction
from emwylib.media import sox
from emwylib import titlecard

#============================================

def runCmd(cmd: str) -> None:
	showcmd = cmd.strip()
	showcmd = re.sub("  *", " ", showcmd)
	print(f"CMD: '{showcmd}'")
	proc = subprocess.Popen(showcmd, shell=True, stderr=subprocess.PIPE,
		stdout=subprocess.PIPE)
	proc.communicate()
	return

#============================================

def parse_args():
	"""
	Parse command-line arguments.
	"""
	parser = argparse.ArgumentParser(description="CLI Movie Editor")
	parser.add_argument('-y', '--yaml', dest='yamlfile', required=True,
		help='main yaml file that outlines the processing to do')
	parser.add_argument('-o', '--output', dest='output_file',
		help='override output file from yaml')
	parser.add_argument('-n', '--dry-run', dest='dry_run', action='store_true',
		help='validate only, do not render')
	args = parser.parse_args()
	return args

#============================================

def parse_fps(raw_fps) -> Fraction:
	if raw_fps is None:
		raise RuntimeError("profile.fps is required")
	if isinstance(raw_fps, int):
		return Fraction(raw_fps, 1)
	if isinstance(raw_fps, float):
		return Fraction(str(raw_fps))
	if isinstance(raw_fps, str):
		if '/' in raw_fps:
			parts = raw_fps.split('/')
			return Fraction(int(parts[0]), int(parts[1]))
		return Fraction(raw_fps)
	raise RuntimeError("profile.fps must be int, float, or fraction string")

#============================================

def parse_timecode(raw_time) -> Decimal:
	if raw_time is None:
		raise RuntimeError("time value is required")
	if isinstance(raw_time, int):
		return Decimal(raw_time)
	if isinstance(raw_time, float):
		return Decimal(str(raw_time))
	if isinstance(raw_time, str):
		value = raw_time.strip()
		if value.endswith('@frame'):
			raise RuntimeError("frame override values are not supported yet")
		if ':' not in value:
			return Decimal(value)
		parts = value.split(':')
		seconds = Decimal(parts.pop())
		minutes = Decimal(parts.pop())
		hours = Decimal(0)
		if len(parts) > 0:
			hours = Decimal(parts.pop())
		return hours * Decimal(3600) + minutes * Decimal(60) + seconds
	raise RuntimeError("time values must be int, float, or timecode string")

#============================================

def round_half_up_fraction(value: Fraction) -> int:
	numerator = value.numerator
	denominator = value.denominator
	whole = numerator // denominator
	remainder = numerator - (whole * denominator)
	if remainder * 2 > denominator:
		return whole + 1
	if remainder * 2 == denominator:
		return whole + 1
	return whole

#============================================

def frames_from_seconds(seconds: Decimal, fps: Fraction) -> int:
	seconds_fraction = Fraction(str(seconds))
	frame_fraction = seconds_fraction * fps
	return round_half_up_fraction(frame_fraction)

#============================================

def seconds_from_frames(frames: int, fps: Fraction) -> float:
	seconds_fraction = Fraction(frames, 1) / fps
	return float(seconds_fraction)

#============================================

def decimal_to_fraction(value: Decimal) -> Fraction:
	return Fraction(str(value))

#============================================

def parse_speed(speed_value, default_speed: Decimal) -> Decimal:
	if speed_value is None:
		return default_speed
	if isinstance(speed_value, int):
		return Decimal(speed_value)
	if isinstance(speed_value, float):
		return Decimal(str(speed_value))
	return Decimal(str(speed_value))

#============================================

def normalize_channels(raw_channels) -> tuple:
	if raw_channels is None:
		return (2, 'stereo')
	channels = str(raw_channels).lower()
	if channels == 'mono':
		return (1, 'mono')
	if channels == 'stereo':
		return (2, 'stereo')
	raise RuntimeError("profile.audio.channels must be mono or stereo")

#============================================

def ensure_file_exists(filepath: str) -> None:
	if not os.path.exists(filepath):
		raise RuntimeError(f"file not found: {filepath}")
	return

#============================================

def make_timestamp() -> str:
	datestamp = time.strftime("%y%b%d").lower()
	uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	hourstamp = uppercase[(time.localtime()[3]) % 26]
	minstamp = f"{time.localtime()[4]:02d}"
	secstamp = uppercase[(time.localtime()[5]) % 26]
	timestamp = datestamp + hourstamp + minstamp + secstamp
	return timestamp

#============================================
class EmwyProject():
	def __init__(self, yaml_file: str, output_override: str = None,
		dry_run: bool = False):
		self.yaml_file = yaml_file
		self.output_override = output_override
		self.dry_run = dry_run
		self.keep_temp = os.environ.get('EMWY_KEEP_TEMP', '') == '1'
		self.cache_dir = os.environ.get('EMWY_CACHE_DIR', os.getcwd())
		self.temp_counter = 0
		self.data = {}
		self.profile = {}
		self.defaults = {}
		self.assets = {}
		self.playlists = {}
		self.stack = {}
		self.output = {}
		self._load_yaml()
		self._parse_project()

	#============================
	def _load_yaml(self):
		file_size = os.path.getsize(self.yaml_file)
		if file_size > 10 ** 7:
			raise RuntimeError("yaml file is larger than 10MB")
		with open(self.yaml_file, 'r') as data_file:
			self.data = yaml.safe_load(data_file)
		if not isinstance(self.data, dict):
			raise RuntimeError("v2 yaml must be a mapping at the top level")

	#============================
	def _parse_project(self):
		self._validate_required_keys()
		self.profile = self._parse_profile(self.data.get('profile'))
		self.defaults = self._parse_defaults(self.data.get('defaults', {}))
		self.assets = self._parse_assets(self.data.get('assets', {}))
		self.playlists = self._parse_playlists(self.data.get('playlists', {}))
		self.stack = self._parse_stack(self.data.get('stack', {}))
		self.output = self._parse_output(self.data.get('output', {}))

	#============================
	def _validate_required_keys(self):
		if self.data.get('emwy') != 2:
			raise RuntimeError("emwy must be set to 2 for v2 projects")
		required_keys = ('profile', 'assets', 'playlists', 'stack', 'output')
		for key in required_keys:
			if key not in self.data:
				raise RuntimeError(f"missing required key: {key}")

	#============================
	def _parse_profile(self, profile: dict) -> dict:
		if not isinstance(profile, dict):
			raise RuntimeError("profile must be a mapping")
		fps = parse_fps(profile.get('fps'))
		resolution = profile.get('resolution')
		if not resolution or len(resolution) != 2:
			raise RuntimeError("profile.resolution must be [width, height]")
		width = int(resolution[0])
		height = int(resolution[1])
		audio = profile.get('audio', {})
		sample_rate = int(audio.get('sample_rate', 48000))
		channels_raw = audio.get('channels', 'stereo')
		(channel_count, audio_mode) = normalize_channels(channels_raw)
		pixel_format = profile.get('pixel_format', 'yuv420p')
		return {
			'fps': fps,
			'fps_float': float(fps),
			'width': width,
			'height': height,
			'sample_rate': sample_rate,
			'channels': channel_count,
			'audio_mode': audio_mode,
			'pixel_format': pixel_format,
		}

	#============================
	def _parse_defaults(self, defaults: dict) -> dict:
		default_speed = Decimal('1.0')
		default_norm = None
		if defaults.get('video') is not None:
			default_speed = parse_speed(defaults['video'].get('speed'), default_speed)
		if defaults.get('audio') is not None:
			norm = defaults['audio'].get('normalize')
			if isinstance(norm, dict):
				default_norm = norm.get('level_db')
		return {
			'speed': default_speed,
			'normalize': default_norm,
		}

	#============================
	def _parse_assets(self, assets: dict) -> dict:
		asset_groups = {
			'video': assets.get('video', {}),
			'audio': assets.get('audio', {}),
			'image': assets.get('image', {}),
			'cards': assets.get('cards', {}),
		}
		for group_name, group in asset_groups.items():
			if not isinstance(group, dict):
				raise RuntimeError(f"assets.{group_name} must be a mapping")
		return asset_groups

	#============================
	def _parse_playlists(self, playlists: dict) -> dict:
		if not isinstance(playlists, dict) or len(playlists) == 0:
			raise RuntimeError("playlists must be a non-empty mapping")
		parsed = {}
		for playlist_id, playlist in playlists.items():
			parsed[playlist_id] = self._parse_playlist(playlist_id, playlist)
		return parsed

	#============================
	def _parse_playlist(self, playlist_id: str, playlist: dict) -> dict:
		if not isinstance(playlist, dict):
			raise RuntimeError(f"playlist {playlist_id} must be a mapping")
		kind = playlist.get('kind')
		if kind not in ('video', 'audio'):
			raise RuntimeError(f"playlist {playlist_id} kind must be video or audio")
		entries = playlist.get('playlist', [])
		if not isinstance(entries, list) or len(entries) == 0:
			raise RuntimeError(f"playlist {playlist_id} has no entries")
		parsed_entries = []
		total_frames = 0
		for entry in entries:
			parsed_entry = self._parse_playlist_entry(playlist_id, kind, entry)
			parsed_entries.append(parsed_entry)
			total_frames += parsed_entry['duration_frames']
		return {
			'id': playlist_id,
			'kind': kind,
			'entries': parsed_entries,
			'duration_frames': total_frames,
		}

	#============================
	def _parse_playlist_entry(self, playlist_id: str, kind: str, entry: dict) -> dict:
		if not isinstance(entry, dict) or len(entry.keys()) != 1:
			raise RuntimeError(f"playlist {playlist_id} entries must have one key")
		entry_type = list(entry.keys())[0]
		entry_data = entry.get(entry_type)
		if entry_type == 'source':
			return self._parse_source_entry(playlist_id, kind, entry_data)
		if entry_type == 'blank':
			return self._parse_blank_entry(playlist_id, kind, entry_data)
		if entry_type == 'generator':
			return self._parse_generator_entry(playlist_id, kind, entry_data)
		if entry_type == 'nested':
			raise RuntimeError("nested entries are not supported yet")
		raise RuntimeError(f"unsupported entry type {entry_type}")

	#============================
	def _parse_source_entry(self, playlist_id: str, kind: str, entry_data: dict) -> dict:
		if not isinstance(entry_data, dict):
			raise RuntimeError(f"playlist {playlist_id} source entry must be mapping")
		asset_id = entry_data.get('asset')
		if asset_id is None:
			raise RuntimeError("source entry must include asset")
		asset_group = 'video' if kind == 'video' else 'audio'
		asset = self.assets.get(asset_group, {}).get(asset_id)
		if asset is None:
			raise RuntimeError(f"asset {asset_id} not found in assets.{asset_group}")
		asset_file = asset.get('file')
		if asset_file is None:
			raise RuntimeError(f"asset {asset_id} missing file")
		ensure_file_exists(asset_file)
		in_time = parse_timecode(entry_data.get('in'))
		out_time = parse_timecode(entry_data.get('out'))
		in_frame = frames_from_seconds(in_time, self.profile['fps'])
		out_frame = frames_from_seconds(out_time, self.profile['fps'])
		if out_frame <= in_frame:
			raise RuntimeError("source entry requires in < out")
		source_frames = out_frame - in_frame
		default_speed = self.defaults['speed']
		entry_speed = None
		if kind == 'video':
			if entry_data.get('video') is not None:
				entry_speed = entry_data['video'].get('speed')
		else:
			if entry_data.get('audio') is not None:
				entry_speed = entry_data['audio'].get('speed')
		speed = parse_speed(entry_speed, default_speed)
		if speed <= 0:
			raise RuntimeError("speed must be positive")
		speed_fraction = decimal_to_fraction(speed)
		output_frames = source_frames
		if speed_fraction != 0:
			output_frames = round_half_up_fraction(
				Fraction(source_frames, 1) / speed_fraction
			)
		if output_frames <= 0:
			raise RuntimeError("source entry duration is zero after speed change")
		norm_level = None
		if kind == 'audio':
			norm_level = self.defaults['normalize']
			if entry_data.get('audio') is not None:
				norm = entry_data['audio'].get('normalize')
				if isinstance(norm, dict) and norm.get('level_db') is not None:
					norm_level = norm.get('level_db')
		return {
			'type': 'source',
			'asset_id': asset_id,
			'asset_file': asset_file,
			'in_frame': in_frame,
			'out_frame': out_frame,
			'duration_frames': output_frames,
			'speed': speed,
			'normalize': norm_level,
		}

	#============================
	def _parse_blank_entry(self, playlist_id: str, kind: str, entry_data: dict) -> dict:
		if not isinstance(entry_data, dict):
			raise RuntimeError(f"playlist {playlist_id} blank entry must be mapping")
		duration = parse_timecode(entry_data.get('duration'))
		duration_frames = frames_from_seconds(duration, self.profile['fps'])
		if duration_frames <= 0:
			raise RuntimeError("blank duration must be positive")
		fill = entry_data.get('fill', 'black')
		if kind == 'video' and fill not in ('black', 'transparent'):
			raise RuntimeError("blank fill must be black or transparent")
		if kind == 'video' and fill == 'transparent':
			raise RuntimeError("transparent blanks not supported in base-only mode")
		return {
			'type': 'blank',
			'duration_frames': duration_frames,
			'fill': fill,
		}

	#============================
	def _parse_generator_entry(self, playlist_id: str, kind: str, entry_data: dict) -> dict:
		if not isinstance(entry_data, dict):
			raise RuntimeError(f"playlist {playlist_id} generator entry must be mapping")
		gen_kind = entry_data.get('kind')
		if gen_kind is None:
			raise RuntimeError("generator entry must include kind")
		duration = parse_timecode(entry_data.get('duration'))
		duration_frames = frames_from_seconds(duration, self.profile['fps'])
		if duration_frames <= 0:
			raise RuntimeError("generator duration must be positive")
		if entry_data.get('paired_audio') is not None:
			raise RuntimeError("paired_audio is not supported yet")
		return {
			'type': 'generator',
			'kind': gen_kind,
			'duration_frames': duration_frames,
			'data': entry_data,
		}

	#============================
	def _parse_stack(self, stack: dict) -> dict:
		if not isinstance(stack, dict):
			raise RuntimeError("stack must be a mapping")
		tracks = stack.get('tracks', [])
		if not isinstance(tracks, list) or len(tracks) == 0:
			raise RuntimeError("stack.tracks must be a non-empty list")
		base_video = None
		main_audio = None
		for track in tracks:
			playlist_id = track.get('playlist')
			role = track.get('role')
			if playlist_id not in self.playlists:
				raise RuntimeError(f"track playlist {playlist_id} not found")
			kind = self.playlists[playlist_id]['kind']
			if kind == 'video' and role == 'base':
				base_video = playlist_id
			if kind == 'audio' and role == 'main':
				main_audio = playlist_id
		if base_video is None:
			raise RuntimeError("stack must include a base video playlist")
		if main_audio is None:
			raise RuntimeError("stack must include a main audio playlist")
		if stack.get('overlays') is not None:
			raise RuntimeError("overlays are not supported yet")
		return {
			'base_video': base_video,
			'main_audio': main_audio,
		}

	#============================
	def _parse_output(self, output: dict) -> dict:
		if not isinstance(output, dict):
			raise RuntimeError("output must be a mapping")
		output_file = output.get('file')
		if self.output_override is not None:
			output_file = self.output_override
		if output_file is None:
			raise RuntimeError("output.file is required")
		return {
			'file': output_file,
			'video_codec': output.get('video_codec', 'libx265'),
			'audio_codec': output.get('audio_codec', 'pcm_s16le'),
			'crf': int(output.get('crf', 26)),
			'container': output.get('container', None),
		}

	#============================
	def validate_timeline(self) -> None:
		video_frames = self.playlists[self.stack['base_video']]['duration_frames']
		audio_frames = self.playlists[self.stack['main_audio']]['duration_frames']
		if video_frames != audio_frames:
			raise RuntimeError("base video and main audio durations do not match")

	#============================
	def run(self) -> None:
		self.validate_timeline()
		if self.dry_run:
			print("dry run: validation complete")
			return
		video_track = self._render_video_playlist(self.stack['base_video'])
		audio_track = self._render_audio_playlist(self.stack['main_audio'])
		self._mux_output(video_track, audio_track, self.output['file'])
		if not self.keep_temp:
			self._cleanup_temp([video_track, audio_track])

	#============================
	def _render_video_playlist(self, playlist_id: str) -> str:
		playlist = self.playlists[playlist_id]
		segment_files = []
		for index, entry in enumerate(playlist['entries'], start=1):
			segment_file = self._render_video_entry(entry, index)
			segment_files.append(segment_file)
		output_file = self._make_temp_path(f"video-track-{playlist_id}.mkv")
		self._concatenate_video(segment_files, output_file)
		if not self.keep_temp:
			self._cleanup_temp(segment_files)
		return output_file

	#============================
	def _render_audio_playlist(self, playlist_id: str) -> str:
		playlist = self.playlists[playlist_id]
		segment_files = []
		for index, entry in enumerate(playlist['entries'], start=1):
			segment_file = self._render_audio_entry(entry, index)
			segment_files.append(segment_file)
		output_file = self._make_temp_path(f"audio-track-{playlist_id}.wav")
		self._concatenate_audio(segment_files, output_file)
		if not self.keep_temp:
			self._cleanup_temp(segment_files)
		return output_file

	#============================
	def _render_video_entry(self, entry: dict, index: int) -> str:
		fps_value = self.profile['fps_float']
		pixel_format = self.profile['pixel_format']
		width = self.profile['width']
		height = self.profile['height']
		codec = self.output['video_codec']
		crf = self.output['crf']
		if entry['type'] == 'source':
			start_seconds = seconds_from_frames(entry['in_frame'], self.profile['fps'])
			out_seconds = seconds_from_frames(entry['out_frame'], self.profile['fps'])
			duration = out_seconds - start_seconds
			speed = float(entry['speed'])
			out_file = self._make_temp_path(f"video-{index:03d}.mkv")
			self._render_video_source(entry['asset_file'], out_file, start_seconds,
				duration, speed, fps_value, codec, crf, pixel_format)
			return out_file
		if entry['type'] == 'blank':
			duration = seconds_from_frames(entry['duration_frames'], self.profile['fps'])
			out_file = self._make_temp_path(f"video-blank-{index:03d}.mkv")
			self._render_black_video(out_file, duration, fps_value, width, height,
				codec, crf, pixel_format)
			return out_file
		if entry['type'] == 'generator':
			return self._render_video_generator(entry, index)
		raise RuntimeError("unsupported video entry type")

	#============================
	def _render_audio_entry(self, entry: dict, index: int) -> str:
		sample_rate = self.profile['sample_rate']
		channels = self.profile['channels']
		audio_mode = self.profile['audio_mode']
		if entry['type'] == 'source':
			start_seconds = seconds_from_frames(entry['in_frame'], self.profile['fps'])
			out_seconds = seconds_from_frames(entry['out_frame'], self.profile['fps'])
			duration = out_seconds - start_seconds
			speed = float(entry['speed'])
			out_file = self._make_temp_path(f"audio-{index:03d}.wav")
			self._render_audio_source(entry['asset_file'], out_file, start_seconds,
				duration, speed, sample_rate, channels, audio_mode, entry['normalize'])
			return out_file
		if entry['type'] == 'blank':
			duration = seconds_from_frames(entry['duration_frames'], self.profile['fps'])
			out_file = self._make_temp_path(f"audio-blank-{index:03d}.wav")
			sox.makeSilence(out_file, seconds=duration, samplerate=sample_rate,
				bitrate=16, audio_mode=audio_mode)
			return out_file
		if entry['type'] == 'generator':
			return self._render_audio_generator(entry, index)
		raise RuntimeError("unsupported audio entry type")

	#============================
	def _render_video_source(self, source_file: str, out_file: str,
		start_seconds: float, duration: float, speed: float, fps_value: float,
		codec: str, crf: int, pixel_format: str) -> None:
		cmd = "ffmpeg -y "
		cmd += f" -ss {start_seconds:.3f} -t {duration:.3f} "
		cmd += f" -i '{source_file}' "
		cmd += " -sn -an -map_chapters -1 -map_metadata -1 "
		cmd += f" -codec:v {codec} -crf {crf} -preset ultrafast "
		cmd += f" -pix_fmt {pixel_format} -r {fps_value:.6f} "
		if abs(speed - 1.0) > 0.0001:
			cmd += f" -filter:v 'setpts={1.0 / speed:.8f}*PTS' "
		cmd += f" '{out_file}' "
		runCmd(cmd)
		ensure_file_exists(out_file)

	#============================
	def _render_black_video(self, out_file: str, duration: float,
		fps_value: float, width: int, height: int, codec: str, crf: int,
		pixel_format: str) -> None:
		cmd = "ffmpeg -y -f lavfi "
		cmd += f" -i color=c=black:s={width}x{height}:r={fps_value:.6f} "
		cmd += f" -t {duration:.3f} "
		cmd += f" -codec:v {codec} -crf {crf} -preset ultrafast "
		cmd += f" -pix_fmt {pixel_format} "
		cmd += f" '{out_file}' "
		runCmd(cmd)
		ensure_file_exists(out_file)

	#============================
	def _render_audio_source(self, source_file: str, out_file: str,
		start_seconds: float, duration: float, speed: float, sample_rate: int,
		channels: int, audio_mode: str, norm_level) -> None:
		raw_file = self._make_temp_path("audio-raw.wav")
		cmd = "ffmpeg -y "
		cmd += f" -ss {start_seconds:.3f} -t {duration:.3f} "
		cmd += f" -i '{source_file}' -sn -vn "
		cmd += f" -acodec pcm_s16le -ar {sample_rate} -ac {channels} "
		cmd += f" '{raw_file}' "
		runCmd(cmd)
		ensure_file_exists(raw_file)
		current_file = raw_file
		if norm_level is not None:
			norm_file = self._make_temp_path("audio-norm.wav")
			sox.normalizeAudio(current_file, norm_file, level=float(norm_level),
				samplerate=sample_rate, bitrate=16)
			if not self.keep_temp:
				os.remove(current_file)
			current_file = norm_file
		if abs(speed - 1.0) > 0.0001:
			speed_file = self._make_temp_path("audio-speed.wav")
			sox.speedUpAudio(current_file, speed_file, speed=speed,
				samplerate=sample_rate, bitrate=16)
			if not self.keep_temp:
				os.remove(current_file)
			current_file = speed_file
		if current_file != out_file:
			shutil.move(current_file, out_file)

	#============================
	def _render_video_generator(self, entry: dict, index: int) -> str:
		gen_kind = entry['kind']
		if gen_kind in ('chapter_card', 'title_card'):
			return self._render_title_card(entry, index)
		if gen_kind == 'black':
			duration = seconds_from_frames(entry['duration_frames'], self.profile['fps'])
			out_file = self._make_temp_path(f"video-black-{index:03d}.mkv")
			self._render_black_video(out_file, duration, self.profile['fps_float'],
				self.profile['width'], self.profile['height'],
				self.output['video_codec'], self.output['crf'],
				self.profile['pixel_format'])
			return out_file
		raise RuntimeError("unsupported video generator kind")

	#============================
	def _render_audio_generator(self, entry: dict, index: int) -> str:
		gen_kind = entry['kind']
		if gen_kind in ('silence',):
			duration = seconds_from_frames(entry['duration_frames'], self.profile['fps'])
			out_file = self._make_temp_path(f"audio-silence-{index:03d}.wav")
			sox.makeSilence(out_file, seconds=duration,
				samplerate=self.profile['sample_rate'], bitrate=16,
				audio_mode=self.profile['audio_mode'])
			return out_file
		raise RuntimeError("unsupported audio generator kind")

	#============================
	def _render_title_card(self, entry: dict, index: int) -> str:
		data = entry.get('data', {})
		text = data.get('title', data.get('text', ''))
		if text == '':
			raise RuntimeError("title_card requires title or text")
		style_id = data.get('style')
		font_size = None
		if style_id is not None:
			style = self.assets.get('cards', {}).get(style_id)
			if isinstance(style, dict) and style.get('font_size') is not None:
				font_size = int(style.get('font_size'))
		if data.get('font_size') is not None:
			font_size = int(data.get('font_size'))
		duration = seconds_from_frames(entry['duration_frames'], self.profile['fps'])
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		tc = titlecard.TitleCard()
		tc.text = text
		tc.width = self.profile['width']
		tc.height = self.profile['height']
		tc.framerate = self.profile['fps_float']
		tc.length = float(duration)
		tc.crf = self.output['crf']
		tc.outfile = out_file
		if font_size is not None:
			tc.size = font_size
		tc.setType()
		tc.createCards()
		ensure_file_exists(out_file)
		return out_file

	#============================
	def _concatenate_video(self, segment_files: list, output_file: str) -> None:
		if len(segment_files) == 0:
			raise RuntimeError("no video segments to concatenate")
		if len(segment_files) == 1:
			shutil.copy(segment_files[0], output_file)
			return
		cmd = "mkvmerge "
		for segment in segment_files:
			cmd += f" {segment} + "
		cmd = cmd[:-2]
		cmd += f" -o {output_file} "
		runCmd(cmd)
		ensure_file_exists(output_file)

	#============================
	def _concatenate_audio(self, segment_files: list, output_file: str) -> None:
		if len(segment_files) == 0:
			raise RuntimeError("no audio segments to concatenate")
		if len(segment_files) == 1:
			shutil.copy(segment_files[0], output_file)
			return
		cmd = "sox "
		for segment in segment_files:
			cmd += f" {segment} "
		cmd += f" {output_file} "
		runCmd(cmd)
		ensure_file_exists(output_file)

	#============================
	def _mux_output(self, video_file: str, audio_file: str, output_file: str) -> None:
		encoded_audio = self._encode_audio_if_needed(audio_file)
		cmd = f"mkvmerge -A -S {video_file} -D -S {encoded_audio} -o {output_file}"
		runCmd(cmd)
		ensure_file_exists(output_file)
		print(f"mpv {output_file}")
		if not self.keep_temp and encoded_audio != audio_file:
			os.remove(encoded_audio)

	#============================
	def _cleanup_temp(self, temp_files: list) -> None:
		for filepath in temp_files:
			if filepath and os.path.exists(filepath):
				os.remove(filepath)

	#============================
	def _make_temp_path(self, filename: str) -> str:
		self.temp_counter += 1
		tag = f"{make_timestamp()}-{self.temp_counter:04d}"
		return os.path.join(self.cache_dir, f"{tag}-{filename}")

	#============================
	def _encode_audio_if_needed(self, audio_file: str) -> str:
		audio_codec = self.output.get('audio_codec', 'pcm_s16le')
		if audio_codec in ('pcm_s16le', 'wav', 'pcm'):
			return audio_file
		if audio_codec == 'copy':
			return audio_file
		encoded_file = self._make_temp_path("audio-encoded.mka")
		cmd = "ffmpeg -y "
		cmd += f" -i '{audio_file}' "
		cmd += f" -acodec {audio_codec} "
		cmd += f" -ar {self.profile['sample_rate']} -ac {self.profile['channels']} "
		cmd += " -f matroska "
		cmd += f" '{encoded_file}' "
		runCmd(cmd)
		ensure_file_exists(encoded_file)
		return encoded_file

#============================================
#============================================
#============================================


def main():
	args = parse_args()
	project = EmwyProject(args.yamlfile, output_override=args.output_file,
		dry_run=args.dry_run)
	project.run()


if __name__ == '__main__':
	main()
