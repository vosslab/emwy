
#python wrapper for mediainfo

import json
import subprocess

#===============================
def getMediaInfo(mediafile):
	cmd = "mediainfo --Output=JSON %s"%(mediafile)
	try:
		proc = subprocess.Popen(cmd, shell=True,
			stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	except ValueError as exc:
		if "fds_to_keep" in str(exc):
			proc = subprocess.Popen(cmd, shell=True,
				stderr=subprocess.PIPE, stdout=subprocess.PIPE, close_fds=False)
		else:
			raise
	stdout, stderr = proc.communicate()
	rawdata = json.loads(stdout)
	data = rawdata.get('media')
	return data

#===============================
def getDuration(mediafile):
	data = getMediaInfo(mediafile)
	print("getDuration", mediafile)
	duration = float(data['track'][0]['Duration'])
	return duration

#===============================
def getVideoDimensions(mediafile):
	data = getMediaInfo(mediafile)
	videotrack = None
	for track in data.get('track'):
		if track.get('@type') == 'Video':
			videotrack = track
	if videotrack is None:
		return None
	width = int(videotrack['Width'])
	height = int(videotrack['Height'])
	return (width, height)
