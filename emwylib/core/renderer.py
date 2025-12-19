#!/usr/bin/env python3

import os
import shutil
from emwylib.core import utils
from emwylib.media import sox
from emwylib import titlecard

#============================================

class Renderer():
	def __init__(self, project):
		self.project = project

	#============================
	def render(self) -> None:
		video_track = self._render_video_playlist(self.project.stack['base_video'])
		audio_track = self._render_audio_playlist(self.project.stack['main_audio'])
		self._mux_output(video_track, audio_track, self.project.output['file'])
		if not self.project.keep_temp:
			self._cleanup_temp([video_track, audio_track])

	#============================
	def _render_video_playlist(self, playlist_id: str) -> str:
		playlist = self.project.playlists[playlist_id]
		segment_files = []
		for index, entry in enumerate(playlist['entries'], start=1):
			segment_file = self._render_video_entry(entry, index)
			segment_files.append(segment_file)
		output_file = self._make_temp_path(f"video-track-{playlist_id}.mkv")
		self._concatenate_video(segment_files, output_file)
		if not self.project.keep_temp:
			self._cleanup_temp(segment_files)
		return output_file

	#============================
	def _render_audio_playlist(self, playlist_id: str) -> str:
		playlist = self.project.playlists[playlist_id]
		segment_files = []
		for index, entry in enumerate(playlist['entries'], start=1):
			segment_file = self._render_audio_entry(entry, index)
			segment_files.append(segment_file)
		output_file = self._make_temp_path(f"audio-track-{playlist_id}.wav")
		self._concatenate_audio(segment_files, output_file)
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
		font_size = None
		if style_id is not None:
			style = self.project.assets.get('cards', {}).get(style_id)
			if isinstance(style, dict) and style.get('font_size') is not None:
				font_size = int(style.get('font_size'))
		if data.get('font_size') is not None:
			font_size = int(data.get('font_size'))
		duration = utils.seconds_from_frames(
			entry['duration_frames'], self.project.profile['fps']
		)
		out_file = self._make_temp_path(f"titlecard-{index:03d}.mkv")
		tc = titlecard.TitleCard()
		tc.text = text
		tc.width = self.project.profile['width']
		tc.height = self.project.profile['height']
		tc.framerate = self.project.profile['fps_float']
		tc.length = float(duration)
		tc.crf = self.project.output['crf']
		tc.outfile = out_file
		if font_size is not None:
			tc.size = font_size
		tc.setType()
		tc.createCards()
		utils.ensure_file_exists(out_file)
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
		utils.runCmd(cmd)
		utils.ensure_file_exists(output_file)

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
		utils.runCmd(cmd)
		utils.ensure_file_exists(output_file)

	#============================
	def _mux_output(self, video_file: str, audio_file: str, output_file: str) -> None:
		encoded_audio = self._encode_audio_if_needed(audio_file)
		cmd = f"mkvmerge -A -S {video_file} -D -S {encoded_audio} -o {output_file}"
		utils.runCmd(cmd)
		utils.ensure_file_exists(output_file)
		print(f"mpv {output_file}")
		if not self.project.keep_temp and encoded_audio != audio_file:
			os.remove(encoded_audio)

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
	def _encode_audio_if_needed(self, audio_file: str) -> str:
		audio_codec = self.project.output.get('audio_codec', 'pcm_s16le')
		if audio_codec in ('pcm_s16le', 'wav', 'pcm'):
			return audio_file
		if audio_codec == 'copy':
			return audio_file
		encoded_file = self._make_temp_path("audio-encoded.mka")
		cmd = "ffmpeg -y "
		cmd += f" -i '{audio_file}' "
		cmd += f" -acodec {audio_codec} "
		cmd += f" -ar {self.project.profile['sample_rate']} -ac {self.project.profile['channels']} "
		cmd += " -f matroska "
		cmd += f" '{encoded_file}' "
		utils.runCmd(cmd)
		utils.ensure_file_exists(encoded_file)
		return encoded_file
