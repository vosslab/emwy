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
	print "CMD: '%s'"%(showcmd)
	if msg is True:
		proc = subprocess.Popen(showcmd, shell=True)
	else:
		proc = subprocess.Popen(showcmd, shell=True,
			stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	proc.communicate()
	return

#===============================
def normalizeAudio(wavfile, normwavfile="audio-norm.wav", level=-1.9, samplerate=None, bitrate=None):
	cmd = "sox %s "%(wavfile,)
	if samplerate is not None:
		cmd += "-r %d "%(samplerate,)
	if bitrate is not None:
		cmd += "-b %d "%(bitrate,)
	cmd += "%s norm %.1f"%(normwavfile, level)
	runCmd(cmd)
	if not os.path.isfile(normwavfile):
		print "normalize audio failed"
		sys.exit(1)
	return normwavfile

#===============================
def removeNoise(wavfile, startseconds=0, endseconds=None, amount=0.21):
	#https://stackoverflow.com/questions/44159621/how-to-denoise-with-sox
	cleanwavfile = "audio-clean.wav"
	cutseconds = endseconds - startseconds
	cmd = "sox %s noise-audio.wav trim %.1f %.3f"%(wavfile, startseconds+1, cutseconds-1)
	runCmd(cmd)
	cmd = "sox noise-audio.wav -n noiseprof noise.prof"
	runCmd(cmd)
	cmd = "sox %s %s noisered noise.prof %.2f"%(wavfile, cleanwavfile, amount)
	runCmd(cmd)
	if not os.path.isfile(cleanwavfile):
		print "remove noise from audio failed"
		sys.exit(1)
	return cleanwavfile

#===============================
def noiseGate(wavfile, level=40):
	# gate level, lower number higher the gatex
	gatedwavfile = "audio-gate.wav"
	cmd = ("sox %s %s compand .1,.2 -inf,-%d.1,-inf,-%d,-%d 0 -90 .1"
		%(wavfile, gatedwavfile, level, level, level))
	runCmd(cmd)
	if not os.path.isfile(gatedwavfile):
		print "noise gate failed"
		sys.exit(1)
	return gatedwavfile

#===============================
def bandPassFilter(wavfile, filtwavfile="audio-filter.wav", highpass=20, lowpass=10000):
	cmd = "sox %s %s lowpass %d highpass %d"%(wavfile, filtwavfile, lowpass, highpass)
	runCmd(cmd)
	if not os.path.isfile(filtwavfile):
		print "band pass filter failed"
		sys.exit(1)
	return filtwavfile

#===============================
def convertAudioToWav(infile, wavfile, audio_mode=None):
	#need to be smarter
	if audio_mode is None:
		mode_text = ""
	elif audio_mode == "mono":
		mode_text = " channels 1 "
	elif audio_mode == "stereo":
		mode_text = " channels 2 "
	#stereo to mono
	cmd = ("sox %s %s %s"
		%(infile, wavfile, mode_text))
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print "convert audio failed"
		sys.exit(1)
	return wavfile

#===============================
def splitAudioSox(wavfile, splitwavfile, movframerate, startseconds, endseconds):
	cutseconds = endseconds - startseconds
	### correction for audio sync between ffmpeg and sox
	### one over the frame rate??
	gap = 1.0/movframerate
	start = startseconds - gap
	end = cutseconds + gap
	if start < 0:
		start = 0
		end += gap
	cmd = ("sox %s %s trim %.3f %.3f"
		%(wavfile, splitwavfile, start, cutseconds + gap))
	runCmd(cmd)
	if not os.path.isfile(splitwavfile):
		print "speed up audio failed"
		sys.exit(1)
	return splitwavfile

#===============================
def speedUpAudio(wavfile, fastwavfile="audio-fast.wav", speed=1.1, samplerate=None, bitrate=None):
	t0 = time.time()
	cmd = "sox %s "%(wavfile,)
	if samplerate is not None:
		cmd += "-r %d "%(samplerate,)
	if bitrate is not None:
		cmd += "-b %d "%(bitrate,)
	cmd += "%s tempo -s %.8f"%(fastwavfile, speed)
	runCmd(cmd)
	if not os.path.isfile(fastwavfile):
		print "speed up audio failed"
		sys.exit(1)
	print "Complete in %d seconds"%(time.time() - t0)
	return fastwavfile

#===============================
def compressAudio(wavfile, drcwavfile="audio-drc.wav", reverse_compress=True):
	cmd = "sox %s %s compand 0.2,1 6:-70,-60,-20 -13 -50 0.2 "%(wavfile, drcwavfile)
	if reverse_compress is True:
		#double DRC in reverse direction
		cmd += " reverse compand 0.2,1 6:-70,-60,-20 -13 -50 0.2 reverse "
	runCmd(cmd)
	if not os.path.isfile(drcwavfile):
		print "dynamic range compression failed"
		sys.exit(1)
	return drcwavfile
