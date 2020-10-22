#!/usr/bin/env python

import re
import os
import sys
import time
import yaml
import json
import shutil
import pprint
import argparse
import subprocess
from emwylib import soxlib
from emwylib import medialib
from emwylib import ffmpeglib
from emwylib import titlecard

### TODO
# add background music
# add mute
# add video transitions
# add audio fade in and out
# add fast forward symbol to screen
# add watermark to video
# allow title cards without audio
# flag to perform av sync
# flag to extract audio at the end, for Audacity editing
# create a show notes
# add more quality levels

debug = True
skipcodes = {'noise': True, 'stop': True, 'skip': True, }
#quality = 'fast'

#===============================
def runCmd(cmd, msg=False):
	showcmd = cmd.strip()
	showcmd = re.sub("  *", " ", showcmd)
	if debug is True:
		print(("CMD: '%s'"%(showcmd)))
	if msg is True:
		proc = subprocess.Popen(showcmd, shell=True)
	else:
		proc = subprocess.Popen(showcmd, shell=True,
			stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	proc.communicate()
	return

#===============================
def common_elements(list1, list2):
	try:
		return list(set(list1).intersection(list2))
	except TypeError:
		list1a = []
		for item in list1:
			if not isinstance(item, dict):
				list1a.append(item)
		return list(set(list1a).intersection(list2))
	sys.exit(1)

#===============================
#===============================
#===============================
class EditControl():
	def __init__(self, yaml_file):
		self.debug = debug
		self.yaml_file = yaml_file
		self.movie_tree = []
		self.titlecard_tree = []
		self.readYamlFile()
		return

	#===============================
	def readYamlFile(self):
		f = open(self.yaml_file, 'r')
		datalist = yaml.load(f)
		#print datalist
		for item in datalist:
			if not isinstance(item, dict):
				print(item)
				print("Hmm, not sure what that was... expecting a dictionary")
				sys.exit(1)
			if item.get('type') == 'global':
				self.global_dict = item
				continue
			elif item.get('type') == 'movie':
				self.movie_tree.append(item)
				continue
			elif item.get('type') == 'titlecard':
				self.titlecard_tree.append(item)
				continue
			else:
				print(item)
				print("Unknown type")
				sys.exit(1)

	#===============================
	def concatenateMovies(self, movlist, bigmovie):
		if len(movlist) == 0:
			print("no movies to merge")
			sys.exit(1)
		if len(movlist) == 1:
			print("only one movie, just rename")
			shutil.copy(movlist[0], bigmovie)
			return bigmovie
		cmd = "mkvmerge "
		for movfile in movlist:
			duration = medialib.getDuration(movfile)
			print(("%.1f  %s"%(duration, movfile)))
			cmd += " %s + "%(movfile)
		cmd = cmd[:-2]
		cmd += " -o %s "%(bigmovie)
		runCmd(cmd)
		if not os.path.isfile(bigmovie):
			print("concatenate movies failed")
			sys.exit(1)
		return bigmovie

	#===============================
	def processAllMovies(self):
		processed_movies = []

		for mov_dict in self.movie_tree:
			movproc = ProcessMovie(mov_dict, self)
			movie_file = movproc.getFinalMovieFile()
			processed_movies.append(movie_file)

		#merge movies...
		self.output_file = self.global_dict.get('output_file', 'complete.mkv')
		self.concatenateMovies(processed_movies, self.output_file)
		for movfile in processed_movies:
			os.remove(movfile)
		print(("mpv %s"%(self.output_file)))

#===============================
#===============================
#===============================
class ProcessMovie():
	#===============================
	def __init__(self, mov_dict, editor):
		self.debug = debug
		self.editor = editor
		self.global_dict = editor.global_dict
		self.mov_dict = mov_dict

		self.movieSettings()
		self.processMovie()

	#===============================
	def movieSettings(self):
		type_map = { 'quality': str, 'samplerate': int, 'bitrate': int,
			'crf': int, 'movframerate': int, 'extra_audio_process': bool,
			'lame_preset': str, 'norm_level': float, 'highpass': int,
			'lowpass': int, 'audio_format': str, 'audio_mode': str,
		}
		self.quality = self.global_dict.get('quality', 'fast')
		self.norm_level = -9.0
		self.highpass = 10
		self.lowpass = 19000
		self.audio_format = 'WAV'
		self.audio_mode = 'mono'
		if self.quality == 'fast':
			self.samplerate = 48000
			self.bitrate = 16
			self.crf = 26
			self.movframerate = 24
			self.extra_audio_process = False
			self.lame_preset = 'medium'
			self.reverse_compress = True
		elif self.quality == 'high':
			self.samplerate = 96000
			self.bitrate = 24
			self.crf = 16
			self.movframerate = 30
			self.extra_audio_process = True
			self.lame_preset = 'standard'
			self.reverse_compress = True
		for category in ('audio', 'video'):
			if self.global_dict.get(category) is not None:
				for key in list(self.global_dict[category].keys()):
					if type_map[key] is float:
						self.__dict__[key] = float(self.global_dict[category].get(key, self.__dict__[key]))
					elif type_map[key] is int:
						self.__dict__[key] = int(self.global_dict[category].get(key, self.__dict__[key]))
					elif type_map[key] is bool:
						self.__dict__[key] = bool(self.global_dict[category].get(key, self.__dict__[key]))
					elif type_map[key] is str:
						self.__dict__[key] = str(self.global_dict[category].get(key, self.__dict__[key]))
			if self.mov_dict.get(category) is not None:
				for key in list(self.mov_dict[category].keys()):
					if type_map[key] is float:
						self.__dict__[key] = float(self.mov_dict[category].get(key, self.__dict__[key]))
					elif type_map[key] is int:
						self.__dict__[key] = int(self.mov_dict[category].get(key, self.__dict__[key]))
					elif type_map[key] is bool:
						self.__dict__[key] = bool(self.mov_dict[category].get(key, self.__dict__[key]))
					elif type_map[key] is str:
						self.__dict__[key] = str(self.mov_dict[category].get(key, self.__dict__[key]))

	#===============================
	def timeCodeToSeconds(self, timecode):
		colons = timecode.split(':')
		seconds = float(colons.pop())
		minutes = int(colons.pop())
		if len(colons) > 0:
			hours = int(colons.pop())
		else:
			hours = 0
		totalseconds = hours*3600 + minutes*60 + seconds
		return totalseconds

	#===============================
	def checkMovieFile(self):
		self.movfile = self.mov_dict.get('file')
		if self.movfile is None:
			print("file not specified for processing")
			sys.exit(1)
		if not os.path.exists(self.movfile):
			print(("file not found %s"%(self.movfile)))
			sys.exit(1)
		medialib.getMediaInfo(self.movfile)

	#===============================
	def checkMovieTimings(self):
		self.timing = self.mov_dict.get('timing')
		if self.timing is None:
			print(("timing information not provided for movie %s"%(self.ovfile)))
			sys.exit(1)
		self.time_mapping = {}
		self.times = []
		for timecode in list(self.timing.keys()):
			seconds = self.timeCodeToSeconds(timecode)
			self.time_mapping[seconds] = timecode
			self.times.append(seconds)
		self.times.sort()

	#===============================
	def getAVSync(self):
		raw_avsync = self.mov_dict.get('avsync')
		if raw_avsync is None:
			return 0.0
		raw_avsync = raw_avsync.strip()
		if ':' in raw_avsync:
			avsync = self.timeCodeToSeconds(raw_avsync)
		elif raw_avsync.endswith("ms"):
			avsync = float(raw_avsync[:-2])/1000.
		elif raw_avsync.endswith("sec"):
			avsync = float(raw_avsync[:-3])
		else:
			avsync = 0.0
		return avsync

	#===============================
	def processNoise(self, orig_wavfile):
		noisetime1 = None
		for i in range(len(self.times)):
			time = self.times[i]
			flags = self.timing[self.time_mapping[time]]
			if not isinstance(flags, dict):
				print(("error: movie flags must be a dict: %s"%(str(flags))))
				sys.exit(1)
			if 'noise' in flags:
				noisetime1 = time
				noisetime2 = self.times[i+1]
		if noisetime1 is None:
			if self.debug is True:
				print("no noise section flagged, skipping noise reduction")
			return orig_wavfile
		noise_wavfile = soxlib.removeNoise(orig_wavfile, noisetime1, noisetime2)
		return noise_wavfile

	#===============================
	def processAudio(self):
		### process audio
		avsync = self.getAVSync()
		raw_wavfile = ffmpeglib.extractAudio(self.movfile,
			samplerate=self.samplerate, bitrate=self.bitrate, audio_mode=self.audio_mode)
		norm_wavfile = soxlib.normalizeAudio(raw_wavfile, level=self.norm_level,
			samplerate=self.samplerate, bitrate=self.bitrate)
		if avsync > 0:
			shift_wavfile = soxlib.addSilenceToStart(norm_wavfile, seconds=avsync,
				samplerate=self.samplerate, bitrate=self.bitrate, audio_mode=self.audio_mode)
			os.remove(norm_wavfile)
			norm_wavfile = shift_wavfile
		if norm_wavfile != raw_wavfile:
			os.remove(raw_wavfile)
		if self.extra_audio_process is True:
			#noise_wavfile = self.processNoise(norm_wavfile)
			#if noise_wavfile != norm_wavfile:
			#	os.remove(norm_wavfile)
			#gate_wavfile = soxlib.noiseGate(noise_wavfile)
			#if gate_wavfile != noise_wavfile:
			#	os.remove(noise_wavfile)
			dnr_wavfile = soxlib.compressAudio(norm_wavfile, reverse_compress=self.reverse_compress)
			if dnr_wavfile != norm_wavfile:
				os.remove(norm_wavfile)
			band_wavfile = soxlib.bandPassFilter(dnr_wavfile)
			if band_wavfile != dnr_wavfile:
				os.remove(dnr_wavfile)
			norm_wavfile = "audio-norm-%s.wav"%(self.makeTimestamp())
			soxlib.normalizeAudio(band_wavfile, norm_wavfile, level=self.norm_level,
				samplerate=self.samplerate, bitrate=self.bitrate)
			if norm_wavfile != band_wavfile:
				os.remove(band_wavfile)

		self.wavfile = norm_wavfile
		## clean up wave files

	#===============================
	def splitAudio(self, filename, splitwavfile, startseconds, endseconds):
		return soxlib.splitAudioSox(filename, splitwavfile, self.movframerate, startseconds, endseconds)
		return ffmpeglib.splitAudioFfmpeg(filename, splitwavfile, startseconds, endseconds)

	#=====================
	def makeTimestamp(self):
		datestamp = time.strftime("%y%b%d").lower()
		uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
		hourstamp = uppercase[(time.localtime()[3])%26]
		minstamp = "%02d"%(time.localtime()[4])
		secstamp = uppercase[(time.localtime()[5])%26]
		timestamp = datestamp+hourstamp+minstamp+secstamp
		return timestamp

	#===============================
	def processMovie(self):
		self.checkMovieFile()
		self.checkMovieTimings()
		self.processAudio()
		filesToMerge = []
		for i in range(len(self.times)-1):
			count = i+1
			starttime = self.times[i]
			endtime = self.times[i+1]
			flags = self.timing[self.time_mapping[starttime]]
			sys.stderr.write("\n### %04d - %04d: %s "%(starttime, endtime, str(flags)))
			if skipcodes.get(flags.get('type')): 
				print(("skipping section %d..."%(count)))
				continue

			print("processing...")
			out_video_file = "video-section%02d.mkv"%(count)
			out_audio_file = "audio-section%02d.wav"%(count)
			merge_file = "merge-section%02d.mkv"%(count)

			if flags.get('type') == 'fastforward':
				speed = float(self.global_dict['speed'].get('fast_forward', 25))
			else:
				speed = float(self.global_dict['speed'].get('normal', 1.1))
			#cut video
			print(("SPEED: %.1f"%(speed)))
			ffmpeglib.processVideo(self.movfile, out_video_file, starttime, endtime,
				speed=speed, crf=self.crf, movframerate=self.movframerate)

			if flags.get('titlecard'):
				titlecard_movfile = self.createTitleCard(flags['titlecard'], count)
				filesToMerge.append(titlecard_movfile)

			#cut audio
			self.splitAudio(self.wavfile, "audio-split.wav", starttime, endtime)
			soxlib.speedUpAudio("audio-split.wav", out_audio_file, speed=speed,
				samplerate=self.samplerate, bitrate=self.bitrate)
			os.remove("audio-split.wav")
			if self.global_dict['audio'].get('audio_format').upper() == 'MP3':
				wavfile = out_audio_file
				out_audio_file = "audio-section%02d.mp3"%(count)
				self.wavToMp3(wavfile, out_audio_file, preset=self.lame_preset)
				os.remove(wavfile)

			#merge
			self.mergeAV(out_video_file, out_audio_file, merge_file)
			os.remove(out_video_file)
			os.remove(out_audio_file)
			filesToMerge.append(merge_file)

		print("")
		print(filesToMerge)
		print("MERGE movies")
		timestamp = self.makeTimestamp()
		self.finalmovie = "processed-movie-%s.mkv"%(timestamp)
		self.editor.concatenateMovies(filesToMerge, self.finalmovie)
		print(("mpv %s"%(self.finalmovie)))
		for movfile in filesToMerge:
			os.remove(movfile)
		os.remove(self.wavfile)

	#===============================
	def createTitleCard(self, titledict, count):
		tc = titlecard.TitleCard()
		tc.text = titledict.get('text')
		(width, height) = medialib.getVideoDimensions(self.movfile)
		tc.width = width 
		tc.height = height
		tc.framerate = self.movframerate
		tc.length = 2.0
		tc.crf = self.crf
		out_video_file = "titlecard-video-section%02d.mkv"%(count)
		tc.outfile = out_video_file
		out_audio_file = "titlecard-audio-section%02d.wav"%(count)
		merge_file = "titlecard-merge-section%02d.mkv"%(count)
		if titledict.get('font_size'):
			tc.size = int(titledict.get('font_size'))
		tc.setType()
		tc.createCards()

		convwavfile = "audio-tc-convert.wav"
		soxlib.convertAudioToWav(titledict.get('audio_file'),  convwavfile, audio_mode=self.audio_mode)

		norm_level = titledict.get('norm_level', self.norm_level)
		normwavfile = "audio-tc-norm.wav"
		soxlib.normalizeAudio(convwavfile, normwavfile, level=norm_level,
			samplerate=self.samplerate, bitrate=self.bitrate)
		os.remove(convwavfile)

		endtime = medialib.getDuration(out_video_file)
		speed = float(self.global_dict['speed'].get('normal', 1.1))
		self.splitAudio(normwavfile, "audio-split.wav", 0, endtime*speed)
		os.remove(normwavfile)

		soxlib.speedUpAudio("audio-split.wav", out_audio_file, speed=speed,
			samplerate=self.samplerate, bitrate=self.bitrate)
		os.remove("audio-split.wav")

		if self.global_dict['audio'].get('audio_format').upper() == 'MP3':
			wavfile = out_audio_file
			out_audio_file = "titlecard-audio-section%02d.mp3"%(count)
			self.wavToMp3(wavfile, out_audio_file, preset=self.lame_preset)
			os.remove(wavfile)

		self.mergeAV(out_video_file, out_audio_file, merge_file)
		os.remove(out_video_file)
		os.remove(out_audio_file)
		return merge_file

	#===============================
	def wavToMp3(self, wavfile, mp3file, preset='medium'):
		presetlist = ['voice', 'radio', 'medium', 'standard', 'extreme']
		cmd = "lame "
		cmd += " --nohist -q 0 -p "
		cmd += " --preset %s "%(preset)
		cmd += "'%s' "%(wavfile)
		cmd += "'%s' "%(mp3file)
		runCmd(cmd)

	#===============================
	def mergeAV(self, video_file, audio_file, merge_file):
		vtime = medialib.getDuration(video_file)
		atime = medialib.getDuration(audio_file)
		print(("Audio: %.3f // Video %.3f"%(atime, vtime)))
		if abs(atime - vtime) > 0.1:
			print(("time error: %.3f %.3f"%(atime,vtime)))
			sys.exit(1)
		cmd = "mkvmerge -A -S %s -D -S %s -o %s"%(video_file, audio_file, merge_file)
		runCmd(cmd)
		if not os.path.isfile(merge_file):
			print("A/V merge failed")
			sys.exit(1)
		return merge_file

	#===============================
	def getFinalMovieFile(self):
		return self.finalmovie

#===============================
#===============================
#===============================
if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='CLI Movie Editor')
	parser.add_argument('-y', '--yaml', dest='yamlfile',
		help='main yaml file that outlines the processing to do')
	args = parser.parse_args()

	editor = EditControl(args.yamlfile)
	pprint.pprint(editor.global_dict)
	pprint.pprint(editor.movie_tree)
	editor.processAllMovies()


