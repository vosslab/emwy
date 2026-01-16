
from decimal import Decimal
from fractions import Fraction
from emwylib.core import utils

#============================================

class TimelinePlanner():
	def __init__(self, project):
		self.project = project

	#============================
	def apply_paired_audio(self) -> None:
		pending = self.project.pending_paired_audio
		if len(pending) == 0:
			return
		sorted_pending = sorted(pending,
			key=lambda item: (item['target_playlist'], item['insert_at_frames']))
		for item in sorted_pending:
			self._apply_paired_item(item)
		self.project.pending_paired_audio = []

	#============================
	def _apply_paired_item(self, item: dict) -> None:
		target_playlist = item['target_playlist']
		playlist = self.project.playlists.get(target_playlist)
		if playlist is None:
			raise RuntimeError(f"paired_audio target playlist not found: {target_playlist}")
		if playlist['kind'] != 'audio':
			raise RuntimeError("paired_audio target playlist must be audio")
		current_frames = playlist['duration_frames']
		if item['insert_at_frames'] != current_frames:
			raise RuntimeError(
				"paired_audio requires target playlist duration to match "
				"the generator position"
			)
		entry = self._build_paired_audio_entry(target_playlist, item)
		playlist['entries'].append(entry)
		playlist['duration_frames'] += entry['duration_frames']

	#============================
	def _build_paired_audio_entry(self, playlist_id: str, item: dict) -> dict:
		source = item['source']
		duration_frames = item['duration_frames']
		in_time = utils.parse_timecode(source.get('in'))
		out_time = source.get('out')
		if out_time is None:
			duration_seconds = utils.seconds_from_frames(
				duration_frames, self.project.profile['fps']
			)
			out_time = Decimal(str(in_time)) + Decimal(str(duration_seconds))
		else:
			out_time = utils.parse_timecode(out_time)
		entry_data = {
			'asset': source.get('asset'),
			'in': float(in_time),
			'out': float(out_time),
		}
		if source.get('audio') is not None:
			entry_data['audio'] = source.get('audio')
		entry = self._parse_source_entry(playlist_id, entry_data)
		if entry['duration_frames'] != duration_frames:
			raise RuntimeError(
				"paired_audio duration must match the generator duration"
			)
		return entry

	#============================
	def _parse_source_entry(self, playlist_id: str, entry_data: dict) -> dict:
		asset_id = entry_data.get('asset')
		if asset_id is None:
			raise RuntimeError("paired_audio.source.asset is required")
		asset = self.project.assets.get('audio', {}).get(asset_id)
		if asset is None:
			raise RuntimeError(f"asset {asset_id} not found in assets.audio")
		asset_file = asset.get('file')
		if asset_file is None:
			raise RuntimeError(f"asset {asset_id} missing file")
		utils.ensure_file_exists(asset_file)
		in_time = utils.parse_timecode(entry_data.get('in'))
		out_time = utils.parse_timecode(entry_data.get('out'))
		in_frame = utils.frames_from_seconds(in_time, self.project.profile['fps'])
		out_frame = utils.frames_from_seconds(out_time, self.project.profile['fps'])
		if out_frame <= in_frame:
			raise RuntimeError("paired_audio source requires in < out")
		source_frames = out_frame - in_frame
		default_speed = self.project.defaults['speed']
		entry_speed = None
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
			raise RuntimeError("paired_audio duration is zero after speed change")
		norm_level = self.project.defaults['normalize']
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
	def validate_timeline(self) -> None:
		video_frames = self.project.playlists[self.project.stack['base_video']]['duration_frames']
		audio_frames = self.project.playlists[self.project.stack['main_audio']]['duration_frames']
		if video_frames != audio_frames:
			raise RuntimeError("base video and main audio durations do not match")
