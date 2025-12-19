# About emwy

**emwy** stands for "*<u>e</u>dit <u>m</u>ovies <u>w</u>ith <u>y</u>aml*" it is a command line tool for splicing and combining movies, with many custom features that really only I wanted.

**emwy** is pronounced as one syllable like a child attempting to say the name "Emily", but getting the "W" sound instead of the "L" sound and skipping the "i" in the middle, i.e., "em-wee" or em'wi.

## Why create emwy?

Most GUI based NLE (non-linear editors) have a high latency while editing which slowed things down and did not match my style.

I did a search for other command line editors, but did not find any at the time, so I wrote my own. Since I have found two:

* [AviSynth](http://avisynth.nl/index.php/Main_Page)
* [MLT Multimedia Framework](https://www.mltframework.org/)

but they did not have any good documentation, [see stackexchange](https://video.stackexchange.com/questions/7459/)

>  "powerful, if somewhat obscure, multitrack command line oriented video editor"

# Usage

## Sample yaml code

download a sample youtube video ([using youtube-dl](https://rg3.github.io/youtube-dl/)) and we'll use yaml to splice the video

```youtube-dl http://youtu.be/9bZkp7q19f0 -o Psy-Gangnam_Style.mp4```

save the following code to the file `gangnam.yml`:

```
- type: global
  quality: fast  #options: high, fast
  speed:
    normal: 1.1
  audio:
    norm_level: -2
    audio_format: MP3
    audio_mode: stereo
  output_file: Psy-Gangnam_Style-Only_Horses.mkv

- type: movie
  file: Psy-Gangnam_Style.mp4
  timing:
    '00:18.1': {type: normal, }
    '00:21.5': {type: skip }
    '00:25.5': {type: normal, }
    '00:27.7': {type: skip, }
    '00:29.5': {type: normal, }
    '00:31.1': {type: skip, }
    '01:11.4': {type: normal, }
    '01:14.6': {type: skip, }
    '01:24.0': {type: normal, }
    '01:27.0': {type: skip, }
    '02:54.8': {type: normal, }
    '02:59.9': {type: skip, }
    '04:00.0': {type: stop, }
```

then run the command:

```emwy.py -y gangnam.yml```

the code with cut and splice the video to create `Psy-Gangnam_Style-Only_Horses.mkv`

# Installation

## Software pre-requisities

emwy is a python package, so it does not need to be compiled,
but it expects several packages to exist on the system already.

### software packages:
* [ffmpeg (with x264 codec)](https://www.ffmpeg.org)
* [lame](http://lame.sourceforge.net)
* [mediainfo](https://mediaarea.net/MediaInfo) ; version 18.03 or newer from March 2018
* [mkvtoolnix](https://mkvtoolnix.download/)
* [python](https://python.org), tested on python 2.7 and 3.8
* [sox](http://sox.sourceforge.net)

### python modules:
* [numpy](https://www.numpy.org)
* [pillow](https://pillow.readthedocs.io)
* [scipy](https://www.scipy.org)
* [tqdm](https://github.com/tqdm/tqdm)
* [yaml](https://pyyaml.org)
