#!/usr/bin/env python3

import os
import shutil
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
		segment_track = self._render_segment_playlist(
			self.project.stack['base_video'],
			self.project.stack['main_audio']
		)
		self._finalize_output(segment_track, self.project.output['file'])
		if not self.project.keep_temp:
			self._cleanup_temp([segment_track])

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
			segment_files.append(segment_file)
		output_file = self._make_temp_path(f"segment-track-{video_playlist_id}.mkv")
		self._concatenate_video(segment_files, output_file)
		if not self.project.keep_temp:
			self._cleanup_temp(segment_files)
		return output_file

	#============================
	def _render_video_entry(self, entry: dict, index: int) -> str:
		fps_value = self.project.profile['fps_float']
		pixel_format = self.project.profile['pixel_format']
		width = self.project.profile['width']
		height = self.project.profile['height']
		codec = self.project.output['video_codec']
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
			duration = utils.seconds_from_frames(
				entry['duration_frames'], self.project.profile['fps']
			)
			out_file = self._make_temp_path(f"video-blank-{index:03d}.mkv")
			self._render_black_video(out_file, duration, fps_value, width, height,
				codec, crf, pixel_format)
			return out_file
		if entry['type'] == 'generator':
			return self._render_video_generator(entry, index)
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
		cmd += f" -codec:v {codec} -crf {crf} -preset ultrafast "
		cmd += f" -pix_fmt {pixel_format} -r {fps_value:.6f} "
		if abs(speed - 1.0) > 0.0001:
			cmd += f" -filter:v 'setpts={1.0 / speed:.8f}*PTS' "
		cmd += f" '{out_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(out_file)

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
	def _render_video_generator(self, entry: dict, index: int) -> str:
		gen_kind = entry['kind']
		if gen_kind in ('chapter_card', 'title_card'):
			return self._render_title_card(entry, index)
		if gen_kind == 'black':
			duration = utils.seconds_from_frames(
				entry['duration_frames'], self.project.profile['fps']
			)
			out_file = self._make_temp_path(f"video-black-{index:03d}.mkv")
			self._render_black_video(out_file, duration,
				self.project.profile['fps_float'],
				self.project.profile['width'], self.project.profile['height'],
				self.project.output['video_codec'], self.project.output['crf'],
				self.project.profile['pixel_format'])
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
	def _render_title_card(self, entry: dict, index: int) -> str:
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
					font_size, text_color, index)
			if bg_kind == 'color':
				return self._render_color_card(text, background, duration, font_file,
					font_size, text_color, index)
			if bg_kind == 'gradient':
				return self._render_gradient_card(text, background, duration, font_file,
					font_size, text_color, index)
			raise RuntimeError(f"unsupported card background kind {bg_kind}")
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		tc = titlecard.TitleCard()
		tc.text = text
		tc.width = self.project.profile['width']
		tc.height = self.project.profile['height']
		tc.framerate = self.project.profile['fps_float']
		tc.length = float(duration)
		tc.crf = self.project.output['crf']
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
		font_file: str, font_size, text_color, index: int) -> str:
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
			font_size, text_color)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_color_card(self, text: str, background: dict, duration: float,
		font_file: str, font_size, text_color, index: int) -> str:
		color_value = background.get('color', '#000000')
		card_image = self._make_temp_path(f"card-{index:03d}.png")
		self._render_color_card_image(text, color_value, card_image, font_file,
			font_size, text_color)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_gradient_card(self, text: str, background: dict, duration: float,
		font_file: str, font_size, text_color, index: int) -> str:
		from_color = background.get('from', '#000000')
		to_color = background.get('to', '#ffffff')
		direction = background.get('direction', 'vertical')
		card_image = self._make_temp_path(f"card-{index:03d}.png")
		self._render_gradient_card_image(text, from_color, to_color, direction,
			card_image, font_file, font_size, text_color)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		self._render_still_image(card_image, out_file, duration)
		if not self.project.keep_temp:
			self._cleanup_temp([card_image])
		return out_file

	#============================
	def _render_card_image(self, text: str, background_file: str,
		output_file: str, font_file: str, font_size, text_color) -> None:
		width = self.project.profile['width']
		height = self.project.profile['height']
		image = PIL.Image.open(background_file).convert("RGB")
		image = self._fit_image(image, width, height)
		self._draw_card_text(image, text, font_file, font_size, text_color)
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_color_card_image(self, text: str, color_value,
		output_file: str, font_file: str, font_size, text_color) -> None:
		width = self.project.profile['width']
		height = self.project.profile['height']
		color = self._parse_color(color_value)
		image = PIL.Image.new("RGB", (width, height), color=color)
		self._draw_card_text(image, text, font_file, font_size, text_color)
		image.save(output_file)
		utils.ensure_file_exists(output_file)

	#============================
	def _render_gradient_card_image(self, text: str, from_color, to_color,
		direction: str, output_file: str, font_file: str, font_size,
		text_color) -> None:
		width = self.project.profile['width']
		height = self.project.profile['height']
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
		if font_file is not None and os.path.exists(font_file):
			return PIL.ImageFont.truetype(font_file, size)
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
		duration: float) -> None:
		fps_value = self.project.profile['fps_float']
		pixel_format = self.project.profile['pixel_format']
		codec = self.project.output['video_codec']
		crf = self.project.output['crf']
		cmd = "ffmpeg -y -loop 1 "
		cmd += f" -i '{image_file}' -t {duration:.3f} "
		cmd += f" -r {fps_value:.6f} "
		cmd += f" -codec:v {codec} -crf {crf} -preset ultrafast "
		cmd += f" -pix_fmt {pixel_format} "
		cmd += f" '{out_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(out_file)

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
		utils.runCmd(cmd)
		utils.ensure_file_exists(output_file)

	#============================
	def _mux_segment(self, video_file: str, audio_file: str, output_file: str) -> None:
		cmd = f"mkvmerge -A -S {video_file} -D -S {audio_file} -o {output_file}"
		utils.runCmd(cmd)
		utils.ensure_file_exists(output_file)

	#============================
	def _finalize_output(self, segment_track: str, output_file: str) -> None:
		audio_codec = self.project.output.get('audio_codec', 'pcm_s16le')
		if audio_codec in ('pcm_s16le', 'wav', 'pcm', 'copy'):
			if segment_track != output_file:
				shutil.move(segment_track, output_file)
			utils.ensure_file_exists(output_file)
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
		print(f"mpv {output_file}")
		if not self.project.keep_temp and segment_track != output_file:
			os.remove(segment_track)

	#============================
	def _cleanup_temp(self, temp_files: list) -> None:
		for filepath in temp_files:
			if filepath and os.path.exists(filepath):
				os.remove(filepath)

	#============================
	def _make_temp_path(self, filename: str) -> str:
		self.project.temp_counter += 1
		tag = f"{utils.make_timestamp()}-{self.project.temp_counter:04d}"
		return os.path.join(self.project.cache_dir, f"{tag}-{filename}")

	#============================
