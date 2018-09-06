
#python wrapper for mediainfo

import json
import subprocess

#===============================
def getMediaInfo(mediafile):
	cmd = "mediainfo --Output=JSON %s"%(mediafile)
	proc = subprocess.Popen(cmd, shell=True,
		stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	stdout, stderr = proc.communicate()
	rawdata = json.loads(stdout)
	data = rawdata.get('media')
	return data

#===============================
def getDuration(mediafile):
	data = getMediaInfo(mediafile)
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