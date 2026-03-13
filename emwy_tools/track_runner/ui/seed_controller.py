"""Seed collection controller for track runner annotation.

Manages the Seed mode annotation workflow with keyboard shortcuts and
mouse drawing for seed collection.
"""

# Standard Library
# (none)

# PIP3 modules
import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

# local repo modules
import ui.base_controller as base_controller_module

BaseAnnotationController = base_controller_module.BaseAnnotationController

#============================================


class SeedController(BaseAnnotationController):
	"""Manages the Seed mode annotation workflow.

	Handles keyboard shortcuts and mouse drawing for collect_seeds().
	"""

	def __init__(
		self,
		seed_frame_indices: list,
		reader: object,
		fps: float,
		config: dict,
		all_seeds: list,
		save_callback: object,
		pass_number: int = 1,
		mode_str: str = "initial",
		predictions: dict | None = None,
		return_callback: object = None,
		start_frame: int | None = None,
	) -> None:
		"""Initialize the SeedController.

		Args:
			seed_frame_indices: List of frame indices to collect seeds at.
			reader: Frame reader instance with read_frame(idx) method.
			fps: Frames per second of the video.
			config: Configuration dict.
			all_seeds: List of existing seeds to preserve.
			save_callback: Callable(seeds_list) to save seeds incrementally.
			pass_number: Which collection pass this is (default 1).
			mode_str: Seed collection mode string (default "initial").
			predictions: Optional dict mapping frame_index to prediction dicts.
			return_callback: Optional callable(new_seeds) to return to edit mode.
			start_frame: Optional frame index to seek to on first activate.
		"""
		super().__init__(
			reader=reader,
			fps=fps,
			config=config,
			save_callback=save_callback,
			predictions=predictions,
		)

		self._seed_frame_indices = seed_frame_indices
		self._all_seeds = all_seeds
		self._pass_number = pass_number
		self._mode_str = mode_str
		self._return_callback = return_callback
		self._start_frame = start_frame
		self._start_frame_used = False

		self._list_idx = 0
		self._current_frame = seed_frame_indices[0] if seed_frame_indices else 0
		self._new_seeds: list = []

		# scrub step in seconds, adjustable via [ and ]
		self._scrub_step_s: float = 0.2
		self._step_value_label: QLabel | None = None

		# auto-seed suggestion state
		self._suggestion: dict | None = None
		self._detector: object = None
		self._detection_cache: dict = {}

	#============================================

	def _build_toolbar(self) -> QWidget:
		"""Build the toolbar widget with nav and draw mode buttons.

		Returns:
			QWidget containing prev/next and draw mode buttons.
		"""
		widget = QWidget()
		layout = QHBoxLayout(widget)
		layout.setContentsMargins(4, 0, 4, 0)
		layout.setSpacing(4)

		# Navigation buttons
		btn_prev = QPushButton("<  Prev")
		btn_prev.setToolTip("Previous frame (LEFT or Shift+LEFT when zoomed)")
		btn_prev.clicked.connect(self._on_prev)
		layout.addWidget(btn_prev)

		btn_next = QPushButton("Next  >")
		btn_next.setToolTip("Next frame (RIGHT or Shift+RIGHT when zoomed)")
		btn_next.clicked.connect(self._on_next)
		layout.addWidget(btn_next)

		btn_skip = QPushButton("Skip")
		btn_skip.setToolTip("Skip this frame (SPACE)")
		btn_skip.clicked.connect(self._on_skip)
		layout.addWidget(btn_skip)

		# Step size control: [ - ] N [ + ]
		layout.addSpacing(8)
		step_label = QLabel("Step:")
		layout.addWidget(step_label)
		btn_step_down = QPushButton("[")
		btn_step_down.setFixedWidth(24)
		btn_step_down.setToolTip("Decrease step size ([)")
		btn_step_down.clicked.connect(self._decrease_step)
		layout.addWidget(btn_step_down)
		self._step_value_label = QLabel(self._step_label())
		layout.addWidget(self._step_value_label)
		btn_step_up = QPushButton("]")
		btn_step_up.setFixedWidth(24)
		btn_step_up.setToolTip("Increase step size (])")
		btn_step_up.clicked.connect(self._increase_step)
		layout.addWidget(btn_step_up)

		# Separator space
		layout.addSpacing(12)

		# Draw mode toggle buttons (checkable for visual state)
		self._btn_partial = QPushButton("Partial")
		self._btn_partial.setCheckable(True)
		self._btn_partial.setToolTip("Toggle partial draw mode (P)")
		self._btn_partial.clicked.connect(self._on_partial_toggle)
		layout.addWidget(self._btn_partial)

		self._btn_approx = QPushButton("Approx")
		self._btn_approx.setCheckable(True)
		self._btn_approx.setToolTip("Toggle approx/obstruction draw mode (A)")
		self._btn_approx.clicked.connect(self._on_approx_toggle)
		layout.addWidget(self._btn_approx)

		return widget

	#============================================

	def _on_activated(self) -> None:
		"""Show keybinding instructions and load the first frame."""
		# Show keybinding instructions in the status bar
		self._window.statusBar().showMessage(self._get_default_status_text())

		# One-shot seek to start_frame if provided
		if self._start_frame is not None and not self._start_frame_used:
			self._start_frame_used = True
			self._current_frame = self._start_frame

		# Load and display the first frame
		self._refresh_frame()
		self._update_scale_bar()

	#============================================

	def _on_deactivated(self) -> None:
		"""Clean up seed-specific state (counters, etc)."""
		# No seed-specific cleanup needed beyond what base handles
		pass

	#============================================

	def _get_default_status_text(self) -> str:
		"""Short mode summary for the status bar.

		Returns:
			String with mode summary.
		"""
		if self._return_callback is not None:
			text = "Seed mode - add seeds (ESC to return)"
		else:
			text = "Seed mode - draw torso box"
		return text

	#============================================

	def _get_keybinding_hints(self) -> str:
		"""Keybinding hints for the key hint overlay.

		Returns:
			String with keybinding hints.
		"""
		hints = (
			"LR=scrub  []=step  SPACE=skip  N=not-in-frame  "
			"F=avg  P=part  A=approx  V=hide preds  Z=zoom"
		)
		# add ENTER hint if suggestion available
		if self._suggestion is not None:
			suggestion_idx = self._suggestion.get(
				"suggestion_index"
			)
			if suggestion_idx is not None:
				hints += "  ENTER=accept"
			# add number keys hint if candidates available
			candidates = self._suggestion.get("candidates", [])
			if len(candidates) > 1:
				hints += "  1-9=select"
		if self._return_callback is not None:
			hints += "  ESC=return"
		else:
			hints += "  ESC=done"
		return hints

	#============================================

	def _get_mode_name(self) -> str:
		"""Mode name for display.

		Returns:
			String "seed".
		"""
		return "seed"

	#============================================

	def _refresh_frame(self) -> None:
		"""Load and display the current frame."""
		frame = self._reader.read_frame(self._current_frame)
		if frame is not None:
			self._window.set_frame(frame)
			self._current_bgr = frame
			self._update_fwd_bwd_overlays()
			self._update_scale_bar()
			# Recenter on prediction center when zoomed in
			self._recenter_on_prediction()
			# compute auto-seed suggestion for this frame
			self._compute_suggestion()

		# update progress bar
		self._window.set_progress(
			self._list_idx + 1, len(self._seed_frame_indices)
		)

		# update title bar with current state
		self._refresh_frame_title()

	#============================================

	def _get_detector(self) -> object | None:
		"""Get or create a YOLO detector instance.

		Lazy-loads the detector on first call. Returns None if YOLO
		weights are not available.

		Returns:
			YoloDetector instance or None if weights unavailable.
		"""
		if self._detector is None:
			# lazy import to avoid circular dependencies
			import tr_detection as detection_module

			# ensure weights exist before creating detector
			weights_path = (
				detection_module.ensure_yolo_weights()
			)
			if not weights_path:
				# weights unavailable, silently degrade
				return None

			# create detector directly without create_detector()
			# to avoid config structure issues
			self._detector = detection_module.YoloDetector(
				weights_path,
				confidence_threshold=0.25,
				nms_threshold=0.45,
			)
		return self._detector

	#============================================

	def _compute_suggestion(self) -> None:
		"""Compute and store auto-seed suggestion for current frame.

		Runs YOLO detection and calls suggest_seed_candidates().
		Results cached per frame. Updates self._suggestion and
		redraws frame overlay.
		"""
		# check cache first
		if self._current_frame in self._detection_cache:
			self._suggestion = self._detection_cache[self._current_frame]
			return

		# try to get detector
		detector = self._get_detector()
		if detector is None or self._current_bgr is None:
			# detector unavailable, no suggestions
			self._suggestion = {
				"candidates": [],
				"suggestion_index": None,
				"mode": "none",
				"scores": None,
			}
			self._detection_cache[self._current_frame] = self._suggestion
			return

		# run YOLO detection on current frame
		try:
			detections = detector.detect(self._current_bgr)
		except (RuntimeError, cv2.error):
			# ONNX inference or OpenCV DNN failure, no suggestions
			self._suggestion = {
				"candidates": [],
				"suggestion_index": None,
				"mode": "none",
				"scores": None,
			}
			self._detection_cache[self._current_frame] = self._suggestion
			return

		# import seeding module for suggestion function
		import seeding as seeding_module

		# get confirmed seeds from all_seeds + new_seeds
		confirmed_seeds = self._all_seeds + self._new_seeds

		# compute suggestion
		suggestion = seeding_module.suggest_seed_candidates(
			self._current_bgr,
			detections,
			confirmed_seeds,
			self._current_frame,
		)
		self._suggestion = suggestion
		self._detection_cache[self._current_frame] = suggestion

	#============================================

	def _draw_candidate_overlays(self, frame: object) -> None:
		"""Draw numbered candidate boxes on the frame overlay.

		Draws all candidates as rectangles with numbers 1-9.
		The suggested candidate (if any) uses thicker/brighter color.

		Args:
			frame: Frame viewer object with draw_rectangle/draw_text.
		"""
		if self._suggestion is None:
			return

		candidates = self._suggestion.get("candidates", [])
		suggestion_idx = self._suggestion.get("suggestion_index")

		# colors: green for suggested, cyan for others
		suggested_color = (0, 255, 0)  # bright green
		other_color = (255, 255, 0)  # cyan

		for idx, candidate in enumerate(candidates):
			if idx >= 9:
				# limit to 9 candidates (1-9 keys)
				break

			bbox = candidate["bbox"]
			x, y, w, h = bbox
			x2 = x + w
			y2 = y + h

			is_suggested = (idx == suggestion_idx)
			color = suggested_color if is_suggested else other_color
			thickness = 3 if is_suggested else 1

			# draw rectangle
			frame.draw_rectangle(
				(x, y), (x2, y2), color, thickness
			)

			# draw number label (1-9) at top-left of bbox
			label_text = str(idx + 1)
			frame.draw_text(
				label_text, (x + 5, y + 20), color
			)

	#============================================

	def _refresh_frame_title(self) -> str:
		"""Update window title with frame, step, zoom, and interval quality info."""
		step_frames = max(1, int(round(self._fps * self._scrub_step_s)))
		zoom = self._window.get_frame_view().get_zoom_factor()
		title = (
			f"Seed {self._list_idx + 1}/{len(self._seed_frame_indices)} | "
			f"Frame {self._current_frame} | "
			f"Step {step_frames}f | "
			f"Zoom {zoom:.1f}x"
		)
		# append interval quality info from predictions if available
		quality_text = self._get_interval_quality_text()
		if quality_text:
			title += f" | {quality_text}"
		self._window.setWindowTitle(title)

	#============================================

	def _get_interval_quality_text(self) -> str:
		"""Build a short quality string from the current frame's interval info.

		Returns:
			String like "HIGH: agree=0.12 margin=0.08 (FWD/BWD diverge)"
			or empty string if no info is available.
		"""
		if self._predictions is None:
			return ""
		preds = self._predictions.get(self._current_frame)
		if preds is None:
			return ""
		info = preds.get("interval_info")
		if info is None:
			return ""

		severity = info["severity"].upper()
		agreement = info["agreement"]
		margin = info["margin"]
		# start with severity and key scores
		text = f"{severity}: agree={agreement:.2f} margin={margin:.2f}"
		# append short failure reasons if present
		reasons = info.get("reasons", [])
		if reasons:
			# use short labels: strip common prefixes for brevity
			short_reasons = [r.replace("likely_", "").replace("_", " ") for r in reasons]
			text += f" ({', '.join(short_reasons)})"
		return text

	#============================================

	def _recenter_on_prediction(self) -> None:
		"""Recenter the view on the prediction center when zoomed in."""
		frame_view = self._window.get_frame_view()
		zoom = frame_view.get_zoom_factor()
		if zoom <= 1.05:
			return
		center = self._get_prediction_center()
		if center is not None:
			frame_view.set_zoom(zoom, center[0], center[1])

	#============================================

	def handle_key_press(self, key: int, modifiers: object = None) -> bool:
		"""Handle keyboard events.

		Args:
			key: Qt key code.
			modifiers: Qt keyboard modifiers (for detecting Shift, etc.).

		Returns:
			True if event was handled.
		"""
		# Check for Shift modifier on arrow keys for frame advance
		shift_held = False
		if modifiers is not None:
			shift_held = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

		# Common keys (ESC/Q, P, A, Z)
		result = self._handle_common_key(key, modifiers)
		if result is not None:
			return result

		# ENTER/RETURN: accept current suggestion if available
		if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
			self._accept_suggestion_if_available()
			return True
		# number keys 1-9: select candidate by index
		elif key >= Qt.Key.Key_1 and key <= Qt.Key.Key_9:
			candidate_idx = int(key) - int(Qt.Key.Key_1)
			self._accept_candidate(candidate_idx)
			return True
		elif key == Qt.Key.Key_Space:
			self._on_skip()
			return True
		elif key == Qt.Key.Key_Left:
			mult = self._step_multiplier(modifiers)
			is_zoomed = self._window.get_frame_view().get_zoom_factor() > 1.05
			if shift_held or not is_zoomed:
				self._on_prev(mult)
				return True
			return False
		elif key == Qt.Key.Key_Right:
			mult = self._step_multiplier(modifiers)
			is_zoomed = self._window.get_frame_view().get_zoom_factor() > 1.05
			if shift_held or not is_zoomed:
				self._on_next(mult)
				return True
			return False
		elif key == Qt.Key.Key_BracketLeft:
			self._decrease_step()
			return True
		elif key == Qt.Key.Key_BracketRight:
			self._increase_step()
			return True
		elif key == Qt.Key.Key_N:
			self._on_not_in_frame()
			return True
		elif key == Qt.Key.Key_F:
			self._on_fwd_bwd_avg()
			return True

		return False

	#============================================

	def _accept_suggestion_if_available(self) -> None:
		"""Accept current suggestion if available.

		Calls _accept_candidate() with the suggestion_index if
		suggestion_index is not None.
		"""
		if self._suggestion is None:
			return
		suggestion_idx = self._suggestion.get("suggestion_index")
		if suggestion_idx is not None:
			self._accept_candidate(suggestion_idx)

	#============================================

	def _accept_candidate(self, candidate_idx: int) -> None:
		"""Accept a candidate from suggestion and create a seed.

		Args:
			candidate_idx: Index into candidates list (0-based).
		"""
		if self._suggestion is None:
			return
		candidates = self._suggestion.get("candidates", [])
		if candidate_idx < 0 or candidate_idx >= len(candidates):
			return

		candidate = candidates[candidate_idx]
		# check for duplicate seed at this frame first
		for seed in self._all_seeds:
			if int(seed["frame_index"]) == self._current_frame:
				if self._window is not None:
					self._window.statusBar().showMessage(
						"seed already exists at this frame"
					)
				return
		for seed in self._new_seeds:
			if int(seed["frame_index"]) == self._current_frame:
				if self._window is not None:
					self._window.statusBar().showMessage(
						"seed already exists at this frame"
					)
				return

		# extract torso_box and compute jersey color
		torso_box = candidate["torso_box"]
		import seeding as seeding_module

		jersey_hsv = seeding_module.extract_jersey_color(
			self._current_bgr, torso_box
		)
		# use candidate's histogram if available, or extract new one
		hist = candidate.get("histogram")
		if hist is None:
			hist = seeding_module.extract_color_histogram(
				self._current_bgr, torso_box
			)

		# build seed dict
		seed = seeding_module._build_seed_dict(
			self._current_frame,
			self._current_frame / self._fps,
			torso_box,
			jersey_hsv,
			self._pass_number,
			self._mode_str,
			histogram=hist,
		)
		self._commit_seed(seed)
		self._advance()

	#============================================

	def _on_box_drawn(self, box: list) -> None:
		"""Process a drawn box.

		Args:
			box: Box as [x, y, w, h].
		"""
		# Check for duplicate seed at this frame
		for seed in self._all_seeds:
			if int(seed["frame_index"]) == self._current_frame:
				print(f"  seed already exists at frame {self._current_frame}")
				if self._window is not None:
					self._window.statusBar().showMessage(
						"seed already exists at this frame"
					)
				return
		for seed in self._new_seeds:
			if int(seed["frame_index"]) == self._current_frame:
				print(f"  seed already exists at frame {self._current_frame}")
				if self._window is not None:
					self._window.statusBar().showMessage(
						"seed already exists at this frame"
					)
				return

		# Import here to avoid circular dependency
		import seeding as seeding_module

		if self._approx_mode:
			self._approx_mode = False
			self._update_mode_badge()
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			tx, ty, tw, th = norm_box
			cx = float(tx + tw / 2.0)
			cy = float(ty + th / 2.0)
			seed = {
				"frame_index": self._current_frame,
				"frame": self._current_frame,
				"time_s": round(self._current_frame / self._fps, 3),
				"status": "approximate",
				"torso_box": norm_box,
				"cx": cx,
				"cy": cy,
				"w": float(tw),
				"h": float(th),
				"conf": None,
				"pass": self._pass_number,
				"source": "human",
				"mode": self._mode_str,
			}
			self._commit_seed(seed)
			self._advance()
			return
		elif self._partial_mode:
			self._partial_mode = False
			self._update_mode_badge()
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			jersey_hsv = seeding_module.extract_jersey_color(
				self._current_bgr, norm_box
			)
			hist = seeding_module.extract_color_histogram(
				self._current_bgr, norm_box
			)
			seed = seeding_module._build_seed_dict(
				self._current_frame,
				self._current_frame / self._fps,
				norm_box,
				jersey_hsv,
				self._pass_number,
				self._mode_str,
				histogram=hist,
			)
			seed["status"] = "partial"
			self._commit_seed(seed)
			self._advance()
		else:
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			jersey_hsv = seeding_module.extract_jersey_color(
				self._current_bgr, norm_box
			)
			hist = seeding_module.extract_color_histogram(
				self._current_bgr, norm_box
			)
			seed = seeding_module._build_seed_dict(
				self._current_frame,
				self._current_frame / self._fps,
				norm_box,
				jersey_hsv,
				self._pass_number,
				self._mode_str,
				histogram=hist,
			)
			self._commit_seed(seed)
			self._advance()

	#============================================

	def _commit_seed(self, seed: dict) -> None:
		"""Save a seed and invoke the save callback.

		Args:
			seed: Seed dict to save.
		"""
		self._new_seeds.append(seed)
		if self._save_callback is not None:
			self._save_callback(self._all_seeds + self._new_seeds)

	#============================================

	def _on_quit(self) -> None:
		"""Handle quit request."""
		self._done = True
		print(f"  user quit at frame {self._current_frame} "
			f"({self._list_idx + 1}/{len(self._seed_frame_indices)})")
		if self._return_callback is not None:
			# Return to edit mode with collected seeds
			self._return_callback(self._new_seeds)
			return
		if self._window is not None:
			self._window.close()

	#============================================

	def _on_skip(self) -> None:
		"""Skip current frame."""
		self._partial_mode = False
		self._advance()

	#============================================

	def _step_multiplier(self, modifiers: object) -> int:
		"""Compute a temporary step multiplier from held modifier keys.

		Alt multiplies by 5. Shift is NOT used here because it already
		means "force scrub when zoomed".

		Args:
			modifiers: Qt keyboard modifiers.

		Returns:
			Integer multiplier (1 or 5).
		"""
		mult = 1
		if modifiers is not None:
			if bool(modifiers & Qt.KeyboardModifier.AltModifier):
				mult = 5
		return mult

	#============================================

	def _on_prev(self, multiplier: int = 1) -> None:
		"""Scrub backward by the current step size times multiplier.

		Args:
			multiplier: Temporary speed multiplier (default 1).
		"""
		scrub_step = max(1, int(round(self._fps * self._scrub_step_s)))
		self._current_frame = max(0, self._current_frame - scrub_step * multiplier)
		self._refresh_frame()

	#============================================

	def _on_next(self, multiplier: int = 1) -> None:
		"""Scrub forward by the current step size times multiplier.

		Args:
			multiplier: Temporary speed multiplier (default 1).
		"""
		scrub_step = max(1, int(round(self._fps * self._scrub_step_s)))
		# Use last seed frame as upper bound for scrubbing
		max_frame = self._seed_frame_indices[-1] if self._seed_frame_indices else 0
		self._current_frame = min(max_frame, self._current_frame + scrub_step * multiplier)
		self._refresh_frame()

	#============================================

	# available step sizes in seconds, cycled with Shift+LR
	_STEP_SIZES = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0]

	def _step_label(self) -> str:
		"""Format the current step size for display.

		Returns:
			String like "0.2s (6f)" showing seconds and frames.
		"""
		frames = max(1, int(round(self._fps * self._scrub_step_s)))
		label = f"{self._scrub_step_s}s ({frames}f)"
		return label

	#============================================

	def _increase_step(self) -> None:
		"""Increase the scrub step to the next larger preset."""
		for s in self._STEP_SIZES:
			if s > self._scrub_step_s + 0.001:
				self._scrub_step_s = s
				break
		self._update_step_display()

	#============================================

	def _decrease_step(self) -> None:
		"""Decrease the scrub step to the next smaller preset."""
		for s in reversed(self._STEP_SIZES):
			if s < self._scrub_step_s - 0.001:
				self._scrub_step_s = s
				break
		self._update_step_display()

	#============================================

	def _update_step_display(self) -> None:
		"""Update the step label in the toolbar and window title."""
		if self._step_value_label is not None:
			self._step_value_label.setText(self._step_label())
		# refresh window title to show new step size
		if self._window is not None:
			self._refresh_frame_title()

	#============================================

	def _on_not_in_frame(self) -> None:
		"""Mark runner as not in frame."""
		seed = {
			"frame_index": self._current_frame,
			"frame": self._current_frame,
			"time_s": round(self._current_frame / self._fps, 3),
			"status": "not_in_frame",
			"conf": None,
			"pass": self._pass_number,
			"source": "human",
			"mode": self._mode_str,
		}
		self._commit_seed(seed)
		self._advance()

	#============================================

	def _on_fwd_bwd_avg(self) -> None:
		"""Auto-accept average of FWD/BWD predictions if overlap sufficient."""
		if self._predictions is None:
			return

		preds = self._predictions.get(self._current_frame)
		if preds is None:
			return

		fwd = preds.get("forward")
		bwd = preds.get("backward")
		if fwd is None or bwd is None:
			return

		# Compute FWD and BWD boxes
		fwd_cx = float(fwd["cx"])
		fwd_cy = float(fwd["cy"])
		fwd_w = float(fwd["w"])
		fwd_h = float(fwd["h"])
		bwd_cx = float(bwd["cx"])
		bwd_cy = float(bwd["cy"])
		bwd_w = float(bwd["w"])
		bwd_h = float(bwd["h"])

		# Compute intersection area
		f_x1 = fwd_cx - fwd_w / 2.0
		f_y1 = fwd_cy - fwd_h / 2.0
		f_x2 = fwd_cx + fwd_w / 2.0
		f_y2 = fwd_cy + fwd_h / 2.0
		b_x1 = bwd_cx - bwd_w / 2.0
		b_y1 = bwd_cy - bwd_h / 2.0
		b_x2 = bwd_cx + bwd_w / 2.0
		b_y2 = bwd_cy + bwd_h / 2.0
		inter_w = max(0.0, min(f_x2, b_x2) - max(f_x1, b_x1))
		inter_h = max(0.0, min(f_y2, b_y2) - max(f_y1, b_y1))
		intersection = inter_w * inter_h
		fwd_area = fwd_w * fwd_h
		bwd_area = bwd_w * bwd_h
		total = fwd_area + bwd_area

		# Check overlap ratio
		if total <= 0 or intersection / total < 0.1:
			return

		# Compute average box
		avg_cx = (fwd_cx + bwd_cx) / 2.0
		avg_cy = (fwd_cy + bwd_cy) / 2.0
		avg_w = (fwd_w + bwd_w) / 2.0
		avg_h = (fwd_h + bwd_h) / 2.0
		avg_x = int(avg_cx - avg_w / 2.0)
		avg_y = int(avg_cy - avg_h / 2.0)

		box = [avg_x, avg_y, int(avg_w), int(avg_h)]
		self._on_box_drawn(box)

	#============================================

	def _advance(self) -> None:
		"""Advance to next seed frame."""
		self._list_idx += 1
		if self._list_idx >= len(self._seed_frame_indices):
			self._on_quit()
			return
		self._current_frame = self._seed_frame_indices[self._list_idx]
		self._refresh_frame()

	#============================================

	def get_final_seeds(self) -> list:
		"""Get all seeds collected.

		Returns:
			List of all seeds (existing + new).
		"""
		return self._all_seeds + self._new_seeds

	#============================================

	def get_new_seeds(self) -> list:
		"""Get only newly collected seeds.

		Returns:
			List of newly collected seeds.
		"""
		return self._new_seeds
