#!/usr/bin/env python3

import os
import yaml
from decimal import Decimal
from fractions import Fraction
from emwylib.core import utils

#============================================

class ProjectData():
	def __init__(self):
		self.yaml_file = None
		self.output_override = None
		self.dry_run = False
		self.keep_temp = False
		self.cache_dir = None
		self.temp_counter = 0
		self.data = {}
		self.profile = {}
		self.defaults = {}
		self.assets = {}
		self.playlists = {}
		self.stack = {}
		self.output = {}
		self.pending_paired_audio = []

#============================================

class ProjectLoader():
	def __init__(self, yaml_file: str, output_override: str = None,
		dry_run: bool = False):
		self.yaml_file = yaml_file
		self.output_override = output_override
		self.dry_run = dry_run

	#============================
	def load(self) -> ProjectData:
		project = ProjectData()
		project.yaml_file = self.yaml_file
		project.output_override = self.output_override
		project.dry_run = self.dry_run
		project.keep_temp = os.environ.get('EMWY_KEEP_TEMP', '') == '1'
		project.cache_dir = os.environ.get('EMWY_CACHE_DIR', os.getcwd())
		project.data = self._load_yaml()
		self._validate_required_keys(project.data)
		project.profile = self._parse_profile(project.data.get('profile'))
		project.defaults = self._parse_defaults(project.data.get('defaults', {}))
		project.assets = self._parse_assets(project.data.get('assets', {}))
		project.playlists = self._parse_playlists(project, project.data.get('playlists', {}))
		project.stack = self._parse_stack(project, project.data.get('stack', {}))
		project.output = self._parse_output(project, project.data.get('output', {}))
		return project

	#============================
	def _load_yaml(self) -> dict:
		file_size = os.path.getsize(self.yaml_file)
		if file_size > 10 ** 7:
			raise RuntimeError("yaml file is larger than 10MB")
		with open(self.yaml_file, 'r') as data_file:
			data = yaml.safe_load(data_file)
		if not isinstance(data, dict):
			raise RuntimeError("v2 yaml must be a mapping at the top level")
		return data

	#============================
	def _validate_required_keys(self, data: dict) -> None:
		if data.get('emwy') != 2:
			raise RuntimeError("emwy must be set to 2 for v2 projects")
		required_keys = ('profile', 'assets', 'playlists', 'stack', 'output')
		for key in required_keys:
			if key not in data:
				raise RuntimeError(f"missing required key: {key}")

	#============================
	def _parse_profile(self, profile: dict) -> dict:
		if not isinstance(profile, dict):
			raise RuntimeError("profile must be a mapping")
		fps = utils.parse_fps(profile.get('fps'))
		resolution = profile.get('resolution')
		if not resolution or len(resolution) != 2:
			raise RuntimeError("profile.resolution must be [width, height]")
		width = int(resolution[0])
		height = int(resolution[1])
		audio = profile.get('audio', {})
		sample_rate = int(audio.get('sample_rate', 48000))
		channels_raw = audio.get('channels', 'stereo')
		(channel_count, audio_mode) = utils.normalize_channels(channels_raw)
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
			default_speed = utils.parse_speed(defaults['video'].get('speed'), default_speed)
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
	def _parse_playlists(self, project: ProjectData, playlists: dict) -> dict:
		if not isinstance(playlists, dict) or len(playlists) == 0:
			raise RuntimeError("playlists must be a non-empty mapping")
		parsed = {}
		for playlist_id, playlist in playlists.items():
			parsed[playlist_id] = self._parse_playlist(project, playlist_id, playlist)
		return parsed

	#============================
	def _parse_playlist(self, project: ProjectData, playlist_id: str,
		playlist: dict) -> dict:
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
			start_frames = total_frames
			parsed_entry = self._parse_playlist_entry(project, playlist_id, kind,
				entry, start_frames)
			parsed_entries.append(parsed_entry)
			total_frames += parsed_entry['duration_frames']
		return {
			'id': playlist_id,
			'kind': kind,
			'entries': parsed_entries,
			'duration_frames': total_frames,
		}

	#============================
	def _parse_playlist_entry(self, project: ProjectData, playlist_id: str,
		kind: str, entry: dict, start_frames: int) -> dict:
		if not isinstance(entry, dict) or len(entry.keys()) != 1:
			raise RuntimeError(f"playlist {playlist_id} entries must have one key")
		entry_type = list(entry.keys())[0]
		entry_data = entry.get(entry_type)
		if entry_type == 'source':
			return self._parse_source_entry(project, playlist_id, kind, entry_data)
		if entry_type == 'blank':
			return self._parse_blank_entry(project, playlist_id, kind, entry_data)
		if entry_type == 'generator':
			return self._parse_generator_entry(project, playlist_id, kind,
				entry_data, start_frames)
		if entry_type == 'nested':
			raise RuntimeError("nested entries are not supported yet")
		raise RuntimeError(f"unsupported entry type {entry_type}")

	#============================
	def _parse_source_entry(self, project: ProjectData, playlist_id: str,
		kind: str, entry_data: dict) -> dict:
		if not isinstance(entry_data, dict):
			raise RuntimeError(f"playlist {playlist_id} source entry must be mapping")
		asset_id = entry_data.get('asset')
		if asset_id is None:
			raise RuntimeError("source entry must include asset")
		asset_group = 'video' if kind == 'video' else 'audio'
		asset = project.assets.get(asset_group, {}).get(asset_id)
		if asset is None:
			raise RuntimeError(f"asset {asset_id} not found in assets.{asset_group}")
		asset_file = asset.get('file')
		if asset_file is None:
			raise RuntimeError(f"asset {asset_id} missing file")
		utils.ensure_file_exists(asset_file)
		in_time = utils.parse_timecode(entry_data.get('in'))
		out_time = utils.parse_timecode(entry_data.get('out'))
		in_frame = utils.frames_from_seconds(in_time, project.profile['fps'])
		out_frame = utils.frames_from_seconds(out_time, project.profile['fps'])
		if out_frame <= in_frame:
			raise RuntimeError("source entry requires in < out")
		source_frames = out_frame - in_frame
		default_speed = project.defaults['speed']
		entry_speed = None
		if kind == 'video':
			if entry_data.get('video') is not None:
				entry_speed = entry_data['video'].get('speed')
		else:
			if entry_data.get('audio') is not None:
				entry_speed = entry_data['audio'].get('speed')
		speed = utils.parse_speed(entry_speed, default_speed)
		if speed <= 0:
			raise RuntimeError("speed must be positive")
		speed_fraction = utils.decimal_to_fraction(speed)
		output_frames = source_frames
		if speed_fraction != 0:
			output_frames = utils.round_half_up_fraction(
				Fraction(source_frames, 1) / speed_fraction
			)
		if output_frames <= 0:
			raise RuntimeError("source entry duration is zero after speed change")
		norm_level = None
		if kind == 'audio':
			norm_level = project.defaults['normalize']
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
	def _parse_blank_entry(self, project: ProjectData, playlist_id: str,
		kind: str, entry_data: dict) -> dict:
		if not isinstance(entry_data, dict):
			raise RuntimeError(f"playlist {playlist_id} blank entry must be mapping")
		duration = utils.parse_timecode(entry_data.get('duration'))
		duration_frames = utils.frames_from_seconds(duration, project.profile['fps'])
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
	def _parse_generator_entry(self, project: ProjectData, playlist_id: str,
		kind: str, entry_data: dict, start_frames: int) -> dict:
		if not isinstance(entry_data, dict):
			raise RuntimeError(f"playlist {playlist_id} generator entry must be mapping")
		gen_kind = entry_data.get('kind')
		if gen_kind is None:
			raise RuntimeError("generator entry must include kind")
		duration = utils.parse_timecode(entry_data.get('duration'))
		duration_frames = utils.frames_from_seconds(duration, project.profile['fps'])
		if duration_frames <= 0:
			raise RuntimeError("generator duration must be positive")
		paired_audio = None
		if entry_data.get('paired_audio') is not None:
			if kind != 'video':
				raise RuntimeError("paired_audio is only supported on video playlists")
			paired_audio = self._parse_paired_audio(project,
				entry_data.get('paired_audio'), duration_frames, start_frames)
		return {
			'type': 'generator',
			'kind': gen_kind,
			'duration_frames': duration_frames,
			'data': entry_data,
			'paired_audio': paired_audio,
		}

	#============================
	def _parse_paired_audio(self, project: ProjectData, paired_audio: dict,
		duration_frames: int, start_frames: int) -> dict:
		if not isinstance(paired_audio, dict):
			raise RuntimeError("paired_audio must be a mapping")
		target_playlist = paired_audio.get('target_playlist')
		if target_playlist is None:
			raise RuntimeError("paired_audio requires target_playlist")
		source = paired_audio.get('source')
		if not isinstance(source, dict):
			raise RuntimeError("paired_audio.source must be a mapping")
		asset_id = source.get('asset')
		if asset_id is None:
			raise RuntimeError("paired_audio.source.asset is required")
		in_time = source.get('in')
		if in_time is None:
			raise RuntimeError("paired_audio.source.in is required")
		paired = {
			'target_playlist': target_playlist,
			'insert_at_frames': start_frames,
			'duration_frames': duration_frames,
			'source': {
				'asset': asset_id,
				'in': in_time,
				'out': source.get('out'),
				'audio': paired_audio.get('audio'),
			}
		}
		project.pending_paired_audio.append(paired)
		return paired

	#============================
	def _parse_stack(self, project: ProjectData, stack: dict) -> dict:
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
			if playlist_id not in project.playlists:
				raise RuntimeError(f"track playlist {playlist_id} not found")
			kind = project.playlists[playlist_id]['kind']
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
	def _parse_output(self, project: ProjectData, output: dict) -> dict:
		if not isinstance(output, dict):
			raise RuntimeError("output must be a mapping")
		output_file = output.get('file')
		if project.output_override is not None:
			output_file = project.output_override
		if output_file is None:
			raise RuntimeError("output.file is required")
		return {
			'file': output_file,
			'video_codec': output.get('video_codec', 'libx265'),
			'audio_codec': output.get('audio_codec', 'pcm_s16le'),
			'crf': int(output.get('crf', 26)),
			'container': output.get('container', None),
		}
