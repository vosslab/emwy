#!/usr/bin/env python3

import os
import sys
from emwylib.core import utils

#============================================

def runCmd(cmd: str, msg: bool = False) -> None:
	utils.runCmd(cmd)
	return

#============================================

def splitAudioFfmpeg(movfile: str, wavfile: str, startseconds: float,
	endseconds: float, samplerate: int = 96, bitrate: int = 24) -> str:
	# not used, created for testing purposes only
	sys.exit(1)
	cutseconds = endseconds - startseconds
	cmd = "ffmpeg -y "
	cmd += f" -ss {startseconds:.2f} -t {cutseconds:.2f} "
	cmd += f" -i {movfile} "
	cmd += " -sn -vn "
	cmd += f" -acodec pcm_s{bitrate}le -ar {samplerate} -rf64 auto "
	cmd += f" '{wavfile}' "
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print("extract audio failed")
		sys.exit(1)
	return wavfile

#============================================

def extractAudio(movfile: str, wavfile: str = 'audio-raw.wav',
	samplerate: int = 96, bitrate: int = 24, audio_mode: str = None) -> str:
	cmd = "ffmpeg -y "
	cmd += f" -i '{movfile}' "
	cmd += " -sn -vn "
	cmd += f" -acodec pcm_s{bitrate}le -ar {samplerate} -rf64 auto "
	if audio_mode == "mono":
		cmd += " -ac 1 "
	elif audio_mode == "stereo":
		cmd += " -ac 2 "
	cmd += f" '{wavfile}' "
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print("extract audio failed")
		sys.exit(1)
	return wavfile
