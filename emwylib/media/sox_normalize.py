
import os
import sys
from emwylib.core import utils

#============================================

def runCmd(cmd: str, msg: bool = False) -> None:
	utils.runCmd(cmd)
	return

#============================================

def normalizeAudio(wavfile: str, normwavfile: str = "audio-norm.wav",
	level: float = -1.9, samplerate: int = None, bitrate: int = None) -> str:
	cmd = f"sox {wavfile} "
	if samplerate is not None:
		cmd += f"-r {samplerate} "
	if bitrate is not None:
		cmd += f"-b {bitrate} "
	cmd += f"{normwavfile} norm {level:.1f}"
	runCmd(cmd)
	if not os.path.isfile(normwavfile):
		print("normalize audio failed")
		sys.exit(1)
	return normwavfile

#============================================

def removeNoise(wavfile: str, startseconds: float = 0, endseconds: float = None,
	amount: float = 0.21) -> str:
	cleanwavfile = "audio-clean.wav"
	cutseconds = endseconds - startseconds
	cmd = f"sox {wavfile} noise-audio.wav trim {startseconds + 1:.1f} {cutseconds - 1:.3f}"
	runCmd(cmd)
	cmd = "sox noise-audio.wav -n noiseprof noise.prof"
	runCmd(cmd)
	cmd = f"sox {wavfile} {cleanwavfile} noisered noise.prof {amount:.2f}"
	runCmd(cmd)
	if not os.path.isfile(cleanwavfile):
		print("remove noise from audio failed")
		sys.exit(1)
	return cleanwavfile

#============================================

def noiseGate(wavfile: str, level: int = 40) -> str:
	gatedwavfile = "audio-gate.wav"
	cmd = (
		"sox %s %s compand .1,.2 -inf,-%d.1,-inf,-%d,-%d 0 -90 .1"
		%(wavfile, gatedwavfile, level, level, level)
	)
	runCmd(cmd)
	if not os.path.isfile(gatedwavfile):
		print("noise gate failed")
		sys.exit(1)
	return gatedwavfile

#============================================

def bandPassFilter(wavfile: str, filtwavfile: str = "audio-filter.wav",
	highpass: int = 20, lowpass: int = 10000) -> str:
	cmd = f"sox {wavfile} {filtwavfile} lowpass {lowpass} highpass {highpass}"
	runCmd(cmd)
	if not os.path.isfile(filtwavfile):
		print("band pass filter failed")
		sys.exit(1)
	return filtwavfile

#============================================

def compressAudio(wavfile: str, drcwavfile: str = "audio-drc.wav",
	reverse_compress: bool = True) -> str:
	cmd = f"sox {wavfile} {drcwavfile} compand 0.2,1 6:-70,-60,-20 -13 -50 0.2 "
	if reverse_compress is True:
		cmd += " reverse compand 0.2,1 6:-70,-60,-20 -13 -50 0.2 reverse "
	runCmd(cmd)
	if not os.path.isfile(drcwavfile):
		print("dynamic range compression failed")
		sys.exit(1)
	return drcwavfile
