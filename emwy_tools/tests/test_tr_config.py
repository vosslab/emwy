"""Unit tests for track_runner.tr_config module."""

# Standard Library
import os
import tempfile

# PIP3 modules
import pytest

# local repo modules
import track_runner.tr_config as config_mod


#============================================
def test_config_default_config_has_required_sections() -> None:
	"""default_config has detection and processing sections."""
	cfg = config_mod.default_config()
	for section in ("detection", "processing"):
		assert section in cfg, f"missing section: {section}"


#============================================
def test_config_default_config_has_header() -> None:
	"""default_config includes the track_runner header key."""
	cfg = config_mod.default_config()
	assert config_mod.TOOL_CONFIG_HEADER_KEY in cfg
	assert cfg[config_mod.TOOL_CONFIG_HEADER_KEY] == config_mod.TOOL_CONFIG_HEADER_VALUE


#============================================
def test_config_validate_passes_on_valid() -> None:
	"""validate_config(default_config()) does not raise."""
	cfg = config_mod.default_config()
	config_mod.validate_config(cfg)


#============================================
def test_config_validate_fails_on_missing_header() -> None:
	"""validate_config({}) raises RuntimeError."""
	with pytest.raises(RuntimeError):
		config_mod.validate_config({})


#============================================
def test_config_validate_fails_on_wrong_version() -> None:
	"""validate_config with wrong version raises RuntimeError."""
	bad = {config_mod.TOOL_CONFIG_HEADER_KEY: 99, "detection": {}, "processing": {}}
	with pytest.raises(RuntimeError):
		config_mod.validate_config(bad)


#============================================
def test_config_merge_overrides_scalar() -> None:
	"""merge_config replaces scalar values from override."""
	base = {"a": 1, "b": 2}
	override = {"a": 99}
	merged = config_mod.merge_config(base, override)
	assert merged["a"] == 99
	assert merged["b"] == 2


#============================================
def test_config_merge_deep_merges_dicts() -> None:
	"""merge_config deep-merges nested dicts."""
	cfg = config_mod.default_config()
	override = {"processing": {"crf": 28}}
	merged = config_mod.merge_config(cfg, override)
	# overridden crf
	assert merged["processing"]["crf"] == 28
	# other processing keys still from base
	assert "crop_aspect" in merged["processing"]


#============================================
def test_config_write_and_load_round_trip() -> None:
	"""write_config then load_config returns equivalent config."""
	cfg = config_mod.default_config()
	with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
		tmp_path = tmp.name
	config_mod.write_config(tmp_path, cfg)
	loaded = config_mod.load_config(tmp_path)
	assert config_mod.TOOL_CONFIG_HEADER_KEY in loaded
	os.unlink(tmp_path)
