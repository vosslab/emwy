#!/usr/bin/env python

import re
import os
import sys
import time
import subprocess

#===============================
def runCmd(cmd, msg=False):
	showcmd = cmd.strip()
	showcmd = re.sub("  *", " ", showcmd)
	print(("CMD: '%s'"%(showcmd)))
	if msg is True:
		proc = subprocess.Popen(showcmd, shell=True)
	else:
		proc = subprocess.Popen(showcmd, shell=True,
			stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	proc.communicate()
	return

#===============================
def splitAudioFfmpeg(movfile, wavfile, startseconds, endseconds, samplerate=96, bitrate=24):
	# not used, created for testing purposes only
	sys.exit(1)
	cutseconds = endseconds - startseconds
	cmd  = "ffmpeg -y "
	cmd += " -ss %.2f -t %.2f "%(startseconds, cutseconds)
	cmd += " -i %s "%(movfile)
	cmd += " -sn -vn "
	cmd += " -acodec pcm_s%dle -ar %d -rf64 auto "%(bitrate, samplerate)
	cmd += " '%s' "%(wavfile)
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print("extract audio failed")
		sys.exit(1)
	return wavfile

#===============================
def processVideo(movfile, outfile, starttime, endtime, speed=1.1, crf=25, movframerate=60, preset='ultrafast'):
	t0 = time.time()
	cmd  = "ffmpeg -y "
	cmd += " -ss %.2f -t %.2f "%(starttime, endtime-starttime)
	cmd += " -i %s "%(movfile)
	cmd += " -sn -an -map_chapters -1 -map_metadata -1 "
	#cmd += " -i ~/sh/vosslab_logo-vector50.png "
	#cmd += " -filter_complex 'overlay=main_w-overlay_w-10:main_h-overlay_h-10'"
	cmd += " -codec:v libx265 -crf %d -preset %s "%(crf, preset)
	cmd += " -tune fastdecode -profile:v high -pix_fmt yuv420p "
	cmd += " -r %d "%(movframerate)
	if abs(speed - 1.0) > 0.01:
		cmd += " -filter:v 'setpts=%.8f*PTS' "%(1.0/speed)
	cmd += " %s "%(outfile)
	runCmd(cmd)
	if not os.path.isfile(outfile):
		print(("fast forward %.1fX failed"%(speed)))
		sys.exit(1)
	print(("Complete in %d seconds"%(time.time() - t0)))
	return outfile

#===============================
def addWatermark(movfile, outfile, watermark_file=None, crf=25, movframerate=60, preset='ultrafast'):
	t0 = time.time()
	cmd  = "ffmpeg -y "
	cmd += " -i '%s' "%(movfile)
	cmd += " -sn -an "
	cmd += " -i '%s' "%(watermark_file)
	cmd += " -filter_complex 'overlay=main_w-overlay_w-10:main_h-overlay_h-10'"
	cmd += " -codec:v libx265 -crf %d -preset %s "%(crf, preset)
	cmd += " -tune fastdecode -profile:v high -pix_fmt yuv420p "
	cmd += " -r %d "%(movframerate)
	cmd += " %s "%(outfile)
	runCmd(cmd)
	if not os.path.isfile(outfile):
		print("add watermark failed")
		sys.exit(1)
	print(("Complete in %d seconds"%(time.time() - t0)))
	return outfile

#===============================
def replaceAudio(movfile, wavfile, newmovfile):
	cmd  = "ffmpeg -y "
	cmd += " -i '%s' "%(movfile)
	cmd += " -i '%s' "%(wavfile)
	cmd += " -sn "
	cmd += " -map 0:v -map 1:a "
	cmd += " -codec copy -shortest "
	cmd += " '%s' "%(newmovfile)
	runCmd(cmd)
	if not os.path.isfile(newmovfile):
		print("replace audio failed")
		sys.exit(1)
	return newmovfile

#===============================
def extractAudio(movfile, wavfile='audio-raw.wav', samplerate=96, bitrate=24, audio_mode=None):
	cmd  = "ffmpeg -y "
	cmd += " -i '%s' "%(movfile)
	cmd += " -sn -vn "
	cmd += " -acodec pcm_s%dle -ar %d -rf64 auto "%(bitrate, samplerate)
	if audio_mode == "mono":
		cmd += " -ac 1 "
	elif audio_mode == "stereo":
		cmd += " -ac 2 "
	cmd += " '%s' "%(wavfile)
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print("extract audio failed")
		sys.exit(1)
	return wavfile

