#!/usr/bin/env python

###
#set of programs to create a title card video
###

import os
import random
import shutil
import sys
import tempfile
import numpy
from tqdm import tqdm
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from scipy.ndimage import gaussian_filter
from emwylib.transforms import RGBTransform
from emwylib.core import utils

#===============================
class TitleCard(object):
	def __init__(self):
		self.length = 3
		self.text = "Orion Voss"
		self.size = 128
		self.width = 1600
		self.height = 900
		self.crf = 28
		self.fontfile = None
		self.bgcolor = (51, 153, 255)
		self.textcolor = (142, 71, 0)
		self.fnt = None
		self.framerate = 60
		self.defaultshift = 0.5
		self.imgcode = "aaadahsdgg"
		self.outfile = "titlecard.mkv"
		self.randimg = None
		self.temp_dir = None
		self.quiet = False
		
	#===============================
	def setType(self):
		self.fnt = self._load_font()
		textsize = self._measure_text(self.text)
		self.w = int(round(self.width/2.0 - textsize[0]/2.0))
		self.h = int(round(self.height/2.0 - textsize[1]/2.0))
		self.topband = int(round(self.height/2.0 - textsize[1]))
		self.bottomband = int(round(self.height/2.0 + textsize[1]))
		return

	#===============================
	def _measure_text(self, text):
		if hasattr(self.fnt, "getbbox"):
			bbox = self.fnt.getbbox(text)
			width = bbox[2] - bbox[0]
			height = bbox[3] - bbox[1]
			return (width, height)
		return self.fnt.getsize(text)

	#===============================
	def alterColor(self, rgb1, shift):
		r,g,b = rgb1
		rgb2 = ( self.alterInt(r, shift),
					self.alterInt(g, shift),
					self.alterInt(b, shift)
				)
		return rgb2

	#===============================
	def alterInt(self, i, shift):
		i += random.gauss(0, shift)
		return int(round(i))

	#===============================
	def makeMovieFromImages(self, imglist, image_dir=None):
		if image_dir is None:
			if len(imglist) > 0:
				image_dir = os.path.dirname(imglist[0])
		if image_dir is None or image_dir == "":
			image_dir = "."
		image_pattern = os.path.join(image_dir, "%s%s.png"%(self.imgcode, "%05d"))
		cmd = "ffmpeg -y "
		cmd += " -r %d "%(self.framerate)
		cmd += " -i \"%s\" "%(image_pattern)
		cmd += " -codec:v libx265 -filter:v 'fps=%d,format=yuv420p' "%(self.framerate)
		cmd += " -crf %d -preset ultrafast -tune fastdecode -profile:v main -pix_fmt yuv420p "%(self.crf)
		cmd += " \"%s\" "%(self.outfile)
		utils.runCmd(cmd)

	#===============================
	def cloudBase(self, bgcolor):
		base_pattern = numpy.random.uniform(0, 255, (self.height, self.width))
		base_pattern = gaussian_filter(base_pattern, sigma=7)
		if self.randimg is not None:
			base_pattern = (1*self.randimg + base_pattern)/2.
		self.randimg = base_pattern
		im = Image.fromarray(numpy.uint8(base_pattern), mode='L')
		im = im.convert("RGB")
		im = RGBTransform().mix_with(bgcolor, factor=.30).applied_to(im)
		return im

	#===============================
	def make_turbulence(self):
		# Initialize the white noise pattern
		base_pattern = numpy.random.uniform(0,255, (self.height//2, self.width//2))
		# Initialize the output pattern
		turbulence_pattern = numpy.zeros((self.height, self.width))
		# Create cloud pattern
		im_size = min(self.height, self.width)
		power_range = list(range(2, int(numpy.log2(im_size))))
		for i in power_range:
			# Set the size of the quadrant to work on
			subimg_size = 2**i
			# Extract the pixels in the upper left quadrant
			quadrant = base_pattern[:subimg_size, :subimg_size]
			# Up-sample the quadrant to the original image size
			upsampled_pattern = self._resize_array(quadrant, self.width, self.height)
			# Add the new noise pattern to the result
			turbulence_pattern += upsampled_pattern / subimg_size
		# Normalize values
		turbulence_pattern /= turbulence_pattern.max()
		turbulence_pattern *= 255
		#turbulence_pattern /= sum([1 / 2**i for i in power_range])
		im = Image.fromarray(numpy.uint8(turbulence_pattern), mode='L')
		im = im.convert("RGB")
		im = RGBTransform().mix_with(self.bgcolor, factor=.30).applied_to(im)
		return im

	#===============================
	def createCards(self):
		if self.fnt is None:
			self.setType()
		temp_dir = self.temp_dir
		owns_temp = False
		if temp_dir is None:
			temp_dir = tempfile.mkdtemp(prefix="emwy-titlecard-")
			owns_temp = True
		self.numimages = int(round(self.length * self.framerate))
		bgcolor = self.bgcolor
		textcolor = self.textcolor
		rectcolor = self.alterColor(bgcolor, self.defaultshift)
		h = self.h
		w = self.w
		imglist = []
		turbim = self.make_turbulence()
		quiet_mode = self.quiet or utils.is_quiet_mode()
		if quiet_mode:
			iter_range = range(self.numimages)
		else:
			iter_range = tqdm(range(self.numimages))
		for i in iter_range:
			bgcolor = self.alterColor(bgcolor, self.defaultshift)
			textcolor = self.alterColor(textcolor, self.defaultshift)
			h = self.alterInt(h, self.defaultshift)
			w = self.alterInt(w, self.defaultshift)

			#im = origim.copy()
			#cloudim = self.make_turbulence()
			im = self.cloudBase(bgcolor)
			#im = Image.new('RGB', size=(self.width, self.height), color=bgcolor)
			#im = Image.blend(newim, cloudim, 0.6)
			im = Image.blend(im, turbim, 0.3)
			d = ImageDraw.Draw(im)
			rectcolor = self.alterColor(rectcolor, self.defaultshift)
			d.rectangle([0, self.topband, self.width, self.bottomband], fill=rectcolor, outline='black')
			d.text((w,h), self.text, font=self.fnt, fill=textcolor)
			imgname = os.path.join(temp_dir, "%s%05d.png"%(self.imgcode, i))
			im.save(imgname, "PNG")
			imglist.append(imgname)
		sys.stderr.write("\n")
		self.makeMovieFromImages(imglist, temp_dir)
		if owns_temp:
			shutil.rmtree(temp_dir, ignore_errors=True)
		if not quiet_mode:
			print("done")
		return

	#===============================
	def _load_font(self):
		if self.fontfile is not None and os.path.exists(self.fontfile):
			return ImageFont.truetype(self.fontfile, self.size)
		try:
			return ImageFont.truetype("DejaVuSans.ttf", self.size)
		except OSError:
			return ImageFont.load_default()

	#===============================
	def _resize_array(self, array: numpy.ndarray, width: int, height: int) -> numpy.ndarray:
		"""Resize a 2D array to (width, height) using PIL."""
		array_uint8 = numpy.clip(array, 0, 255).astype(numpy.uint8)
		image = Image.fromarray(array_uint8, mode='L')
		image = image.resize((width, height), resample=Image.BICUBIC)
		return numpy.array(image, dtype=numpy.float64)

#===============================
#===============================
if __name__ == '__main__':
	tc = TitleCard()
	tc.setType()
	tc.createCards()
	
