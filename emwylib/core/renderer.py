
import os
import shutil
import decimal
from fractions import Fraction
from emwylib.core import utils
from emwylib.media import sox
from emwylib import titlecard
import PIL.Image
import PIL.ImageColor
import PIL.ImageDraw
import PIL.ImageFont

#============================================

class Renderer():
	def __init__(self, project):
		self.project = project

	#============================
	def render(self) -> None:
		if not utils.is_quiet_mode():
			utils.set_command_total(self._estimate_command_total())
		segment_track = self._render_segment_playlist(
			self.project.stack['base_video'],
			self.project.stack['main_audio']
		)
		overlays = self.project.stack.get('overlays', [])
		if len(overlays) > 0:
			segment_track = self._apply_overlays(segment_track, overlays)
		chapters = self._collect_chapters()
		self._finalize_output(segment_track, self.project.output['file'], chapters)
		if not self.project.keep_temp:
			self._cleanup_temp([segment_track])
		if not utils.is_quiet_mode():
			utils.set_command_total(None)

	#============================
	def _estimate_command_total(self) -> int:
		total = 0
		total += self._estimate_segment_playlist_commands(
			self.project.stack['base_video'],
			self.project.stack['main_audio']
		)
		overlays = self.project.stack.get('overlays', [])
		for overlay in overlays:
			playlist_id = overlay.get('b')
			if playlist_id is None:
				continue
			total += self._estimate_overlay_playlist_commands(playlist_id)
			total += 1
		chapters = self._collect_chapters()
		if len(chapters) > 0 and self._output_supports_chapters(self.project.output['file']):
			total += 1
		total += self._estimate_finalize_commands()
		return total

	#============================
	def _estimate_segment_playlist_commands(self, video_playlist_id: str,
		audio_playlist_id: str) -> int:
		video_playlist = self.project.playlists.get(video_playlist_id, {})
		audio_playlist = self.project.playlists.get(audio_playlist_id, {})
		video_entries = video_playlist.get('entries', [])
		audio_entries = audio_playlist.get('entries', [])
		count = 0
		for video_entry, audio_entry in zip(video_entries, audio_entries):
			count += self._estimate_video_entry_commands(video_entry)
			count += self._estimate_audio_entry_commands(audio_entry)
			count += 1
		count += self._estimate_concat_commands(len(video_entries))
		return count

	#============================
	def _estimate_overlay_playlist_commands(self, playlist_id: str) -> int:
		playlist = self.project.playlists.get(playlist_id, {})
		entries = playlist.get('entries', [])
		count = 0
		for entry in entries:
			count += self._estimate_video_entry_commands(entry)
		count += self._estimate_concat_commands(len(entries))
		return count

	#============================
	def _estimate_video_entry_commands(self, entry: dict) -> int:
		entry_type = entry.get('type')
		if entry_type in ('source', 'blank'):
			return 1
		if entry_type == 'generator':
			gen_kind = entry.get('kind')
			if gen_kind == 'overlay_text':
				data = entry.get('data', {})
				if isinstance(data, dict) and data.get('animate') is not None:
					return 2
			return 1
		return 0

	#============================
	def _estimate_audio_entry_commands(self, entry: dict) -> int:
		entry_type = entry.get('type')
		if entry_type == 'source':
			count = 1
			if entry.get('normalize') is not None:
				count += 1
			speed = float(entry.get('speed', 1.0))
			if abs(speed - 1.0) > 0.0001:
				count += 1
			return count
		if entry_type in ('blank', 'generator'):
			return 1
		return 0

	#============================
	def _estimate_concat_commands(self, segment_count: int) -> int:
		if segment_count <= 1:
			return 0
		threshold = self.project.output.get('merge_batch_threshold', 0)
		batch_size = self.project.output.get('merge_batch_size', 0)
		if threshold > 0 and batch_size > 0 and segment_count > threshold:
			batch_commands = 0
			for start_index in range(0, segment_count, batch_size):
				size = min(batch_size, segment_count - start_index)
				if size > 1:
					batch_commands += 1
			return batch_commands + 1
		return 1

	#============================
	def _estimate_finalize_commands(self) -> int:
		audio_codec = self.project.output.get('audio_codec', 'pcm_s16le')
		if audio_codec in ('pcm_s16le', 'wav', 'pcm', 'copy'):
			return 0
		return 1

	#============================
	def _render_segment_playlist(self, video_playlist_id: str,
		audio_playlist_id: str) -> str:
		video_playlist = self.project.playlists[video_playlist_id]
		audio_playlist = self.project.playlists[audio_playlist_id]
		video_entries = video_playlist.get('entries', [])
		audio_entries = audio_playlist.get('entries', [])
		if len(video_entries) != len(audio_entries):
			raise RuntimeError("video and audio segment counts do not match")
		segment_files = []
		batch_files = []
		batch_segments = []
		batch_index = 1
		threshold = self.project.output.get('merge_batch_threshold', 0)
		batch_size = self.project.output.get('merge_batch_size', 0)
		use_batch = (
			threshold > 0 and batch_size > 0 and len(video_entries) > threshold
		)
		for index, (video_entry, audio_entry) in enumerate(
			zip(video_entries, audio_entries), start=1
		):
			if video_entry['duration_frames'] != audio_entry['duration_frames']:
				raise RuntimeError("video and audio segment durations do not match")
			video_file = self._render_video_entry(video_entry, index)
			audio_file = self._render_audio_entry(audio_entry, index)
			segment_file = self._make_temp_path(f"segment-{index:03d}.mkv")
			self._mux_segment(video_file, audio_file, segment_file)
			if not self.project.keep_temp:
				self._cleanup_temp([video_file, audio_file])
			if use_batch:
				batch_segments.append(segment_file)
				if len(batch_segments) >= batch_size:
					batch_out = self._make_temp_path(f"concat-{batch_index:03d}.mkv")
					if len(batch_segments) == 1:
						shutil.copy(batch_segments[0], batch_out)
					else:
						self._merge_video_files(batch_segments, batch_out)
					if not self.project.keep_temp:
						self._cleanup_temp(batch_segments)
					batch_files.append(batch_out)
					batch_segments = []
					batch_index += 1
			else:
				segment_files.append(segment_file)
		output_file = self._make_temp_path(f"segment-track-{video_playlist_id}.mkv")
		if use_batch:
			if len(batch_segments) > 0:
				batch_out = self._make_temp_path(f"concat-{batch_index:03d}.mkv")
				if len(batch_segments) == 1:
					shutil.copy(batch_segments[0], batch_out)
				else:
					self._merge_video_files(batch_segments, batch_out)
				if not self.project.keep_temp:
					self._cleanup_temp(batch_segments)
				batch_files.append(batch_out)
			if len(batch_files) == 1:
				shutil.copy(batch_files[0], output_file)
			else:
				self._merge_video_files(batch_files, output_file)
			if not self.project.keep_temp:
				self._cleanup_temp(batch_files)
		else:
			self._concatenate_video(segment_files, output_file)
			if not self.project.keep_temp:
				self._cleanup_temp(segment_files)
		return output_file

	#============================
	def _apply_overlays(self, base_file: str, overlays: list) -> str:
		current_file = base_file
		for index, overlay in enumerate(overlays, start=1):
			overlay_playlist_id = overlay.get('b')
			if overlay_playlist_id is None:
				raise RuntimeError("overlay missing b playlist")
			overlay_file = self._render_overlay_playlist(overlay_playlist_id, index, overlay)
			out_file = self._make_temp_path(f"overlay-{index:02d}.mkv")
			self._composite_overlay(current_file, overlay_file, out_file, overlay)
			if not self.project.keep_temp:
				self._cleanup_temp([current_file, overlay_file])
			current_file = out_file
		return current_file

	#============================
	def _render_overlay_playlist(self, playlist_id: str, overlay_index: int,
		overlay: dict = None) -> str:
		playlist = self.project.playlists.get(playlist_id)
		if playlist is None:
			raise RuntimeError(f"overlay playlist not found: {playlist_id}")
		if playlist.get('kind') != 'video':
			raise RuntimeError("overlay playlists must be video")
		segment_files = []
		batch_files = []
		batch_segments = []
		batch_index = 1
		threshold = self.project.output.get('merge_batch_threshold', 0)
		batch_size = self.project.output.get('merge_batch_size', 0)
		use_batch = (
			threshold > 0 and batch_size > 0 and len(playlist.get('entries', [])) > threshold
		)
		entries = playlist.get('entries', [])
		render_width = None
		render_height = None
		geometry = overlay.get('geometry') if isinstance(overlay, dict) else None
		if isinstance(geometry, list) and len(geometry) >= 4:
			has_source = any(item.get('type') == 'source' for item in entries)
			if not has_source:
				render_width = int(round(self.project.profile['width'] * geometry[2]))
				render_height = int(round(self.project.profile['height'] * geometry[3]))
				if render_width <= 0 or render_height <= 0:
					render_width = None
					render_height = None
		for index, entry in enumerate(entries, start=1):
			video_file = self._render_video_entry(entry, index, codec='ffv1',
				pixel_format='rgba', allow_transparent=True,
				render_width=render_width, render_height=render_height)
			if use_batch:
				batch_segments.append(video_file)
				if len(batch_segments) >= batch_size:
					batch_out = self._make_temp_path(f"concat-{batch_index:03d}.mkv")
					if len(batch_segments) == 1:
						shutil.copy(batch_segments[0], batch_out)
					else:
						self._merge_video_files(batch_segments, batch_out)
					if not self.project.keep_temp:
						self._cleanup_temp(batch_segments)
					batch_files.append(batch_out)
					batch_segments = []
					batch_index += 1
			else:
				segment_files.append(video_file)
		if len(segment_files) == 0 and len(batch_files) == 0 and len(batch_segments) == 0:
			raise RuntimeError("overlay playlist has no entries")
		output_file = self._make_temp_path(f"overlay-track-{overlay_index:02d}.mkv")
		if use_batch:
			if len(batch_segments) > 0:
				batch_out = self._make_temp_path(f"concat-{batch_index:03d}.mkv")
				if len(batch_segments) == 1:
					shutil.copy(batch_segments[0], batch_out)
				else:
					self._merge_video_files(batch_segments, batch_out)
				if not self.project.keep_temp:
					self._cleanup_temp(batch_segments)
				batch_files.append(batch_out)
			if len(batch_files) == 1:
				shutil.copy(batch_files[0], output_file)
			else:
				self._merge_video_files(batch_files, output_file)
			if not self.project.keep_temp:
				self._cleanup_temp(batch_files)
		else:
			self._concatenate_video(segment_files, output_file)
			if not self.project.keep_temp:
				self._cleanup_temp(segment_files)
		return output_file

	#============================
	def _composite_overlay(self, base_file: str, overlay_file: str,
		output_file: str, overlay: dict) -> None:
		width = self.project.profile['width']
		height = self.project.profile['height']
		geometry = overlay.get('geometry', [0.0, 0.0, 1.0, 1.0])
		opacity = overlay.get('opacity', 1.0)
		x = int(round(width * geometry[0]))
		y = int(round(height * geometry[1]))
		w = int(round(width * geometry[2]))
		h = int(round(height * geometry[3]))
		start_time = utils.seconds_from_frames(overlay['in_frames'],
			self.project.profile['fps'])
		end_time = utils.seconds_from_frames(overlay['out_frames'],
			self.project.profile['fps'])
		if w <= 0 or h <= 0:
			raise RuntimeError("overlay geometry results in zero-sized region")
		alpha_value = f"{opacity}"
		filter_chain = (
			f"[1:v]scale={w}:{h},format=rgba,colorchannelmixer=aa={alpha_value}[ovr];"
			f"[0:v][ovr]overlay={x}:{y}:enable='between(t,{start_time:.6f},{end_time:.6f})'"
			"[vout]"
		)
		cmd = "ffmpeg -y "
		cmd += f" -i '{base_file}' -i '{overlay_file}' "
		cmd += f" -filter_complex \"{filter_chain}\" "
		cmd += " -map \"[vout]\" -map 0:a? "
		cmd += self._video_codec_args(self.project.output['video_codec'],
			self.project.output['crf'])
		cmd += f" -pix_fmt {self.project.profile['pixel_format']} "
		cmd += " -codec:a copy "
		cmd += f" '{output_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_video_entry(self, entry: dict, index: int, codec: str = None,
		pixel_format: str = None, allow_transparent: bool = False,
		render_width: int = None, render_height: int = None) -> str:
		fps_value = self.project.profile['fps_float']
		pixel_format = pixel_format or self.project.profile['pixel_format']
		width = render_width or self.project.profile['width']
		height = render_height or self.project.profile['height']
		codec = codec or self.project.output['video_codec']
		crf = self.project.output['crf']
		if entry['type'] == 'source':
			start_seconds = utils.seconds_from_frames(
				entry['in_frame'], self.project.profile['fps']
			)
			out_seconds = utils.seconds_from_frames(
				entry['out_frame'], self.project.profile['fps']
			)
			duration = out_seconds - start_seconds
			speed = float(entry['speed'])
			out_file = self._make_temp_path(f"video-{index:03d}.mkv")
			self._render_video_source(entry['asset_file'], out_file, start_seconds,
				duration, speed, fps_value, codec, crf, pixel_format)
			return out_file
		if entry['type'] == 'blank':
			fill = entry.get('fill', 'black')
			if fill == 'transparent' and not allow_transparent:
				raise RuntimeError("transparent blanks are only supported in overlays")
			duration = utils.seconds_from_frames(
				entry['duration_frames'], self.project.profile['fps']
			)
			out_file = self._make_temp_path(f"video-blank-{index:03d}.mkv")
			self._render_blank_video(out_file, duration, fps_value, width, height,
				codec, crf, pixel_format, fill)
			return out_file
		if entry['type'] == 'generator':
			return self._render_video_generator(entry, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		raise RuntimeError("unsupported video entry type")

	#============================
	def _render_audio_entry(self, entry: dict, index: int) -> str:
		sample_rate = self.project.profile['sample_rate']
		channels = self.project.profile['channels']
		audio_mode = self.project.profile['audio_mode']
		if entry['type'] == 'source':
			start_seconds = utils.seconds_from_frames(
				entry['in_frame'], self.project.profile['fps']
			)
			out_seconds = utils.seconds_from_frames(
				entry['out_frame'], self.project.profile['fps']
			)
			duration = out_seconds - start_seconds
			speed = float(entry['speed'])
			out_file = self._make_temp_path(f"audio-{index:03d}.wav")
			self._render_audio_source(entry['asset_file'], out_file, start_seconds,
				duration, speed, sample_rate, channels, audio_mode,
				entry['normalize'])
			return out_file
		if entry['type'] == 'blank':
			duration = utils.seconds_from_frames(
				entry['duration_frames'], self.project.profile['fps']
			)
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
		cmd += self._video_codec_args(codec, crf)
		cmd += f" -pix_fmt {pixel_format} -r {fps_value:.6f} "
		if abs(speed - 1.0) > 0.0001:
			cmd += f" -filter:v 'setpts={1.0 / speed:.8f}*PTS' "
		cmd += f" '{out_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(out_file)

	#============================
	def _render_blank_video(self, out_file: str, duration: float,
		fps_value: float, width: int, height: int, codec: str, crf: int,
		pixel_format: str, fill: str) -> None:
		if fill == 'transparent':
			card_image = self._make_temp_path("blank-transparent.png")
			image = PIL.Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
			image.save(card_image)
			self._render_still_image(card_image, out_file, duration, codec, crf,
				pixel_format)
			if not self.project.keep_temp:
				self._cleanup_temp([card_image])
			return
		color_value = 'black'
		cmd = "ffmpeg -y -f lavfi "
		cmd += f" -i color=c={color_value}:s={width}x{height}:r={fps_value:.6f} "
		cmd += f" -t {duration:.3f} "
		cmd += self._video_codec_args(codec, crf)
		cmd += f" -pix_fmt {pixel_format} "
		cmd += f" '{out_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(out_file)

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
		utils.runCmd(cmd)
		utils.ensure_file_exists(raw_file)
		current_file = raw_file
		if norm_level is not None:
			norm_file = self._make_temp_path("audio-norm.wav")
			sox.normalizeAudio(current_file, norm_file, level=float(norm_level),
				samplerate=sample_rate, bitrate=16)
			if not self.project.keep_temp:
				os.remove(current_file)
			current_file = norm_file
		if abs(speed - 1.0) > 0.0001:
			speed_file = self._make_temp_path("audio-speed.wav")
			sox.speedUpAudio(current_file, speed_file, speed=speed,
				samplerate=sample_rate, bitrate=16)
			if not self.project.keep_temp:
				os.remove(current_file)
			current_file = speed_file
		if current_file != out_file:
			shutil.move(current_file, out_file)

	#============================
	def _render_video_generator(self, entry: dict, index: int,
		codec: str = None, crf: int = None, pixel_format: str = None,
		render_width: int = None, render_height: int = None) -> str:
		codec = codec or self.project.output['video_codec']
		crf = self.project.output['crf'] if crf is None else crf
		pixel_format = pixel_format or self.project.profile['pixel_format']
		gen_kind = entry['kind']
		if gen_kind in ('chapter_card', 'title_card'):
			return self._render_title_card(entry, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		if gen_kind == 'overlay_text':
			return self._render_overlay_text(entry, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		if gen_kind == 'still':
			return self._render_still_generator(entry, index, codec, crf,
				pixel_format, render_width=render_width,
				render_height=render_height)
		if gen_kind == 'black':
			duration = utils.seconds_from_frames(
				entry['duration_frames'], self.project.profile['fps']
			)
			out_file = self._make_temp_path(f"video-black-{index:03d}.mkv")
			self._render_blank_video(out_file, duration,
				self.project.profile['fps_float'],
				render_width or self.project.profile['width'],
				render_height or self.project.profile['height'],
				codec, crf, pixel_format, 'black')
			return out_file
		raise RuntimeError("unsupported video generator kind")

	#============================
	def _render_audio_generator(self, entry: dict, index: int) -> str:
		gen_kind = entry['kind']
		if gen_kind in ('silence',):
			duration = utils.seconds_from_frames(
				entry['duration_frames'], self.project.profile['fps']
			)
			out_file = self._make_temp_path(f"audio-silence-{index:03d}.wav")
			sox.makeSilence(out_file, seconds=duration,
				samplerate=self.project.profile['sample_rate'], bitrate=16,
				audio_mode=self.project.profile['audio_mode'])
			return out_file
		raise RuntimeError("unsupported audio generator kind")

	#============================
	def _render_title_card(self, entry: dict, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		data = entry.get('data', {})
		text = data.get('title', data.get('text', ''))
		if text == '':
			raise RuntimeError("title_card requires title or text")
		style_id = data.get('style')
		style = None
		if style_id is not None:
			style = self.project.assets.get('cards', {}).get(style_id)
			if style is None:
				raise RuntimeError(f"card style {style_id} not found in assets.cards")
		font_size = self._resolve_card_value(data, style, 'font_size')
		font_file = self._resolve_card_value(data, style, 'font_file')
		text_color = self._resolve_card_value(data, style, 'text_color')
		background = self._resolve_card_background(data, style)
		duration = utils.seconds_from_frames(
			entry['duration_frames'], self.project.profile['fps']
		)
		if background is not None:
			if not isinstance(background, dict):
				raise RuntimeError("card background must be a mapping")
			bg_kind = background.get('kind')
			if bg_kind == 'image':
				return self._render_image_card(text, background, duration, font_file,
					font_size, text_color, index, codec, crf, pixel_format,
					render_width=render_width, render_height=render_height)
			if bg_kind == 'color':
				return self._render_color_card(text, background, duration, font_file,
					font_size, text_color, index, codec, crf, pixel_format,
					render_width=render_width, render_height=render_height)
			if bg_kind == 'gradient':
				return self._render_gradient_card(text, background, duration, font_file,
					font_size, text_color, index, codec, crf, pixel_format,
					render_width=render_width, render_height=render_height)
			if bg_kind == 'transparent':
				return self._render_transparent_card(text, duration, font_file,
					font_size, text_color, index, codec, crf, pixel_format,
					render_width=render_width, render_height=render_height)
			raise RuntimeError(f"unsupported card background kind {bg_kind}")
		if codec == 'ffv1':
			raise RuntimeError("title_card requires a background for overlays")
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		tc = titlecard.TitleCard()
		tc.text = text
		tc.width = render_width or self.project.profile['width']
		tc.height = render_height or self.project.profile['height']
		tc.framerate = self.project.profile['fps_float']
		tc.length = float(duration)
		tc.crf = self.project.output['crf']
		tc.codec = codec
		tc.outfile = out_file
		if font_file is not None:
			tc.fontfile = font_file
		if font_size is not None:
			tc.size = font_size
		if text_color is not None:
			tc.textcolor = self._parse_color(text_color)
		tc.setType()
		tc.createCards()
		utils.ensure_file_exists(out_file)
		return out_file

	#============================
	def _render_overlay_text(self, entry: dict, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		data = entry.get('data', {})
		text = data.get('text', data.get('title', ''))
		if text == '':
			raise RuntimeError("overlay_text requires text or title")
		style_id = data.get('style')
		style = None
		if style_id is not None:
			style = self.project.assets.get('overlay_text_styles', {}).get(style_id)
			if style is None:
				raise RuntimeError(
					f"overlay text style {style_id} not found in assets.overlay_text_styles"
				)
		font_size = self._resolve_card_value(data, style, 'font_size')
		font_file = self._resolve_card_value(data, style, 'font_file')
		text_color = self._resolve_card_value(data, style, 'text_color')
		background = self._resolve_card_background(data, style)
		if background is None:
			background = {'kind': 'transparent'}
		duration = utils.seconds_from_frames(
			entry['duration_frames'], self.project.profile['fps']
		)
		if not isinstance(background, dict):
			raise RuntimeError("overlay text background must be a mapping")
		bg_kind = background.get('kind')
		animate = data.get('animate')
		if animate is not None:
			return self._render_overlay_text_animated(text, background, duration,
				font_file, font_size, text_color, index, codec, crf, pixel_format,
				animate, render_width=render_width, render_height=render_height)
		if bg_kind == 'image':
			return self._render_image_card(text, background, duration, font_file,
				font_size, text_color, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		if bg_kind == 'color':
			return self._render_color_card(text, background, duration, font_file,
				font_size, text_color, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		if bg_kind == 'gradient':
			return self._render_gradient_card(text, background, duration, font_file,
				font_size, text_color, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		if bg_kind == 'transparent':
			return self._render_transparent_card(text, duration, font_file,
				font_size, text_color, index, codec, crf, pixel_format,
				render_width=render_width, render_height=render_height)
		raise RuntimeError(f"unsupported overlay text background kind {bg_kind}")

	#============================
	def _render_overlay_text_animated(self, text: str, background: dict,
		duration: float, font_file: str, font_size, text_color, index: int,
		codec: str, crf: int, pixel_format: str, animate: dict,
		render_width: int = None, render_height: int = None) -> str:
		if not isinstance(animate, dict):
			raise RuntimeError("overlay text animate must be a mapping")
		kind = animate.get('kind', 'cycle')
		if kind != 'cycle':
			raise RuntimeError("overlay text animate kind must be cycle")
		values = animate.get('values')
		if not isinstance(values, list) or len(values) == 0:
			raise RuntimeError("overlay text animate values must be a non-empty list")
		cadence = animate.get('cadence')
		fps_value = animate.get('fps')
		if cadence is not None:
			cadence_value = float(cadence)
			if cadence_value <= 0:
				raise RuntimeError("overlay text animate cadence must be positive")
			fps_value = 1.0 / cadence_value
		if fps_value is None:
			fps_value = 2.0
		fps_value = float(fps_value)
		if fps_value <= 0:
			raise RuntimeError("overlay text animate fps must be positive")
		frame_texts = []
		for value in values:
			value_text = str(value)
			if "{animate}" in text:
				frame_texts.append(text.replace("{animate}", value_text))
			else:
				space = "" if text.endswith(" ") or text == "" else " "
				frame_texts.append(f"{text}{space}{value_text}".strip())
		frame_prefix = self._make_temp_path(f"overlay-anim-{index:03d}")
		frame_files = []
		bg_kind = background.get('kind')
		for frame_index, frame_text in enumerate(frame_texts, start=1):
			frame_file = f"{frame_prefix}-{frame_index:03d}.png"
			if bg_kind == 'image':
				asset_id = background.get('asset')
				if asset_id is None:
					raise RuntimeError("background image requires asset id")
				image_asset = self.project.assets.get('image', {}).get(asset_id)
				if image_asset is None:
					raise RuntimeError(f"image asset {asset_id} not found in assets.image")
				image_file = image_asset.get('file')
				if image_file is None:
					raise RuntimeError(f"image asset {asset_id} missing file")
				utils.ensure_file_exists(image_file)
				self._render_card_image(frame_text, image_file, frame_file,
					font_file, font_size, text_color,
					render_width=render_width, render_height=render_height)
			elif bg_kind == 'color':
				color_value = background.get('color', '#000000')
				self._render_color_card_image(frame_text, color_value, frame_file,
					font_file, font_size, text_color, render_width=render_width,
					render_height=render_height)
			elif bg_kind == 'gradient':
				from_color = background.get('from', '#000000')
				to_color = background.get('to', '#ffffff')
				direction = background.get('direction', 'vertical')
				self._render_gradient_card_image(frame_text, from_color, to_color,
					direction, frame_file, font_file, font_size, text_color,
					render_width=render_width, render_height=render_height)
			elif bg_kind == 'transparent':
				self._render_transparent_card_image(frame_text, frame_file,
					font_file, font_size, text_color, render_width=render_width,
					render_height=render_height)
			else:
				raise RuntimeError(f"unsupported overlay text background kind {bg_kind}")
			frame_files.append(frame_file)
		loop_duration = float(len(frame_texts)) / fps_value
		loop_file = self._make_temp_path(f"overlay-anim-loop-{index:03d}.mkv")
		cmd = "ffmpeg -y "
		cmd += f" -r {fps_value:.6f} "
		cmd += f" -i '{frame_prefix}-%03d.png' "
		cmd += f" -t {loop_duration:.3f} "
		cmd += self._video_codec_args(codec, crf)
		cmd += f" -pix_fmt {pixel_format} "
		cmd += f" '{loop_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(loop_file)
		out_file = self._make_temp_path(f"overlay-text-{index:03d}.mkv")
		cmd = "ffmpeg -y -stream_loop -1 "
		cmd += f" -i '{loop_file}' "
		cmd += f" -t {float(duration):.3f} "
		cmd += f" -r {fps_value:.6f} "
		cmd += self._video_codec_args(codec, crf)
		cmd += f" -pix_fmt {pixel_format} "
		cmd += f" '{out_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(out_file)
		if not self.project.keep_temp:
			self._cleanup_temp(frame_files + [loop_file])
		return out_file

	#============================
	def _resolve_card_value(self, data: dict, style: dict, key: str):
		if isinstance(data, dict) and data.get(key) is not None:
			return data.get(key)
		if isinstance(style, dict) and style.get(key) is not None:
			return style.get(key)
		return None

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
	def _render_image_card(self, text: str, background: dict, duration: float,
		font_file: str, font_size, text_color, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		asset_id = background.get('asset')
		if asset_id is None:
			raise RuntimeError("background image requires asset id")
		image_asset = self.project.assets.get('image', {}).get(asset_id)
		if image_asset is None:
			raise RuntimeError(f"image asset {asset_id} not found in assets.image")
		image_file = image_asset.get('file')
		if image_file is None:
			raise RuntimeError(f"image asset {asset_id} missing file")
		utils.ensure_file_exists(image_file)
		card_image = self._make_temp_path(f"card-{index:03d}.png")
		self._render_card_image(text, image_file, card_image, font_file,
			font_size, text_color, render_width=render_width,
			render_height=render_height)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration, codec, crf,
			pixel_format)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_color_card(self, text: str, background: dict, duration: float,
		font_file: str, font_size, text_color, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		color_value = background.get('color', '#000000')
		card_image = self._make_temp_path(f"card-{index:03d}.png")
		self._render_color_card_image(text, color_value, card_image, font_file,
			font_size, text_color, render_width=render_width,
			render_height=render_height)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration, codec, crf,
			pixel_format)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_gradient_card(self, text: str, background: dict, duration: float,
		font_file: str, font_size, text_color, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		from_color = background.get('from', '#000000')
		to_color = background.get('to', '#ffffff')
		direction = background.get('direction', 'vertical')
		card_image = self._make_temp_path(f"card-{index:03d}.png")
		self._render_gradient_card_image(text, from_color, to_color, direction,
			card_image, font_file, font_size, text_color,
			render_width=render_width, render_height=render_height)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration, codec, crf,
			pixel_format)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_transparent_card(self, text: str, duration: float,
		font_file: str, font_size, text_color, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		card_image = self._make_temp_path(f"card-{index:03d}.png")
		self._render_transparent_card_image(text, card_image, font_file,
			font_size, text_color, render_width=render_width,
			render_height=render_height)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration, codec, crf,
			pixel_format)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_transparent_card_image(self, text: str, output_file: str,
		font_file: str, font_size, text_color, render_width: int = None,
		render_height: int = None) -> None:
		width = render_width or self.project.profile['width']
		height = render_height or self.project.profile['height']
		image = PIL.Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
		draw = PIL.ImageDraw.Draw(image)
		font = self._load_font(font_file, font_size)
		color = self._parse_color(text_color or "#ffffff")
		color_rgba = (color[0], color[1], color[2], 255)
		text_size = self._measure_text(draw, text, font)
		x = (width - text_size[0]) / 2.0
		y = (height - text_size[1]) / 2.0
		draw.multiline_text((x, y), text, font=font, fill=color_rgba,
			align="center")
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_card_image(self, text: str, background_file: str,
		output_file: str, font_file: str, font_size, text_color,
		render_width: int = None, render_height: int = None) -> None:
		width = render_width or self.project.profile['width']
		height = render_height or self.project.profile['height']
		image = PIL.Image.open(background_file).convert("RGB")
		image = self._fit_image(image, width, height)
		self._draw_card_text(image, text, font_file, font_size, text_color)
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_still_generator(self, entry: dict, index: int, codec: str = None,
		crf: int = None, pixel_format: str = None, render_width: int = None,
		render_height: int = None) -> str:
		data = entry.get('data', {})
		asset_id = data.get('asset')
		if asset_id is None:
			raise RuntimeError("still generator requires asset")
		image_asset = self.project.assets.get('image', {}).get(asset_id)
		if image_asset is None:
			raise RuntimeError(f"image asset {asset_id} not found in assets.image")
		image_file = image_asset.get('file')
		if image_file is None:
			raise RuntimeError(f"image asset {asset_id} missing file")
		utils.ensure_file_exists(image_file)
		duration = utils.seconds_from_frames(
			entry['duration_frames'], self.project.profile['fps']
		)
		card_image = self._make_temp_path(f"still-{index:03d}.png")
		self._render_still_image_asset(image_file, card_image, pixel_format,
			render_width=render_width, render_height=render_height)
		out_file = self._make_temp_path(f"still-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration, codec, crf,
			pixel_format)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_still_image_asset(self, image_file: str, output_file: str,
		pixel_format: str, render_width: int = None, render_height: int = None) -> None:
		width = render_width or self.project.profile['width']
		height = render_height or self.project.profile['height']
		image = PIL.Image.open(image_file)
		if pixel_format in ('rgba', 'argb', 'yuva420p', 'yuva444p'):
			image = image.convert("RGBA")
		else:
			image = image.convert("RGB")
		image = self._fit_image(image, width, height)
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_color_card_image(self, text: str, color_value,
		output_file: str, font_file: str, font_size, text_color,
		render_width: int = None, render_height: int = None) -> None:
		width = render_width or self.project.profile['width']
		height = render_height or self.project.profile['height']
		color = self._parse_color(color_value)
		image = PIL.Image.new("RGB", (width, height), color=color)
		self._draw_card_text(image, text, font_file, font_size, text_color)
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_gradient_card_image(self, text: str, from_color, to_color,
		direction: str, output_file: str, font_file: str, font_size,
		text_color, render_width: int = None, render_height: int = None) -> None:
		width = render_width or self.project.profile['width']
		height = render_height or self.project.profile['height']
		image = self._render_gradient_background(from_color, to_color, direction,
			width, height)
		self._draw_card_text(image, text, font_file, font_size, text_color)
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _draw_card_text(self, image, text: str, font_file: str, font_size,
		text_color) -> None:
		width, height = image.size
		draw = PIL.ImageDraw.Draw(image)
		font = self._load_font(font_file, font_size)
		color = self._parse_color(text_color or "#ffffff")
		if hasattr(draw, "multiline_textbbox"):
			bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
			text_w = bbox[2] - bbox[0]
			text_h = bbox[3] - bbox[1]
			x = (width - text_w) / 2.0 - bbox[0]
			y = (height - text_h) / 2.0 - bbox[1]
		else:
			text_size = self._measure_text(draw, text, font)
			x = (width - text_size[0]) / 2.0
			y = (height - text_size[1]) / 2.0
		draw.multiline_text((x, y), text, font=font, fill=color, align="center")

	#============================
	def _fit_image(self, image, width: int, height: int):
		src_w, src_h = image.size
		if src_w <= 0 or src_h <= 0:
			raise RuntimeError("invalid background image size")
		scale = max(width / src_w, height / src_h)
		new_size = (int(round(src_w * scale)), int(round(src_h * scale)))
		image = image.resize(new_size, resample=PIL.Image.LANCZOS)
		left = max(0, int(round((new_size[0] - width) / 2.0)))
		top = max(0, int(round((new_size[1] - height) / 2.0)))
		right = left + width
		bottom = top + height
		return image.crop((left, top, right, bottom))

	#============================
	def _load_font(self, font_file: str, font_size):
		size = int(font_size) if font_size is not None else 96
		if font_file is not None:
			if os.path.exists(font_file):
				return PIL.ImageFont.truetype(font_file, size)
			raise RuntimeError(f"font file not found: {font_file}")
		try:
			return PIL.ImageFont.truetype("DejaVuSans.ttf", size)
		except OSError:
			return PIL.ImageFont.load_default()

	#============================
	def _measure_text(self, draw, text: str, font) -> tuple:
		if hasattr(draw, "multiline_textbbox"):
			bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
			return (bbox[2] - bbox[0], bbox[3] - bbox[1])
		size = draw.multiline_textsize(text, font=font)
		return size

	#============================
	def _parse_color(self, value):
		if value is None:
			return (255, 255, 255)
		if isinstance(value, (list, tuple)) and len(value) == 3:
			return tuple(int(channel) for channel in value)
		if isinstance(value, str):
			return PIL.ImageColor.getrgb(value)
		raise RuntimeError("invalid color value for card text")

	#============================
	def _render_gradient_background(self, from_color, to_color, direction: str,
		width: int, height: int):
		color_start = self._parse_color(from_color)
		color_end = self._parse_color(to_color)
		image = PIL.Image.new("RGB", (width, height))
		draw = PIL.ImageDraw.Draw(image)
		if direction not in ('vertical', 'horizontal'):
			raise RuntimeError("gradient direction must be vertical or horizontal")
		if direction == 'vertical':
			steps = max(height - 1, 1)
			for y in range(height):
				ratio = y / steps
				color = self._blend_color(color_start, color_end, ratio)
				draw.line([(0, y), (width, y)], fill=color)
		else:
			steps = max(width - 1, 1)
			for x in range(width):
				ratio = x / steps
				color = self._blend_color(color_start, color_end, ratio)
				draw.line([(x, 0), (x, height)], fill=color)
		return image

	#============================
	def _blend_color(self, color_start: tuple, color_end: tuple, ratio: float) -> tuple:
		return tuple(
			int(round(start + (end - start) * ratio))
			for start, end in zip(color_start, color_end)
		)

	#============================
	def _render_still_image(self, image_file: str, out_file: str,
		duration: float, codec: str = None, crf: int = None,
		pixel_format: str = None) -> None:
		fps_value = self.project.profile['fps_float']
		pixel_format = pixel_format or self.project.profile['pixel_format']
		codec = codec or self.project.output['video_codec']
		crf = self.project.output['crf'] if crf is None else crf
		cmd = "ffmpeg -y -loop 1 "
		cmd += f" -i '{image_file}' -t {duration:.3f} "
		cmd += f" -r {fps_value:.6f} "
		cmd += self._video_codec_args(codec, crf)
		cmd += f" -pix_fmt {pixel_format} "
		cmd += f" '{out_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(out_file)

	#============================
	def _video_codec_args(self, codec: str, crf: int) -> str:
		if codec == 'ffv1':
			return f" -codec:v {codec} "
		return f" -codec:v {codec} -crf {crf} -preset ultrafast "

	#============================
	def _concatenate_video(self, segment_files: list, output_file: str) -> None:
		if len(segment_files) == 0:
			raise RuntimeError("no video segments to concatenate")
		if len(segment_files) == 1:
			shutil.copy(segment_files[0], output_file)
			return
		self._merge_video_files(segment_files, output_file)
		return

	#============================
	def _merge_video_files(self, segment_files: list, output_file: str) -> None:
		cmd = "mkvmerge "
		for segment in segment_files:
			cmd += f" {segment} + "
		cmd = cmd[:-2]
		cmd += f" -o {output_file} "
		self._run_mkvmerge(cmd, output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _mux_segment(self, video_file: str, audio_file: str, output_file: str) -> None:
		cmd = f"mkvmerge -A -S {video_file} -D -S {audio_file} -o {output_file}"
		self._run_mkvmerge(cmd, output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _finalize_output(self, segment_track: str, output_file: str,
		chapters: list) -> None:
		audio_codec = self.project.output.get('audio_codec', 'pcm_s16le')
		if audio_codec in ('pcm_s16le', 'wav', 'pcm', 'copy'):
			if segment_track != output_file:
				shutil.move(segment_track, output_file)
			utils.ensure_file_exists(output_file)
			if len(chapters) > 0:
				self._apply_chapters(output_file, chapters)
			if not utils.is_quiet_mode():
				print(f"mpv {output_file}")
			return
		encoded_file = self._make_temp_path("output-encoded.mkv")
		cmd = "ffmpeg -y "
		cmd += f" -i '{segment_track}' "
		cmd += " -codec:v copy "
		cmd += f" -codec:a {audio_codec} "
		cmd += f" -ar {self.project.profile['sample_rate']} "
		cmd += f" -ac {self.project.profile['channels']} "
		cmd += f" '{encoded_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(encoded_file)
		shutil.move(encoded_file, output_file)
		utils.ensure_file_exists(output_file)
		if len(chapters) > 0:
			self._apply_chapters(output_file, chapters)
		if not utils.is_quiet_mode():
			print(f"mpv {output_file}")
		if not self.project.keep_temp and segment_track != output_file:
			os.remove(segment_track)

	#============================
	def _cleanup_temp(self, temp_files: list) -> None:
		for filepath in temp_files:
			if filepath and os.path.exists(filepath):
				os.remove(filepath)

	#============================
	def _run_mkvmerge(self, cmd: str, output_file: str) -> None:
		try:
			utils.runCmd(cmd)
		except RuntimeError as exc:
			message = str(exc)
			if "mkvmerge" not in message:
				raise
			stderr_text = ""
			if "stderr:" in message:
				stderr_text = message.split("stderr:", 1)[1].strip()
			for line in stderr_text.splitlines():
				line = line.strip()
				if line.lower().startswith("error"):
					raise
			if output_file and os.path.exists(output_file):
				return
			raise

	#============================
	def _make_temp_path(self, filename: str) -> str:
		self.project.temp_counter += 1
		tag = f"{utils.make_timestamp()}-{self.project.temp_counter:04d}"
		return os.path.join(self.project.cache_dir, f"{tag}-{filename}")

	#============================

	def _collect_chapters(self) -> list:
		timeline = self.project.timeline or {}
		segments = timeline.get('segments', [])
		if not isinstance(segments, list) or len(segments) == 0:
			return []
		chapters = []
		current_frames = 0
		for segment in segments:
			if not isinstance(segment, dict) or len(segment.keys()) != 1:
				raise RuntimeError("timeline.segments entries must have one key")
			entry_type = list(segment.keys())[0]
			entry_data = segment.get(entry_type)
			if isinstance(entry_data, dict) and entry_data.get('enabled') is False:
				continue
			if isinstance(entry_data, dict):
				title = entry_data.get('title')
				chapter_flag = entry_data.get('chapter')
				if title and chapter_flag is not False:
					chapters.append({
						'start_frames': current_frames,
						'title': title,
					})
			duration_frames = self._calculate_segment_output_frames(entry_type,
				entry_data)
			current_frames += duration_frames
		return chapters

	#============================
	def _calculate_segment_output_frames(self, entry_type: str,
		entry_data: dict) -> int:
		fps = self.project.profile['fps']
		if entry_type == 'source':
			if not isinstance(entry_data, dict):
				raise RuntimeError("source segment must be a mapping")
			in_time = utils.parse_timecode(entry_data.get('in'))
			out_time = utils.parse_timecode(entry_data.get('out'))
			in_frame = utils.frames_from_seconds(in_time, fps)
			out_frame = utils.frames_from_seconds(out_time, fps)
			if out_frame <= in_frame:
				raise RuntimeError("source entry requires in < out")
			source_frames = out_frame - in_frame
			speed_value = None
			if entry_data.get('video') is not None:
				speed_value = entry_data['video'].get('speed')
			if speed_value is None and entry_data.get('audio') is not None:
				speed_value = entry_data['audio'].get('speed')
			speed = utils.parse_speed(speed_value, self.project.defaults['speed'])
			if speed <= 0:
				raise RuntimeError("speed must be positive")
			speed_fraction = utils.decimal_to_fraction(speed)
			if speed_fraction == 0:
				raise RuntimeError("speed must be non-zero")
			output_frames = utils.round_half_up_fraction(
				Fraction(source_frames, 1) / speed_fraction
			)
			if output_frames <= 0:
				raise RuntimeError("source entry duration is zero after speed change")
			return output_frames
		if entry_type == 'blank' or entry_type == 'generator':
			if not isinstance(entry_data, dict):
				raise RuntimeError("segment entry must be a mapping")
			duration = utils.parse_timecode(entry_data.get('duration'))
			duration_frames = utils.frames_from_seconds(duration, fps)
			if duration_frames <= 0:
				raise RuntimeError("segment duration must be positive")
			return duration_frames
		raise RuntimeError(f"unsupported segment type {entry_type}")

	#============================
	def _apply_chapters(self, output_file: str, chapters: list) -> None:
		if not self._output_supports_chapters(output_file):
			return
		if len(chapters) == 0:
			return
		chapter_file = self._make_temp_path("chapters.txt")
		self._write_chapters_file(chapter_file, chapters)
		temp_output = self._make_temp_path("output-chapters.mkv")
		cmd = "mkvmerge "
		cmd += f" -o '{temp_output}' --chapters '{chapter_file}' "
		cmd += f" '{output_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(temp_output)
		shutil.move(temp_output, output_file)
		if not self.project.keep_temp:
			self._cleanup_temp([chapter_file])

	#============================
	def _output_supports_chapters(self, output_file: str) -> bool:
		ext = os.path.splitext(output_file)[1].lower()
		return ext in ('.mkv', '.mka', '.mk3d', '.mks')

	#============================
	def _write_chapters_file(self, chapter_file: str, chapters: list) -> None:
		lines = []
		for index, chapter in enumerate(chapters, start=1):
			num = f"{index:02d}"
			start_seconds = utils.seconds_from_frames(
				chapter['start_frames'], self.project.profile['fps']
			)
			lines.append(f"CHAPTER{num}={self._format_chapter_time(start_seconds)}")
			title = str(chapter['title']).replace("\n", " ").strip()
			lines.append(f"CHAPTER{num}NAME={title}")
		lines.append("")
		with open(chapter_file, 'w', encoding='utf-8') as handle:
			handle.write("\n".join(lines))

	#============================
	def _format_chapter_time(self, seconds: float) -> str:
		value = decimal.Decimal(str(seconds)) * decimal.Decimal("1000")
		millis = int(value.quantize(decimal.Decimal("1"),
			rounding=decimal.ROUND_HALF_UP))
		if millis < 0:
			millis = 0
		hours = millis // 3600000
		remainder = millis % 3600000
		minutes = remainder // 60000
		remainder = remainder % 60000
		seconds_part = remainder // 1000
		millis_part = remainder % 1000
		return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}.{millis_part:03d}"

	#============================
