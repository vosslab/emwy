
"""
Font discovery helpers for tests.
"""

# Standard Library
import os

#============================================

def find_system_ttf() -> str:
	"""
	Find a system TTF/OTF font path for macOS/Linux tests.
	"""
	candidates = [
		"/Library/Fonts/Arial.ttf",
		"/Library/Fonts/Helvetica.ttf",
		"/Library/Fonts/Times New Roman.ttf",
		"/System/Library/Fonts/Supplemental/Arial.ttf",
		"/System/Library/Fonts/Supplemental/Helvetica.ttf",
		"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
		"/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
		"/usr/share/fonts/truetype/freefont/FreeSans.ttf",
		"/usr/local/share/fonts/DejaVuSans.ttf",
	]
	for path in candidates:
		if os.path.exists(path):
			return path
	search_dirs = [
		"/Library/Fonts",
		"/System/Library/Fonts",
		"/usr/share/fonts",
		"/usr/local/share/fonts",
	]
	for base in search_dirs:
		if not os.path.isdir(base):
			continue
		for root, dirs, files in os.walk(base):
			rel = os.path.relpath(root, base)
			depth = 0 if rel == "." else rel.count(os.sep) + 1
			if depth >= 3:
				dirs[:] = []
			dirs[:] = sorted(dirs)
			for name in sorted(files):
				lower = name.lower()
				if lower.endswith((".ttf", ".otf")):
					return os.path.join(root, name)
	return None
