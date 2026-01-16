
"""
Render a single title card video for quick manual validation.
"""

# Standard Library
import argparse
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

from emwylib.core.project import EmwyProject

#============================================

REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "mkvmerge", "sox")

#============================================

def ensure_tools() -> None:
	missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
	if missing:
		raise RuntimeError(f"missing tools: {', '.join(missing)}")

#============================================

def parse_args():
	parser = argparse.ArgumentParser(
		description="Render a single title card video for quick validation"
	)
	parser.add_argument(
		"-o", "--output",
		dest="output_path",
		default=os.path.join(os.getcwd(), "titlecard.mkv"),
		help="output video path (default: ./titlecard.mkv)"
	)
	parser.add_argument(
		"--width",
		type=int,
		default=640,
		help="output width in pixels (default: 640)"
	)
	parser.add_argument(
		"--height",
		type=int,
		default=360,
		help="output height in pixels (default: 360)"
	)
	parser.add_argument(
		"--font-size",
		type=int,
		default=None,
		help="font size in pixels (default: scaled from height)"
	)
	parser.add_argument(
		"--font-file",
		type=str,
		default=None,
		help="path to a TTF/OTF font file"
	)
	parser.add_argument(
		"--title",
		type=str,
		default="Title Card",
		help="title text to render"
	)
	return parser.parse_args()

#============================================

def main() -> None:
	ensure_tools()
	args = parse_args()
	if args.width <= 0 or args.height <= 0:
		raise RuntimeError("width and height must be positive")
	if args.font_size is None:
		args.font_size = max(18, int(round(args.height * 0.089)))
	with tempfile.TemporaryDirectory() as temp_dir:
		output_path = args.output_path
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		lines = []
		lines.append("emwy: 2")
		lines.append("")
		lines.append("profile:")
		lines.append("  fps: 25")
		lines.append(f"  resolution: [{args.width}, {args.height}]")
		lines.append("  audio: {sample_rate: 48000, channels: mono}")
		lines.append("")
		lines.append("assets:")
		lines.append("  cards:")
		lines.append("    title_style:")
		lines.append("      kind: chapter_card_style")
		lines.append(f"      font_size: {args.font_size}")
		if args.font_file is not None:
			lines.append(f"      font_file: \"{args.font_file}\"")
		lines.append("      text_color: \"#ffffff\"")
		lines.append("      background:")
		lines.append("        kind: gradient")
		lines.append("        from: \"#101820\"")
		lines.append("        to: \"#2b5876\"")
		lines.append("        direction: vertical")
		lines.append("")
		lines.append("timeline:")
		lines.append("  segments:")
		lines.append("    - generator:")
		lines.append("        kind: title_card")
		lines.append(f"        title: \"{args.title}\"")
		lines.append("        duration: \"00:03.0\"")
		lines.append("        style: title_style")
		lines.append("        fill_missing: {audio: silence}")
		lines.append("")
		lines.append("output:")
		lines.append(f"  file: \"{output_path}\"")
		with open(yaml_path, "w") as handle:
			handle.write("\n".join(lines))
			handle.write("\n")
		project = EmwyProject(yaml_path)
		project.run()
		print(f"rendered: {output_path}")

#============================================

if __name__ == "__main__":
	main()
