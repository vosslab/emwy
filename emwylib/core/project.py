#!/usr/bin/env python3

import shutil
from emwylib.core import utils
from emwylib.core.loader import ProjectLoader
from emwylib.core.renderer import Renderer
from emwylib.core.timeline import TimelinePlanner

#============================================

class EmwyProject():
	def __init__(self, yaml_file: str, output_override: str = None,
		dry_run: bool = False, keep_temp: bool = False, cache_dir: str = None):
		loader = ProjectLoader(yaml_file, output_override=output_override,
			dry_run=dry_run, keep_temp=keep_temp, cache_dir=cache_dir)
		self._project = loader.load()
		self._timeline = TimelinePlanner(self._project)
		self._timeline.apply_paired_audio()
		self._renderer = Renderer(self._project)
		self._sync_public_fields()

	#============================
	def _sync_public_fields(self) -> None:
		self.yaml_file = self._project.yaml_file
		self.output_override = self._project.output_override
		self.dry_run = self._project.dry_run
		self.keep_temp = self._project.keep_temp
		self.cache_dir = self._project.cache_dir
		self.cache_dir_created = self._project.cache_dir_created
		self.data = self._project.data
		self.profile = self._project.profile
		self.defaults = self._project.defaults
		self.assets = self._project.assets
		self.playlists = self._project.playlists
		self.stack = self._project.stack
		self.output = self._project.output

	#============================
	def run(self) -> None:
		self._timeline.validate_timeline()
		if self.dry_run:
			if not utils.is_quiet_mode():
				print("dry run: validation complete")
			return
		self._renderer.render()
		if not self.keep_temp and self._project.cache_dir_created:
			shutil.rmtree(self._project.cache_dir, ignore_errors=True)

	#============================
	def validate(self) -> None:
		self._timeline.validate_timeline()
