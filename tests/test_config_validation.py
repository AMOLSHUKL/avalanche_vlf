"""
Configuration boundary validation tests: malformed parameters must be
rejected at the boundary with actionable errors, never silently fused.
"""
import shutil

import pytest
import yaml

from backend.config.loader import ConfigLoader, ConfigValidationError


@pytest.fixture
def isolated_loader(tmp_path):
    """ConfigLoader bound to a disposable copy of the repo config."""
    cfg_copy = tmp_path / "fusion_parameters.yaml"
    shutil.copy("config/fusion_parameters.yaml", cfg_copy)
    ConfigLoader.reset_instance()
    loader = ConfigLoader(config_path=str(cfg_copy))
    yield loader, cfg_copy
    ConfigLoader.reset_instance()


def _write_cfg(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def test_valid_base_config_loads(isolated_loader):
    loader, _ = isolated_loader
    assert loader.config["grid"]["cell_size_m"] == 5.0


def test_inverted_triage_thresholds_rejected(tmp_path):
    cfg = tmp_path / "bad_thresholds.yaml"
    with open("config/fusion_parameters.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["thresholds"]["tau_p1"] = 0.40  # below tau_p2 (0.45)
    _write_cfg(cfg, data)

    ConfigLoader.reset_instance()
    try:
        with pytest.raises(ConfigValidationError, match="tau_p1"):
            ConfigLoader(config_path=str(cfg))
    finally:
        ConfigLoader.reset_instance()


def test_degenerate_priors_rejected(tmp_path):
    cfg = tmp_path / "bad_priors.yaml"
    with open("config/fusion_parameters.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["sensor_priors"]["GPR"]["p_z_given_h"] = 0.05  # below p_z_given_not_h (0.07)
    _write_cfg(cfg, data)

    ConfigLoader.reset_instance()
    try:
        with pytest.raises(ConfigValidationError, match="GPR"):
            ConfigLoader(config_path=str(cfg))
    finally:
        ConfigLoader.reset_instance()


def test_hot_swap_rejects_invalid_partial_update(isolated_loader):
    loader, cfg = isolated_loader
    version_before = loader.config["version"]

    with pytest.raises(ConfigValidationError):
        loader.update_parameters_in_memory(
            {"thresholds": {"tau_p1": "not-a-number"}}, "BAD_UPDATE"
        )

    # Rejected update leaves memory state and version untouched.
    assert loader.config["version"] == version_before
    assert loader.get_thresholds()["tau_p1"] == 0.85


def test_hot_swap_applies_valid_partial_update(isolated_loader):
    loader, cfg = isolated_loader
    new_version = loader.update_parameters_in_memory(
        {"thresholds": {"tau_p1": 0.88}}, "TEST_COMMANDER"
    )
    assert new_version == loader.config["version"]
    assert loader.get_thresholds()["tau_p1"] == 0.88
    # Deep merge preserved untouched sibling keys.
    assert loader.get_thresholds()["tau_p2"] == 0.45


def test_unknown_sensor_priors_fail_loudly(isolated_loader):
    loader, _ = isolated_loader
    with pytest.raises(KeyError):
        loader.get_sensor_priors("UNREGISTERED_SENSOR")
