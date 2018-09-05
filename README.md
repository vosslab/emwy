# emwy

**emwy** stands for "*edit movies with yaml*" it is a command line tool for 
splicing and combining movies.

# Why emwy?

Most GUI based NLE (non-linear editors) have a high latency while
editing which slowed things down and did not match my style. 

I did a search for other command line editors, but did not find any at
the time, so I wrote my own. Since I have found two:

* [AviSynth](http://avisynth.nl/index.php/Main_Page)
* [MLT Multimedia Framework](https://www.mltframework.org/)

but they did not have any good documentation,
[see stackexchange](https://video.stackexchange.com/questions/7459/)

>  "powerful, if somewhat obscure, multitrack command line oriented video editor…"

# Software pre-requisities

emwy is a python package, so it does not need to be compiled, 
but it expects several packages to exist on the system already.

## software packages:
* [ffmpeg (with x264 codec)](https://www.ffmpeg.org)
* [lame](http://lame.sourceforge.net)
* [mediainfo](https://mediaarea.net/MediaInfo) ; version 18.03 or newer from March 2018
* [python](https://python.org), tested on python 2.7, my day job is using python 2.7
* [sox](http://sox.sourceforge.net)

## python modules:
* [numpy](https://www.numpy.org)
* [pillow](https://pillow.readthedocs.io)
* [scipy](https://www.scipy.org)
* [tqdm](https://github.com/tqdm/tqdm)
* [yaml](https://pyyaml.org)
