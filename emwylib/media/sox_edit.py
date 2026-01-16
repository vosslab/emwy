
import os
import sys
import time
from emwylib.core import utils

#============================================

def runCmd(cmd: str, msg: bool = False) -> None:
	utils.runCmd(cmd)
	return

#============================================

def convertAudioToWav(infile: str, wavfile: str, audio_mode: str = None) -> str:
	if audio_mode is None:
		mode_text = ""
	elif audio_mode == "mono":
		mode_text = " channels 1 "
	elif audio_mode == "stereo":
		mode_text = " channels 2 "
	cmd = f"sox {infile} {wavfile} {mode_text}"
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print("convert audio failed")
		sys.exit(1)
	return wavfile

#============================================

def splitAudioSox(wavfile: str, splitwavfile: str, movframerate: float,
	startseconds: float, endseconds: float) -> str:
	cutseconds = endseconds - startseconds
	gap = 1.0 / movframerate
	start = startseconds - gap
	if start < 0:
		start = 0
	cutseconds += gap
	cmd = f"sox {wavfile} {splitwavfile} trim {start:.3f} {cutseconds:.3f}"
	runCmd(cmd)
	if not os.path.isfile(splitwavfile):
		print("speed up audio failed")
		sys.exit(1)
	return splitwavfile

#============================================

def speedUpAudio(wavfile: str, fastwavfile: str = "audio-fast.wav",
	speed: float = 1.1, samplerate: int = None, bitrate: int = None) -> str:
	t0 = time.time()
	cmd = f"sox {wavfile} "
	if samplerate is not None:
		cmd += f"-r {samplerate} "
	if bitrate is not None:
		cmd += f"-b {bitrate} "
	cmd += f"{fastwavfile} tempo -s {speed:.8f}"
	runCmd(cmd)
	if not os.path.isfile(fastwavfile):
		print("speed up audio failed")
		sys.exit(1)
	print(f"Complete in {int(time.time() - t0)} seconds")
	return fastwavfile

#============================================

def addSilenceToStart(wavfile: str, addwavfile: str = "audio-shift.wav",
	seconds: float = 3.0, samplerate: int = None, bitrate: int = None,
	audio_mode: str = None) -> str:
	silentwav = makeSilence("silence.wav", seconds=seconds,
		samplerate=samplerate, bitrate=bitrate, audio_mode=audio_mode)
	combineWaveFiles(silentwav, wavfile, addwavfile)
	if not os.path.isfile(addwavfile):
		print("add Silence To Start failed")
		sys.exit(1)
	os.remove(silentwav)
	return addwavfile

#============================================

def combineWaveFiles(wavfile1: str, wavfile2: str,
	mergewavfile: str = "audio-merge.wav") -> str:
	cmd = f"sox {wavfile1} {wavfile2} {mergewavfile}"
	runCmd(cmd)
	if not os.path.isfile(mergewavfile):
		print("merge wav files failed")
		sys.exit(1)
	return mergewavfile

#============================================

def makeSilence(wavfile: str = "silence.wav", seconds: float = 3.0,
	samplerate: int = None, bitrate: int = None, audio_mode: str = None) -> str:
	cmd = "sox --null "
	if samplerate is not None:
		cmd += f"-r {samplerate} "
	if bitrate is not None:
		cmd += f"-b {bitrate} "
	if audio_mode is None:
		mode_text = ""
	elif audio_mode == "mono":
		mode_text = " -c 1 "
	elif audio_mode == "stereo":
		mode_text = " -c 2 "
	cmd += f" {mode_text} {wavfile} trim 0.0 {seconds:.4f}"
	runCmd(cmd)
	if not os.path.isfile(wavfile):
		print("silence creation failed")
		sys.exit(1)
	return wavfile
