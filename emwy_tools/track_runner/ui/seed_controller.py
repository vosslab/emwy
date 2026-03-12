"""Seed collection controller for track runner annotation.

Manages the Seed mode annotation workflow with keyboard shortcuts and
mouse drawing for seed collection.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtCore import QObject, Qt, QTimer
import numpy

# local repo modules
import ui.overlay_items as overlay_items_module

PreviewBoxItem = overlay_items_module.PreviewBoxItem
RectItem = overlay_items_module.RectItem
ScaleBarItem = overlay_items_module.ScaleBarItem

#============================================


class SeedController(QObject):
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
		"""
		super().__init__()

		self._seed_frame_indices = seed_frame_indices
		self._reader = reader
		self._fps = fps
		self._config = config
		self._all_seeds = all_seeds
		self._save_callback = save_callback
		self._pass_number = pass_number
		self._mode_str = mode_str
		self._predictions = predictions

		self._list_idx = 0
		self._current_frame = seed_frame_indices[0] if seed_frame_indices else 0
		self._new_seeds: list = []
		self._window: object = None
		self._drawing: bool = False
		self._drag_start: tuple | None = None
		self._drag_current: tuple | None = None
		self._preview_item: object = None
		self._fwd_item: object = None
		self._bwd_item: object = None
		self._done: bool = False
		self._partial_mode: bool = False
		self._approx_mode: bool = False
		self._current_bgr: numpy.ndarray | None = None
		self._scale_bar_item: object = None

	#============================================

	def activate(self, window: object) -> None:
		"""Activate the controller and connect to window events.

		Args:
			window: AnnotationWindow instance.
		"""
		self._window = window

		# Install event filter for keyboard and mouse events
		self._window.installEventFilter(self)
		viewport = self._window.get_frame_view().viewport()
		viewport.installEventFilter(self)

		# Add scale bar item to scene
		scene = self._window.get_frame_view().scene()
		self._scale_bar_item = ScaleBarItem()
		scene.addItem(self._scale_bar_item)

		# Load and display the first frame
		self._refresh_frame()
		self._update_scale_bar()

	#============================================

	def deactivate(self) -> None:
		"""Deactivate the controller and disconnect from window events."""
		if self._window is not None:
			self._window.removeEventFilter(self)
			viewport = self._window.get_frame_view().viewport()
			viewport.removeEventFilter(self)

		# Clear overlay items
		if self._window is not None:
			scene = self._window.get_frame_view().scene()
			if self._fwd_item is not None:
				scene.removeItem(self._fwd_item)
				self._fwd_item = None
			if self._bwd_item is not None:
				scene.removeItem(self._bwd_item)
				self._bwd_item = None
			if self._preview_item is not None:
				scene.removeItem(self._preview_item)
				self._preview_item = None
			if self._scale_bar_item is not None:
				scene.removeItem(self._scale_bar_item)
				self._scale_bar_item = None

	#============================================

	def eventFilter(self, obj: object, event: object) -> bool:
		"""Handle window and viewport events.

		Args:
			obj: Object that received the event.
			event: Event instance.

		Returns:
			True if event was handled, False otherwise.
		"""
		# Import QEvent here to avoid circular dependency
		from PySide6.QtCore import QEvent as QEventType
		from PySide6.QtGui import QMouseEvent

		if event.type() == QEventType.Type.KeyPress:
			key = event.key()
			if self.handle_key_press(key):
				return True
		elif event.type() == QEventType.Type.MouseButtonPress:
			if isinstance(event, QMouseEvent):
				pos = event.position()
				sx, sy = self._window.get_frame_view().map_to_scene(
					int(pos.x()), int(pos.y())
				)
				self.handle_mouse_press(sx, sy)
				return True
		elif event.type() == QEventType.Type.MouseMove:
			if isinstance(event, QMouseEvent):
				pos = event.position()
				sx, sy = self._window.get_frame_view().map_to_scene(
					int(pos.x()), int(pos.y())
				)
				self.handle_mouse_move(sx, sy)
				return True
		elif event.type() == QEventType.Type.MouseButtonRelease:
			if isinstance(event, QMouseEvent):
				pos = event.position()
				sx, sy = self._window.get_frame_view().map_to_scene(
					int(pos.x()), int(pos.y())
				)
				self.handle_mouse_release(sx, sy)
				return True
		elif event.type() == QEventType.Type.Wheel:
			# Update scale bar after zoom changes
			QTimer.singleShot(0, self._update_scale_bar)
			return False

		return super().eventFilter(obj, event)

	#============================================

	def _refresh_frame(self) -> None:
		"""Load and display the current frame."""
		frame = self._reader.read_frame(self._current_frame)
		if frame is not None:
			self._window.set_frame(frame)
			self._current_bgr = frame
			self._update_fwd_bwd_overlays()
			self._update_scale_bar()

		# Print progress
		progress_msg = (
			f"  seed {self._list_idx + 1}/{len(self._seed_frame_indices)}  "
			f"frame {self._current_frame}"
		)
		print(progress_msg)

	#============================================

	def _update_fwd_bwd_overlays(self) -> None:
		"""Update FWD/BWD prediction overlays."""
		scene = self._window.get_frame_view().scene()

		# Remove old overlays
		if self._fwd_item is not None:
			scene.removeItem(self._fwd_item)
			self._fwd_item = None
		if self._bwd_item is not None:
			scene.removeItem(self._bwd_item)
			self._bwd_item = None

		# Return early if no predictions
		if self._predictions is None:
			return

		preds = self._predictions.get(self._current_frame)
		if preds is None:
			return

		# FWD prediction
		fwd = preds.get("forward")
		if fwd is not None:
			cx = float(fwd["cx"])
			cy = float(fwd["cy"])
			w = float(fwd["w"])
			h = float(fwd["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._fwd_item = RectItem(
				x, y, int(w), int(h),
				color_str="#FF6400",
				label="FWD"
			)
			scene.addItem(self._fwd_item)

		# BWD prediction
		bwd = preds.get("backward")
		if bwd is not None:
			cx = float(bwd["cx"])
			cy = float(bwd["cy"])
			w = float(bwd["w"])
			h = float(bwd["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._bwd_item = RectItem(
				x, y, int(w), int(h),
				color_str="#FF00FF",
				label="BWD"
			)
			scene.addItem(self._bwd_item)

	#============================================

	def handle_key_press(self, key: int) -> bool:
		"""Handle keyboard events.

		Args:
			key: Qt key code.

		Returns:
			True if event was handled.
		"""
		if key == Qt.Key.Key_Escape or key == Qt.Key.Key_Q:
			self._on_quit()
			return True
		elif key == Qt.Key.Key_Space:
			self._on_skip()
			return True
		elif key == Qt.Key.Key_Left:
			self._on_prev()
			return True
		elif key == Qt.Key.Key_Right:
			self._on_next()
			return True
		elif key == Qt.Key.Key_N:
			self._on_not_in_frame()
			return True
		elif key == Qt.Key.Key_P:
			self._on_partial_toggle()
			return True
		elif key == Qt.Key.Key_A:
			self._on_approx_toggle()
			return True
		elif key == Qt.Key.Key_F:
			self._on_fwd_bwd_avg()
			return True

		return False

	#============================================

	def handle_mouse_press(self, scene_x: float, scene_y: float) -> None:
		"""Handle mouse button press.

		Args:
			scene_x: Scene x coordinate.
			scene_y: Scene y coordinate.
		"""
		if self._current_bgr is None:
			return

		self._drawing = True
		self._drag_start = (scene_x, scene_y)
		self._drag_current = (scene_x, scene_y)

		# Remove any old preview item
		if self._preview_item is not None:
			scene = self._window.get_frame_view().scene()
			scene.removeItem(self._preview_item)
			self._preview_item = None

	#============================================

	def handle_mouse_move(self, scene_x: float, scene_y: float) -> None:
		"""Handle mouse move.

		Args:
			scene_x: Scene x coordinate.
			scene_y: Scene y coordinate.
		"""
		if not self._drawing or self._drag_start is None:
			return

		self._drag_current = (scene_x, scene_y)

		# Update preview box
		scene = self._window.get_frame_view().scene()
		if self._preview_item is not None:
			scene.removeItem(self._preview_item)

		x1, y1 = self._drag_start
		x2, y2 = self._drag_current
		x = min(x1, x2)
		y = min(y1, y2)
		w = abs(x2 - x1)
		h = abs(y2 - y1)

		self._preview_item = PreviewBoxItem(x, y, w, h)
		scene.addItem(self._preview_item)

	#============================================

	def handle_mouse_release(self, scene_x: float, scene_y: float) -> None:
		"""Handle mouse button release.

		Args:
			scene_x: Scene x coordinate.
			scene_y: Scene y coordinate.
		"""
		if not self._drawing:
			return

		self._drawing = False

		if self._drag_start is None:
			return

		x1, y1 = self._drag_start
		x2, y2 = scene_x, scene_y

		# Normalize the box
		x = min(x1, x2)
		y = min(y1, y2)
		w = abs(x2 - x1)
		h = abs(y2 - y1)

		# Remove preview item
		scene = self._window.get_frame_view().scene()
		if self._preview_item is not None:
			scene.removeItem(self._preview_item)
			self._preview_item = None

		# Validate box size
		box_area = w * h
		frame_h, frame_w = self._current_bgr.shape[:2]
		min_area = 10
		max_area = frame_w * frame_h * 0.5

		if box_area < min_area or box_area > max_area:
			return

		box = [int(x), int(y), int(w), int(h)]
		self._on_box_drawn(box)

	#============================================

	def _on_box_drawn(self, box: list) -> None:
		"""Process a drawn box.

		Args:
			box: Box as [x, y, w, h].
		"""
		# Import here to avoid circular dependency
		from emwy_tools.track_runner import seeding as seeding_module

		if self._approx_mode:
			self._approx_mode = False
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			tx, ty, tw, th = norm_box
			cx = float(tx + tw / 2.0)
			cy = float(ty + th / 2.0)
			seed = {
				"frame_index": self._current_frame,
				"frame": self._current_frame,
				"time_s": round(self._current_frame / self._fps, 3),
				"status": "obstructed",
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
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			jersey_hsv = seeding_module.extract_jersey_color(
				self._current_bgr, norm_box
			)
			seed = seeding_module._build_seed_dict(
				self._current_frame,
				self._current_frame / self._fps,
				norm_box,
				jersey_hsv,
				self._pass_number,
				self._mode_str,
			)
			seed["status"] = "partial"
			self._commit_seed(seed)
			self._advance()
		else:
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			jersey_hsv = seeding_module.extract_jersey_color(
				self._current_bgr, norm_box
			)
			seed = seeding_module._build_seed_dict(
				self._current_frame,
				self._current_frame / self._fps,
				norm_box,
				jersey_hsv,
				self._pass_number,
				self._mode_str,
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
		if self._window is not None:
			self._window.close()

	#============================================

	def _on_skip(self) -> None:
		"""Skip current frame."""
		self._partial_mode = False
		self._advance()

	#============================================

	def _on_prev(self) -> None:
		"""Scrub backward by 0.2 seconds."""
		scrub_step = max(1, int(round(self._fps * 0.2)))
		self._current_frame = max(0, self._current_frame - scrub_step)
		self._refresh_frame()

	#============================================

	def _on_next(self) -> None:
		"""Scrub forward by 0.2 seconds."""
		scrub_step = max(1, int(round(self._fps * 0.2)))
		total_frames = self._reader.total_frames
		self._current_frame = min(total_frames - 1, self._current_frame + scrub_step)
		self._refresh_frame()

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

	def _on_partial_toggle(self) -> None:
		"""Toggle partial mode."""
		if self._partial_mode:
			self._partial_mode = False
			print("  partial mode cancelled")
		else:
			self._partial_mode = True
			print("  partial mode: draw the runner's torso box (press p again to cancel)")

	#============================================

	def _on_approx_toggle(self) -> None:
		"""Toggle approximate/positioned obstruction mode."""
		if self._approx_mode:
			self._approx_mode = False
			print("  approx mode cancelled")
		else:
			self._approx_mode = True
			print("  approx mode: draw approximate box to record obstruction position")

	#============================================

	def _update_scale_bar(self) -> None:
		"""Update the zoom scale bar display."""
		if self._scale_bar_item is None:
			return
		zoom = self._window.get_frame_view().get_zoom_factor()
		self._scale_bar_item.update_zoom(zoom)

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
