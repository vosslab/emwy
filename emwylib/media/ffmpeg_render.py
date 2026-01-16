
import os
import sys
import time
from emwylib.core import utils

#============================================

def runCmd(cmd: str, msg: bool = False) -> None:
	utils.runCmd(cmd)
	return

#============================================

def processVideo(movfile: str, outfile: str, starttime: float,
	endtime: float, speed: float = 1.1, crf: int = 25,
	movframerate: int = 60, preset: str = 'ultrafast') -> str:
	t0 = time.time()
	cmd = "ffmpeg -y "
	cmd += f" -ss {starttime:.2f} -t {endtime - starttime:.2f} "
	cmd += f" -i {movfile} "
	cmd += " -sn -an -map_chapters -1 -map_metadata -1 "
	cmd += f" -codec:v libx265 -crf {crf} -preset {preset} "
	cmd += " -tune fastdecode -profile:v main444-12 -pix_fmt yuv420p "
	cmd += f" -r {movframerate} "
	if abs(speed - 1.0) > 0.01:
		cmd += f" -filter:v 'setpts={1.0 / speed:.8f}*PTS' "
	cmd += f" {outfile} "
	runCmd(cmd)
	if not os.path.isfile(outfile):
		print(f"fast forward {speed:.1f}X failed")
		sys.exit(1)
	print(f"Complete in {int(time.time() - t0)} seconds")
	return outfile

#============================================

def addWatermark(movfile: str, outfile: str, watermark_file: str = None,
	crf: int = 25, movframerate: int = 60, preset: str = 'ultrafast') -> str:
	t0 = time.time()
	cmd = "ffmpeg -y "
	cmd += f" -i '{movfile}' "
	cmd += " -sn -an "
	cmd += f" -i '{watermark_file}' "
	cmd += " -filter_complex 'overlay=main_w-overlay_w-10:main_h-overlay_h-10'"
	cmd += f" -codec:v libx265 -crf {crf} -preset {preset} "
	cmd += " -tune fastdecode -profile:v high -pix_fmt yuv420p "
	cmd += f" -r {movframerate} "
	cmd += f" {outfile} "
	runCmd(cmd)
	if not os.path.isfile(outfile):
		print("add watermark failed")
		sys.exit(1)
	print(f"Complete in {int(time.time() - t0)} seconds")
	return outfile

#============================================

def replaceAudio(movfile: str, wavfile: str, newmovfile: str) -> str:
	cmd = "ffmpeg -y "
	cmd += f" -i '{movfile}' "
	cmd += f" -i '{wavfile}' "
	cmd += " -sn "
	cmd += " -map 0:v -map 1:a "
	cmd += " -codec copy -shortest "
	cmd += f" '{newmovfile}' "
	runCmd(cmd)
	if not os.path.isfile(newmovfile):
		print("replace audio failed")
		sys.exit(1)
	return newmovfile
