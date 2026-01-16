
import argparse
import os
import lxml.etree
from emwylib.core.project import EmwyProject

#============================================

def parse_args():
	"""
	Parse command-line arguments.
	"""
	parser = argparse.ArgumentParser(description="Export emwy v2 YAML to MLT XML")
	parser.add_argument('-y', '--yaml', dest='yamlfile', required=True,
		help='main yaml file that outlines the processing to do')
	parser.add_argument('-o', '--output', dest='output_file',
		help='output MLT XML file path')
	args = parser.parse_args()
	return args

#============================================

def reduce_fraction(num: int, den: int) -> tuple:
	if den == 0:
		return (num, den)
	a = num
	b = den
	while b != 0:
		a, b = b, a % b
	gcd = a if a != 0 else 1
	return (num // gcd, den // gcd)

#============================================
class MltExporter():
	def __init__(self, yaml_file: str, output_file: str = None):
		self.yaml_file = yaml_file
		self.output_file = output_file or self._default_output_path()
		self.project = EmwyProject(self.yaml_file, output_override=None,
			dry_run=True)
		self.producer_counter = 0
		self.root = None
		self.playlist_nodes = {}

	#============================
	def _default_output_path(self) -> str:
		base, _ = os.path.splitext(self.yaml_file)
		return base + ".mlt"

	#============================
	def export(self) -> None:
		self.root = lxml.etree.Element('mlt')
		self._emit_profile()
		track_list = self._get_track_list()
		for track in track_list:
			playlist_id = track.get('playlist')
			self._emit_playlist(playlist_id)
		self._emit_tractor(track_list)
		self._write_output()

	#============================
	def _emit_profile(self) -> None:
		fps = self.project.profile['fps']
		width = self.project.profile['width']
		height = self.project.profile['height']
		frame_rate_num = fps.numerator
		frame_rate_den = fps.denominator
		(display_num, display_den) = reduce_fraction(width, height)
		profile = lxml.etree.SubElement(self.root, 'profile')
		profile.set('description', 'emwy')
		profile.set('width', str(width))
		profile.set('height', str(height))
		profile.set('progressive', '1')
		profile.set('sample_aspect_num', '1')
		profile.set('sample_aspect_den', '1')
		profile.set('display_aspect_num', str(display_num))
		profile.set('display_aspect_den', str(display_den))
		profile.set('frame_rate_num', str(frame_rate_num))
		profile.set('frame_rate_den', str(frame_rate_den))
		profile.set('colorspace', '709')

	#============================
	def _get_track_list(self) -> list:
		stack = self.project.stack if self.project.stack is not None else {}
		tracks = stack.get('tracks', [])
		if not isinstance(tracks, list) or len(tracks) == 0:
			raise RuntimeError("stack.tracks is required for MLT export")
		base_track = None
		main_track = None
		for track in tracks:
			if track.get('role') == 'base':
				base_track = track
			if track.get('role') == 'main':
				main_track = track
		if base_track is None:
			raise RuntimeError("stack.tracks must include base for MLT export")
		result = [base_track]
		if main_track is not None:
			result.append(main_track)
		return result

	#============================
	def _emit_playlist(self, playlist_id: str) -> None:
		playlist = self.project.playlists.get(playlist_id)
		if playlist is None:
			raise RuntimeError(f"playlist not found: {playlist_id}")
		playlist_elem = lxml.etree.SubElement(self.root, 'playlist')
		playlist_elem.set('id', playlist_id)
		for entry in playlist['entries']:
			self._emit_playlist_entry(playlist_elem, playlist, entry)
		self.playlist_nodes[playlist_id] = playlist_elem

	#============================
	def _emit_playlist_entry(self, playlist_elem, playlist: dict, entry: dict) -> None:
		entry_type = entry['type']
		if entry_type == 'source':
			producer_id = self._emit_source_producer(entry)
			start_frame = entry['in_frame']
			end_frame = entry['out_frame'] - 1
			playlist_entry = lxml.etree.SubElement(playlist_elem, 'entry')
			playlist_entry.set('producer', producer_id)
			playlist_entry.set('in', str(start_frame))
			playlist_entry.set('out', str(end_frame))
			return
		if entry_type == 'blank':
			self._emit_blank_entry(playlist_elem, entry['duration_frames'])
			return
		if entry_type == 'generator':
			self._emit_generator_entry(playlist_elem, playlist, entry)
			return
		raise RuntimeError(f"unsupported playlist entry type: {entry_type}")

	#============================
	def _emit_blank_entry(self, playlist_elem, duration_frames: int) -> None:
		if duration_frames <= 0:
			raise RuntimeError("blank duration must be positive")
		blank_elem = lxml.etree.SubElement(playlist_elem, 'blank')
		blank_elem.set('length', str(duration_frames))

	#============================
	def _emit_generator_entry(self, playlist_elem, playlist: dict, entry: dict) -> None:
		gen_kind = entry.get('kind')
		if playlist['kind'] == 'audio' and gen_kind == 'silence':
			self._emit_blank_entry(playlist_elem, entry['duration_frames'])
			return
		if playlist['kind'] != 'video':
			raise RuntimeError("generator entries are only supported on video playlists")
		if gen_kind not in ('black', 'chapter_card', 'title_card', 'still'):
			raise RuntimeError(f"generator kind not supported for MLT export: {gen_kind}")
		producer_id = self._emit_color_producer(entry['duration_frames'])
		playlist_entry = lxml.etree.SubElement(playlist_elem, 'entry')
		playlist_entry.set('producer', producer_id)
		playlist_entry.set('in', '0')
		playlist_entry.set('out', str(entry['duration_frames'] - 1))

	#============================
	def _emit_source_producer(self, entry: dict) -> str:
		producer_id = self._next_producer_id('source')
		producer = lxml.etree.SubElement(self.root, 'producer')
		producer.set('id', producer_id)
		speed = float(entry.get('speed', 1.0))
		if abs(speed - 1.0) > 0.0001:
			self._set_property(producer, 'mlt_service', 'timewarp')
			resource = f"{speed:.8f}:{entry['asset_file']}"
			self._set_property(producer, 'resource', resource)
			self._set_property(producer, 'warp_speed', f"{speed:.8f}")
		else:
			self._set_property(producer, 'mlt_service', 'avformat')
			self._set_property(producer, 'resource', entry['asset_file'])
		return producer_id

	#============================
	def _emit_color_producer(self, duration_frames: int) -> str:
		producer_id = self._next_producer_id('color')
		producer = lxml.etree.SubElement(self.root, 'producer')
		producer.set('id', producer_id)
		self._set_property(producer, 'mlt_service', 'color')
		self._set_property(producer, 'resource', '#000000')
		self._set_property(producer, 'length', str(duration_frames))
		self._set_property(producer, 'out', str(duration_frames - 1))
		return producer_id

	#============================
	def _emit_tractor(self, track_list: list) -> None:
		tractor = lxml.etree.SubElement(self.root, 'tractor')
		tractor.set('id', 'tractor0')
		self._set_property(tractor, 'emwy:version', '2')
		multitrack = lxml.etree.SubElement(tractor, 'multitrack')
		for track in track_list:
			playlist_id = track.get('playlist')
			track_elem = lxml.etree.SubElement(multitrack, 'track')
			track_elem.set('producer', playlist_id)

	#============================
	def _set_property(self, parent, name: str, value: str) -> None:
		prop = lxml.etree.SubElement(parent, 'property')
		prop.set('name', name)
		prop.text = value

	#============================
	def _next_producer_id(self, prefix: str) -> str:
		self.producer_counter += 1
		return f"{prefix}_{self.producer_counter:04d}"

	#============================
	def _write_output(self) -> None:
		os.makedirs(os.path.dirname(self.output_file) or '.', exist_ok=True)
		tree = lxml.etree.ElementTree(self.root)
		tree.write(self.output_file, encoding='utf-8', xml_declaration=True)

#============================================
#============================================
#============================================


def main():
	args = parse_args()
	exporter = MltExporter(args.yamlfile, args.output_file)
	exporter.export()
	print(f"wrote {exporter.output_file}")


if __name__ == '__main__':
	main()
