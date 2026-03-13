"""Target collection controller for track runner annotation.

Manages the Target mode annotation workflow, which is a subclass of
SeedController with different defaults for refinement passes.
"""

# local repo modules
import ui.seed_controller as seed_controller_module

#============================================


class TargetController(seed_controller_module.SeedController):
	"""Manages the Target mode annotation workflow.

	Inherits all functionality from SeedController, with different
	default parameters for refinement passes (pass 2+).
	"""

	def __init__(
		self,
		sorted_targets: list,
		reader: object,
		fps: float,
		config: dict,
		all_seeds: list,
		save_callback: object,
		pass_number: int = 2,
		mode_str: str = "suggested_refine",
		predictions: dict | None = None,
	) -> None:
		"""Initialize the TargetController.

		Args:
			sorted_targets: List of frame indices to collect seeds at.
			reader: Frame reader instance with read_frame(idx) method.
			fps: Frames per second of the video.
			config: Configuration dict.
			all_seeds: List of existing seeds to preserve.
			save_callback: Callable(seeds_list) to save seeds incrementally.
			pass_number: Which collection pass this is (default 2).
			mode_str: Seed collection mode string (default "suggested_refine").
			predictions: Optional dict mapping frame_index to prediction dicts.
		"""
		super().__init__(
			seed_frame_indices=sorted_targets,
			reader=reader,
			fps=fps,
			config=config,
			all_seeds=all_seeds,
			save_callback=save_callback,
			pass_number=pass_number,
			mode_str=mode_str,
			predictions=predictions,
		)
