#!/usr/bin/env python3

import os
import tempfile
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
		self.cache_dir_created = False
		self.temp_counter = 0
		self.data = {}
		self.timeline = {}
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
		dry_run: bool = False, keep_temp: bool = False, cache_dir: str = None):
		self.yaml_file = yaml_file
		self.output_override = output_override
		self.dry_run = dry_run
		self.keep_temp = keep_temp
		self.cache_dir = cache_dir

	#============================
	def load(self) -> ProjectData:
		project = ProjectData()
		project.yaml_file = self.yaml_file
		project.output_override = self.output_override
		project.dry_run = self.dry_run
		project.keep_temp = self.keep_temp
		cache_dir = self.cache_dir
		cache_dir_created = False
		if cache_dir is None:
			cache_dir = tempfile.mkdtemp(prefix="emwy-run-")
			cache_dir_created = True
		else:
			if not os.path.exists(cache_dir):
				os.makedirs(cache_dir)
		project.cache_dir = cache_dir
		project.cache_dir_created = cache_dir_created
		project.data = self._load_yaml()
		self._validate_required_keys(project.data)
		project.profile = self._parse_profile(project.data.get('profile'))
		project.defaults = self._parse_defaults(project.data.get('defaults', {}))
		project.assets = self._parse_assets(project.data.get('assets', {}))
		if project.data.get('timeline') is not None:
			project.timeline = project.data.get('timeline', {})
			(compiled_playlists, compiled_stack) = self._compile_timeline(project,
				project.timeline)
			project.data['playlists'] = compiled_playlists
			project.data['stack'] = compiled_stack
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
		if data.get('timeline') is None:
			raise RuntimeError("timeline.segments is required for v2 projects")
		if data.get('playlists') is not None or data.get('stack') is not None:
			raise RuntimeError("playlists/stack are compiled-only; use timeline.segments")
		required_keys = ('profile', 'assets', 'timeline', 'output')
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
			'overlay_text_styles': assets.get('overlay_text_styles', {}),
			'playback_styles': assets.get('playback_styles', {}),
		}
		for group_name, group in asset_groups.items():
			if not isinstance(group, dict):
				raise RuntimeError(f"assets.{group_name} must be a mapping")
		return asset_groups

	#============================
	def _compile_timeline(self, project: ProjectData, timeline: dict) -> tuple:
		if not isinstance(timeline, dict):
			raise RuntimeError("timeline must be a mapping")
		segments = timeline.get('segments', [])
		if not isinstance(segments, list) or len(segments) == 0:
			raise RuntimeError("timeline.segments must be a non-empty list")
		video_entries = []
		audio_entries = []
		for segment in segments:
			self._compile_segment(project, segment, video_entries, audio_entries)
		base_frames = self._calculate_playlist_frames(project, video_entries, 'video')
		playlists = {
			'video_base': {
				'kind': 'video',
				'playlist': video_entries,
			},
			'audio_main': {
				'kind': 'audio',
				'playlist': audio_entries,
			},
		}
		tracks = [
			{'playlist': 'video_base', 'role': 'base'},
			{'playlist': 'audio_main', 'role': 'main'},
		]
		overlays = self._compile_overlay_tracks(project, timeline, playlists,
			tracks, base_frames, segments)
		stack = {'tracks': tracks}
		if len(overlays) > 0:
			stack['overlays'] = overlays
		return (playlists, stack)

	#============================
	def _compile_overlay_tracks(self, project: ProjectData, timeline: dict,
		playlists: dict, tracks: list, base_frames: int, base_segments: list) -> list:
		overlays = []
		overlay_tracks = timeline.get('overlays', [])
		if overlay_tracks is None:
			return overlays
		if not isinstance(overlay_tracks, list):
			raise RuntimeError("timeline.overlays must be a list")
		for index, overlay in enumerate(overlay_tracks, start=1):
			overlay_info = self._compile_overlay_track(project, overlay, index,
				playlists, tracks, base_frames, base_segments)
			if overlay_info is not None:
				overlays.append(overlay_info)
		return overlays

	#============================
	def _compile_overlay_track(self, project: ProjectData, overlay: dict, index: int,
		playlists: dict, tracks: list, base_frames: int, base_segments: list) -> dict:
		if not isinstance(overlay, dict):
			raise RuntimeError("timeline.overlays entries must be mappings")
		if overlay.get('enabled') is False:
			return None
		segments = overlay.get('segments')
		overlay_entries = []
		template = overlay.get('template')
		apply_settings = overlay.get('apply')
		if segments is not None:
			if template is not None or apply_settings is not None:
				raise RuntimeError("overlay track cannot mix segments with template/apply")
			if not isinstance(segments, list) or len(segments) == 0:
				raise RuntimeError("overlay track requires non-empty segments list")
			for segment in segments:
				self._compile_overlay_segment(project, segment, overlay_entries)
		else:
			if template is None and apply_settings is None:
				raise RuntimeError("overlay track requires segments or template/apply")
			overlay_entries = self._compile_overlay_template(project, base_segments,
				template, apply_settings)
		overlay_frames = self._calculate_playlist_frames(project, overlay_entries,
			'video')
		if overlay_frames < base_frames:
			fill_frames = base_frames - overlay_frames
			fill_duration = self._format_duration_from_frames(fill_frames,
				project.profile['fps'])
			overlay_entries.append({'blank': {
				'duration': fill_duration,
				'fill': 'transparent',
			}})
		if overlay_frames > base_frames:
			raise RuntimeError("overlay track duration exceeds base timeline duration")
		overlay_id = overlay.get('id', f"{index}")
		playlist_id = f"video_overlay_{overlay_id}"
		if playlists.get(playlist_id) is not None:
			raise RuntimeError(f"overlay playlist id already exists: {playlist_id}")
		playlists[playlist_id] = {
			'kind': 'video',
			'playlist': overlay_entries,
		}
		tracks.append({'playlist': playlist_id, 'role': 'overlay'})
		duration = self._format_duration_from_frames(base_frames, project.profile['fps'])
		geometry = overlay.get('geometry')
		opacity = overlay.get('opacity')
		overlays = {
			'a': 'video_base',
			'b': playlist_id,
			'kind': overlay.get('kind', 'over'),
			'in': '0',
			'out': duration,
		}
		if geometry is not None:
			overlays['geometry'] = geometry
		if opacity is not None:
			overlays['opacity'] = opacity
		return overlays

	#============================
	def _compile_overlay_template(self, project: ProjectData, base_segments: list,
		template: dict, apply_settings: dict) -> list:
		if template is None or apply_settings is None:
			raise RuntimeError("overlay template requires template and apply settings")
		if not isinstance(template, dict) or len(template.keys()) != 1:
			raise RuntimeError("overlay template must be a mapping with one entry")
		if not isinstance(apply_settings, dict):
			raise RuntimeError("overlay apply settings must be a mapping")
		template_type = list(template.keys())[0]
		template_data = template.get(template_type)
		if template_type != 'generator':
			raise RuntimeError("overlay template only supports generator entries")
		if not isinstance(template_data, dict):
			raise RuntimeError("overlay template generator must be a mapping")
		if template_data.get('duration') is not None:
			raise RuntimeError("overlay template generator must not set duration")
		apply_kind = apply_settings.get('kind', 'speed')
		stream_kind = None
		min_speed = None
		max_speed = None
		apply_style = None
		playback_overlay_style = None
		if apply_kind == 'speed':
			stream_kind = apply_settings.get('stream', 'video')
			if stream_kind not in ('video', 'audio'):
				raise RuntimeError("overlay apply stream must be video or audio")
			min_speed_raw = apply_settings.get('min_speed')
			max_speed_raw = apply_settings.get('max_speed')
			if min_speed_raw is None and max_speed_raw is None:
				raise RuntimeError("overlay apply speed requires min_speed or max_speed")
			if min_speed_raw is not None:
				min_speed = utils.parse_speed(min_speed_raw, project.defaults['speed'])
			if max_speed_raw is not None:
				max_speed = utils.parse_speed(max_speed_raw, project.defaults['speed'])
			if min_speed is not None and max_speed is not None and min_speed > max_speed:
				raise RuntimeError("overlay apply min_speed must be <= max_speed")
		elif apply_kind == 'playback_style':
			apply_style = apply_settings.get('style')
			if apply_style is None:
				raise RuntimeError("overlay apply playback_style requires style")
			playback_style = project.assets.get('playback_styles', {}).get(apply_style)
			if playback_style is None:
				raise RuntimeError(f"playback style {apply_style} not found in assets.playback_styles")
			if not isinstance(playback_style, dict):
				raise RuntimeError("playback style must be a mapping")
			playback_overlay_style = playback_style.get('overlay_text_style')
		else:
			raise RuntimeError("overlay apply kind must be speed or playback_style")
		if not isinstance(base_segments, list) or len(base_segments) == 0:
			raise RuntimeError("overlay template requires base timeline segments")
		overlay_entries = []
		for segment in base_segments:
			if not isinstance(segment, dict) or len(segment.keys()) != 1:
				raise RuntimeError("timeline.segments entries must have one key")
			entry_type = list(segment.keys())[0]
			entry_data = segment.get(entry_type)
			if isinstance(entry_data, dict) and entry_data.get('enabled') is False:
				continue
			if entry_type not in ('source', 'blank', 'generator'):
				raise RuntimeError("overlay template only supports source/blank/generator")
			duration_frames = self._calculate_entry_frames(project, entry_type,
				entry_data, 'video')
			duration = self._format_duration_from_frames(duration_frames,
				project.profile['fps'])
			apply_template = False
			speed_value = None
			if entry_type == 'source':
				if apply_kind == 'speed':
					speed_value = self._segment_speed_value(project, entry_data, stream_kind)
					apply_template = self._speed_in_range(speed_value, min_speed, max_speed)
				else:
					entry_style = entry_data.get('style')
					apply_template = entry_style == apply_style
			if apply_template:
				if apply_kind == 'playback_style':
					speed_value = self._segment_speed_value(project, entry_data, 'video')
				generator_entry = dict(template_data)
				generator_entry['duration'] = duration
				if apply_kind == 'playback_style' and template_data.get('kind') == 'overlay_text':
					if generator_entry.get('style') is None:
						if playback_overlay_style is None:
							raise RuntimeError(
								"overlay_text template requires style or playback style overlay_text_style"
							)
						generator_entry['style'] = playback_overlay_style
				speed_text = self._format_speed_text(speed_value)
				generator_entry = self._apply_speed_template(generator_entry, speed_text)
				self._compile_overlay_segment(project, {'generator': generator_entry},
					overlay_entries)
			else:
				self._compile_overlay_segment(project, {'blank': {
					'duration': duration,
					'fill': 'transparent',
				}}, overlay_entries)
		return overlay_entries

	#============================
	def _segment_speed_value(self, project: ProjectData, entry_data: dict,
		stream_kind: str) -> Decimal:
		speed_value = None
		if stream_kind == 'video':
			if entry_data.get('video') is not None:
				speed_value = entry_data['video'].get('speed')
		if stream_kind == 'audio':
			if entry_data.get('audio') is not None:
				speed_value = entry_data['audio'].get('speed')
		return utils.parse_speed(speed_value, project.defaults['speed'])

	#============================
	def _speed_in_range(self, speed_value: Decimal, min_speed,
		max_speed) -> bool:
		if min_speed is not None and speed_value < min_speed:
			return False
		if max_speed is not None and speed_value > max_speed:
			return False
		return True

	#============================
	def _format_speed_text(self, speed_value: Decimal) -> str:
		speed_text = f"{speed_value:.6f}"
		if '.' in speed_text:
			speed_text = speed_text.rstrip('0').rstrip('.')
		return speed_text

	#============================
	def _apply_speed_template(self, template_data: dict, speed_text: str) -> dict:
		updated = dict(template_data)
		title_text = updated.get('title')
		if isinstance(title_text, str):
			updated['title'] = title_text.replace("{speed}", speed_text)
		body_text = updated.get('text')
		if isinstance(body_text, str):
			updated['text'] = body_text.replace("{speed}", speed_text)
		return updated

	#============================
	def _compile_overlay_segment(self, project: ProjectData, segment: dict,
		video_entries: list) -> None:
		if not isinstance(segment, dict) or len(segment.keys()) != 1:
			raise RuntimeError("overlay segments entries must have one key")
		entry_type = list(segment.keys())[0]
		entry_data = segment.get(entry_type)
		if isinstance(entry_data, dict) and entry_data.get('enabled') is False:
			return
		if entry_type == 'source':
			self._compile_overlay_source_segment(project, entry_data, video_entries)
			return
		if entry_type == 'blank':
			if not isinstance(entry_data, dict):
				raise RuntimeError("overlay blank segment must be a mapping")
			fill = entry_data.get('fill', 'transparent')
			if fill not in ('black', 'transparent'):
				raise RuntimeError("overlay blank fill must be black or transparent")
			video_entries.append({'blank': {
				'duration': entry_data.get('duration'),
				'fill': fill,
			}})
			return
		if entry_type == 'generator':
			self._compile_overlay_generator_segment(project, entry_data, video_entries)
			return
		raise RuntimeError(f"unsupported overlay segment type {entry_type}")

	#============================
	def _compile_overlay_source_segment(self, project: ProjectData,
		entry_data: dict, video_entries: list) -> None:
		if not isinstance(entry_data, dict):
			raise RuntimeError("overlay source segment must be a mapping")
		asset_id = entry_data.get('asset')
		if asset_id is None:
			raise RuntimeError("overlay source entry must include asset")
		if asset_id not in project.assets.get('video', {}):
			raise RuntimeError("overlay source entry requires a video asset")
		video_entries.append({'source': entry_data})

	#============================
	def _compile_overlay_generator_segment(self, project: ProjectData,
		entry_data: dict, video_entries: list) -> None:
		if not isinstance(entry_data, dict):
			raise RuntimeError("overlay generator segment must be a mapping")
		gen_kind = entry_data.get('kind')
		if gen_kind is None:
			raise RuntimeError("overlay generator entry must include kind")
		video_kinds = ('chapter_card', 'title_card', 'overlay_text', 'black', 'still')
		if gen_kind not in video_kinds:
			raise RuntimeError(f"unsupported overlay generator kind {gen_kind}")
		if gen_kind in ('chapter_card', 'title_card'):
			title_text = entry_data.get('title', entry_data.get('text', ''))
			if title_text == '':
				raise RuntimeError("chapter_card/title_card requires title or text")
			style_id = entry_data.get('style')
			if style_id is not None:
				style = project.assets.get('cards', {}).get(style_id)
				if style is None:
					raise RuntimeError(f"card style {style_id} not found in assets.cards")
		if gen_kind == 'overlay_text':
			title_text = entry_data.get('text', entry_data.get('title', ''))
			if title_text == '':
				raise RuntimeError("overlay_text requires text or title")
			style_id = entry_data.get('style')
			if style_id is not None:
				style = project.assets.get('overlay_text_styles', {}).get(style_id)
				if style is None:
					raise RuntimeError(
						f"overlay text style {style_id} not found in assets.overlay_text_styles"
					)
		if gen_kind == 'still':
			asset_id = entry_data.get('asset')
			if asset_id is None:
				raise RuntimeError("still generator requires asset")
			image_asset = project.assets.get('image', {}).get(asset_id)
			if image_asset is None:
				raise RuntimeError(f"image asset {asset_id} not found in assets.image")
		duration = entry_data.get('duration')
		if duration is None:
			raise RuntimeError("generator duration must be provided for overlay segments")
		video_entries.append({'generator': entry_data})

	#============================
	def _calculate_playlist_frames(self, project: ProjectData, entries: list,
		kind: str) -> int:
		total_frames = 0
		for entry in entries:
			if not isinstance(entry, dict) or len(entry.keys()) != 1:
				raise RuntimeError("playlist entries must have one key")
			entry_type = list(entry.keys())[0]
			entry_data = entry.get(entry_type)
			total_frames += self._calculate_entry_frames(project, entry_type,
				entry_data, kind)
		return total_frames

	#============================
	def _calculate_entry_frames(self, project: ProjectData, entry_type: str,
		entry_data: dict, kind: str) -> int:
		if entry_type == 'source':
			speed_value = None
			if kind == 'video':
				if entry_data.get('video') is not None:
					speed_value = entry_data['video'].get('speed')
			else:
				if entry_data.get('audio') is not None:
					speed_value = entry_data['audio'].get('speed')
			return self._calculate_output_frames(project, entry_data, speed_value)
		if entry_type == 'blank':
			duration = utils.parse_timecode(entry_data.get('duration'))
			return utils.frames_from_seconds(duration, project.profile['fps'])
		if entry_type == 'generator':
			duration = utils.parse_timecode(entry_data.get('duration'))
			return utils.frames_from_seconds(duration, project.profile['fps'])
		raise RuntimeError(f"unsupported entry type for duration calc {entry_type}")

	#============================
	def _compile_segment(self, project: ProjectData, segment: dict,
		video_entries: list, audio_entries: list) -> None:
		if not isinstance(segment, dict) or len(segment.keys()) != 1:
			raise RuntimeError("timeline.segments entries must have one key")
		entry_type = list(segment.keys())[0]
		entry_data = segment.get(entry_type)
		if isinstance(entry_data, dict) and entry_data.get('enabled') is False:
			return
		if entry_type == 'source':
			self._compile_source_segment(project, entry_data,
				video_entries, audio_entries)
			return
		if entry_type == 'blank':
			if not isinstance(entry_data, dict):
				raise RuntimeError("blank segment must be a mapping")
			video_entries.append({'blank': entry_data})
			audio_entries.append({'blank': entry_data})
			return
		if entry_type == 'generator':
			self._compile_generator_segment(project, entry_data,
				video_entries, audio_entries)
			return
		raise RuntimeError(f"unsupported segment type {entry_type}")

	#============================
	def _compile_source_segment(self, project: ProjectData, entry_data: dict,
		video_entries: list, audio_entries: list) -> None:
		if not isinstance(entry_data, dict):
			raise RuntimeError("source segment must be a mapping")
		if entry_data.get('take') is not None:
			raise RuntimeError("take is not supported in v2")
		asset_id = entry_data.get('asset')
		if asset_id is None:
			raise RuntimeError("source entry must include asset")
		has_video = asset_id in project.assets.get('video', {})
		has_audio = asset_id in project.assets.get('audio', {})
		if asset_id in project.assets.get('video', {}):
			has_audio = True
		if not has_video and not has_audio:
			raise RuntimeError(f"asset {asset_id} not found in assets.video or assets.audio")
		fill_missing = self._normalize_fill_missing(entry_data.get('fill_missing'))
		if not has_video and (fill_missing is None or 'video' not in fill_missing):
			raise RuntimeError("source entry missing video stream requires fill_missing.video")
		if not has_audio and (fill_missing is None or 'audio' not in fill_missing):
			raise RuntimeError("source entry missing audio stream requires fill_missing.audio")
		self._apply_source_style(project, entry_data)
		self._sync_source_speeds(project, entry_data)
		if has_video:
			video_entries.append({'source': entry_data})
		else:
			duration = self._duration_for_missing_stream(project, entry_data,
				stream_kind='audio')
			video_entries.append({'blank': {
				'duration': duration,
				'fill': fill_missing.get('video', 'black'),
			}})
		if has_audio:
			audio_entries.append({'source': entry_data})
		else:
			duration = self._duration_for_missing_stream(project, entry_data,
				stream_kind='video')
			audio_entries.append({'blank': {
				'duration': duration,
			}})

	#============================
	def _apply_source_style(self, project: ProjectData, entry_data: dict) -> None:
		style_id = entry_data.get('style')
		if style_id is None:
			return
		styles = project.assets.get('playback_styles', {})
		style = styles.get(style_id)
		if style is None:
			raise RuntimeError(f"playback style {style_id} not found in assets.playback_styles")
		if not isinstance(style, dict):
			raise RuntimeError("playback style must be a mapping")
		speed_value = style.get('speed')
		if speed_value is None:
			raise RuntimeError("playback style requires speed")
		style_speed = utils.parse_speed(speed_value, project.defaults['speed'])
		video_settings = entry_data.get('video')
		audio_settings = entry_data.get('audio')
		video_speed_value = None
		audio_speed_value = None
		if isinstance(video_settings, dict):
			video_speed_value = video_settings.get('speed')
		if isinstance(audio_settings, dict):
			audio_speed_value = audio_settings.get('speed')
		if video_speed_value is not None:
			video_speed = utils.parse_speed(video_speed_value, project.defaults['speed'])
			if video_speed != style_speed:
				raise RuntimeError("video.speed must match playback style speed")
		if audio_speed_value is not None:
			audio_speed = utils.parse_speed(audio_speed_value, project.defaults['speed'])
			if audio_speed != style_speed:
				raise RuntimeError("audio.speed must match playback style speed")
		if video_settings is None:
			video_settings = {}
			entry_data['video'] = video_settings
		if audio_settings is None:
			audio_settings = {}
			entry_data['audio'] = audio_settings
		if video_speed_value is None:
			video_settings['speed'] = speed_value
		if audio_speed_value is None:
			audio_settings['speed'] = speed_value
		return

	#============================
	def _sync_source_speeds(self, project: ProjectData, entry_data: dict) -> None:
		video_settings = entry_data.get('video')
		audio_settings = entry_data.get('audio')
		video_speed_set = False
		audio_speed_set = False
		video_speed_value = None
		audio_speed_value = None
		if isinstance(video_settings, dict) and video_settings.get('speed') is not None:
			video_speed_set = True
			video_speed_value = video_settings.get('speed')
		if isinstance(audio_settings, dict) and audio_settings.get('speed') is not None:
			audio_speed_set = True
			audio_speed_value = audio_settings.get('speed')
		if not video_speed_set and not audio_speed_set:
			return
		if video_speed_set and audio_speed_set:
			video_speed = utils.parse_speed(video_speed_value, project.defaults['speed'])
			audio_speed = utils.parse_speed(audio_speed_value, project.defaults['speed'])
			if video_speed != audio_speed:
				raise RuntimeError("video.speed and audio.speed must match for source entries")
			return
		speed_value = video_speed_value if video_speed_set else audio_speed_value
		if video_settings is None:
			video_settings = {}
			entry_data['video'] = video_settings
		if audio_settings is None:
			audio_settings = {}
			entry_data['audio'] = audio_settings
		if not video_speed_set:
			video_settings['speed'] = speed_value
		if not audio_speed_set:
			audio_settings['speed'] = speed_value
		return

	#============================
	def _compile_generator_segment(self, project: ProjectData, entry_data: dict,
		video_entries: list, audio_entries: list) -> None:
		if not isinstance(entry_data, dict):
			raise RuntimeError("generator segment must be a mapping")
		gen_kind = entry_data.get('kind')
		if gen_kind is None:
			raise RuntimeError("generator entry must include kind")
		if gen_kind == 'overlay_text':
			raise RuntimeError("overlay_text generator is only supported in overlays")
		video_kinds = ('chapter_card', 'title_card', 'black', 'still')
		audio_kinds = ('silence',)
		has_video = gen_kind in video_kinds
		has_audio = gen_kind in audio_kinds
		if not has_video and not has_audio:
			raise RuntimeError(f"unsupported generator kind {gen_kind}")
		if gen_kind in ('chapter_card', 'title_card'):
			title_text = entry_data.get('title', entry_data.get('text', ''))
			if title_text == '':
				raise RuntimeError("chapter_card/title_card requires title or text")
			style_id = entry_data.get('style')
			if style_id is not None:
				style = project.assets.get('cards', {}).get(style_id)
				if style is None:
					raise RuntimeError(f"card style {style_id} not found in assets.cards")
			background = self._resolve_card_background(entry_data, style)
			if isinstance(background, dict) and background.get('kind') == 'transparent':
				raise RuntimeError("transparent card background is only supported in overlays")
		if gen_kind == 'still':
			asset_id = entry_data.get('asset')
			if asset_id is None:
				raise RuntimeError("still generator requires asset")
			image_asset = project.assets.get('image', {}).get(asset_id)
			if image_asset is None:
				raise RuntimeError(f"image asset {asset_id} not found in assets.image")
		fill_missing = self._normalize_fill_missing(entry_data.get('fill_missing'))
		duration = entry_data.get('duration')
		if duration is None:
			raise RuntimeError("generator duration must be provided for segments")
		if has_video:
			video_entries.append({'generator': entry_data})
		else:
			if fill_missing is None or 'video' not in fill_missing:
				raise RuntimeError("generator entry missing video stream requires fill_missing.video")
			video_entries.append({'blank': {
				'duration': duration,
				'fill': fill_missing.get('video', 'black'),
			}})
		if has_audio:
			audio_entries.append({'generator': entry_data})
		else:
			if fill_missing is None or 'audio' not in fill_missing:
				raise RuntimeError("generator entry missing audio stream requires fill_missing.audio")
			audio_entries.append({'blank': {
				'duration': duration,
			}})

	#============================
	def _normalize_fill_missing(self, fill_missing) -> dict:
		if fill_missing is None:
			return None
		if fill_missing is True:
			return {'video': 'black', 'audio': 'silence'}
		if not isinstance(fill_missing, dict):
			raise RuntimeError("fill_missing must be true or a mapping")
		result = {}
		if fill_missing.get('video') is not None:
			video_value = fill_missing.get('video')
			if video_value != 'black':
				raise RuntimeError("fill_missing.video must be black")
			result['video'] = video_value
		if fill_missing.get('audio') is not None:
			audio_value = fill_missing.get('audio')
			if audio_value != 'silence':
				raise RuntimeError("fill_missing.audio must be silence")
			result['audio'] = audio_value
		if len(result) == 0:
			raise RuntimeError("fill_missing must include video and/or audio")
		return result

	#============================
	def _resolve_card_background(self, data: dict, style: dict) -> dict:
		if isinstance(data, dict) and data.get('background') is not None:
			return data.get('background')
		if isinstance(style, dict) and style.get('background') is not None:
			return style.get('background')
		background_image = None
		if isinstance(data, dict):
			background_image = data.get('background_image')
		if background_image is None and isinstance(style, dict):
			background_image = style.get('background_image')
		if background_image is not None:
			return {'kind': 'image', 'asset': background_image}
		return None

	#============================
	def _duration_for_missing_stream(self, project: ProjectData,
		entry_data: dict, stream_kind: str) -> str:
		speed_value = None
		if stream_kind == 'video':
			if entry_data.get('video') is not None:
				speed_value = entry_data['video'].get('speed')
		if stream_kind == 'audio':
			if entry_data.get('audio') is not None:
				speed_value = entry_data['audio'].get('speed')
		output_frames = self._calculate_output_frames(project, entry_data, speed_value)
		duration = self._format_duration_from_frames(output_frames,
			project.profile['fps'])
		return duration

	#============================
	def _calculate_output_frames(self, project: ProjectData, entry_data: dict,
		speed_value) -> int:
		in_time = utils.parse_timecode(entry_data.get('in'))
		out_time = utils.parse_timecode(entry_data.get('out'))
		in_frame = utils.frames_from_seconds(in_time, project.profile['fps'])
		out_frame = utils.frames_from_seconds(out_time, project.profile['fps'])
		if out_frame <= in_frame:
			raise RuntimeError("source entry requires in < out")
		source_frames = out_frame - in_frame
		speed = utils.parse_speed(speed_value, project.defaults['speed'])
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
		return output_frames

	#============================
	def _format_duration_from_frames(self, frames: int, fps: Fraction) -> str:
		seconds_fraction = Fraction(frames, 1) / fps
		numerator = Decimal(seconds_fraction.numerator)
		denominator = Decimal(seconds_fraction.denominator)
		value = numerator / denominator
		return f"{value:.6f}".rstrip('0').rstrip('.')

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
			if parsed_entry is None:
				continue
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
		if isinstance(entry_data, dict) and entry_data.get('enabled') is False:
			return None
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
		if entry_data.get('take') is not None:
			raise RuntimeError("take is not supported in v2")
		asset_id = entry_data.get('asset')
		if asset_id is None:
			raise RuntimeError("source entry must include asset")
		asset_group = 'video' if kind == 'video' else 'audio'
		asset = project.assets.get(asset_group, {}).get(asset_id)
		if asset is None and kind == 'audio':
			asset = project.assets.get('video', {}).get(asset_id)
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
		audio_tracks = 0
		parsed_tracks = []
		for track in tracks:
			if not isinstance(track, dict):
				raise RuntimeError("stack.tracks entries must be a mapping")
			playlist_id = track.get('playlist')
			role = track.get('role')
			if playlist_id not in project.playlists:
				raise RuntimeError(f"track playlist {playlist_id} not found")
			kind = project.playlists[playlist_id]['kind']
			if kind == 'video' and role == 'base':
				base_video = playlist_id
			if kind == 'audio' and role == 'main':
				main_audio = playlist_id
			if kind == 'audio':
				audio_tracks += 1
			parsed_tracks.append({
				'playlist': playlist_id,
				'role': role,
			})
		if base_video is None:
			raise RuntimeError("stack must include a base video playlist")
		if audio_tracks > 0 and main_audio is None:
			raise RuntimeError("stack must include a main audio playlist")
		source_audio = stack.get('source_audio', True)
		if not isinstance(source_audio, bool):
			raise RuntimeError("stack.source_audio must be true or false")
		overlays = self._parse_overlays(project, stack.get('overlays', []),
			base_video)
		self._validate_base_playlist_blanks(project, base_video)
		stack_data = {
			'base_video': base_video,
			'main_audio': main_audio,
			'tracks': parsed_tracks,
			'source_audio': source_audio,
		}
		if len(overlays) > 0:
			stack_data['overlays'] = overlays
		return stack_data

	#============================
	def _parse_overlays(self, project: ProjectData, overlays_raw, base_video: str) -> list:
		if overlays_raw is None:
			return []
		if not isinstance(overlays_raw, list):
			raise RuntimeError("stack.overlays must be a list")
		parsed = []
		base_duration = project.playlists[base_video]['duration_frames']
		for overlay in overlays_raw:
			parsed.append(self._parse_overlay(project, overlay, base_duration))
		return parsed

	#============================
	def _parse_overlay(self, project: ProjectData, overlay: dict,
		base_duration: int) -> dict:
		if not isinstance(overlay, dict):
			raise RuntimeError("overlay entries must be mappings")
		playlist_a = overlay.get('a')
		playlist_b = overlay.get('b')
		if playlist_a is None or playlist_b is None:
			raise RuntimeError("overlay entries require a and b playlists")
		if playlist_a not in project.playlists or playlist_b not in project.playlists:
			raise RuntimeError("overlay playlists must exist in compiled playlists")
		if project.playlists[playlist_a]['kind'] != 'video':
			raise RuntimeError("overlay playlist a must be video")
		if project.playlists[playlist_b]['kind'] != 'video':
			raise RuntimeError("overlay playlist b must be video")
		kind = overlay.get('kind', 'over')
		if kind != 'over':
			raise RuntimeError("overlay kind must be over")
		geometry = overlay.get('geometry', [0.0, 0.0, 1.0, 1.0])
		if not isinstance(geometry, list) or len(geometry) != 4:
			raise RuntimeError("overlay geometry must be [x, y, w, h]")
		for value in geometry:
			if not isinstance(value, (int, float)):
				raise RuntimeError("overlay geometry values must be numbers")
			if value < 0 or value > 1:
				raise RuntimeError("overlay geometry values must be between 0 and 1")
		opacity = overlay.get('opacity', 1.0)
		if not isinstance(opacity, (int, float)):
			raise RuntimeError("overlay opacity must be numeric")
		if opacity < 0 or opacity > 1:
			raise RuntimeError("overlay opacity must be between 0 and 1")
		in_time = overlay.get('in', '0')
		out_time = overlay.get('out')
		in_frames = utils.frames_from_seconds(utils.parse_timecode(in_time),
			project.profile['fps'])
		if out_time is None:
			out_frames = base_duration
		else:
			out_frames = utils.frames_from_seconds(utils.parse_timecode(out_time),
				project.profile['fps'])
		if in_frames < 0 or out_frames <= in_frames:
			raise RuntimeError("overlay in/out range is invalid")
		if out_frames > base_duration:
			if out_frames - base_duration <= 1:
				out_frames = base_duration
			else:
				raise RuntimeError("overlay out time exceeds base duration")
		return {
			'a': playlist_a,
			'b': playlist_b,
			'kind': kind,
			'in_frames': in_frames,
			'out_frames': out_frames,
			'geometry': geometry,
			'opacity': float(opacity),
		}

	#============================
	def _validate_base_playlist_blanks(self, project: ProjectData, base_video: str) -> None:
		playlist = project.playlists.get(base_video)
		if playlist is None:
			return
		for entry in playlist.get('entries', []):
			if entry.get('type') == 'blank' and entry.get('fill') == 'transparent':
				raise RuntimeError("transparent blanks are only supported in overlays")

	#============================
	def _parse_output(self, project: ProjectData, output: dict) -> dict:
		if not isinstance(output, dict):
			raise RuntimeError("output must be a mapping")
		output_file = output.get('file')
		if project.output_override is not None:
			output_file = project.output_override
		if output_file is None:
			raise RuntimeError("output.file is required")
		merge_batch_threshold = int(output.get('merge_batch_threshold', 24))
		merge_batch_size = int(output.get('merge_batch_size', 8))
		if merge_batch_threshold < 0:
			raise RuntimeError("output.merge_batch_threshold must be >= 0")
		if merge_batch_size < 1:
			raise RuntimeError("output.merge_batch_size must be >= 1")
		return {
			'file': output_file,
			'video_codec': output.get('video_codec', 'libx265'),
			'audio_codec': output.get('audio_codec', 'pcm_s16le'),
			'crf': int(output.get('crf', 26)),
			'container': output.get('container', None),
			'merge_batch_threshold': merge_batch_threshold,
			'merge_batch_size': merge_batch_size,
		}
