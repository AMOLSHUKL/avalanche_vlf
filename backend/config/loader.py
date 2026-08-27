"""
Thread-safe configuration loader with strict schema validation, atomic disk
persistence, and singleton support.

Every load and every runtime hot-swap passes through `_validate_config`, so a
malformed value (a string where a float belongs, an inverted threshold pair,
an out-of-range prior) fails loudly at the boundary instead of silently
corrupting the fusion engine's arithmetic mid-mission.
"""
import copy
import os
import tempfile
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


class ConfigValidationError(ValueError):
    """Raised when the fusion parameter file violates the schema contract."""


EVIDENCE_GROUPS = ("GROUP_A_ELECTRONIC", "GROUP_B_SUBSURFACE", "GROUP_C_SURFACE")


def _deep_update(
    base_dict: dict[str, Any], update_dict: dict[str, Any]
) -> dict[str, Any]:
    """Recursively merge nested dicts without clobbering unmentioned root keys."""
    for k, v in update_dict.items():
        if isinstance(v, dict) and k in base_dict and isinstance(base_dict[k], dict):
            _deep_update(base_dict[k], v)
        else:
            base_dict[k] = v
    return base_dict


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigValidationError(message)


def _as_float(value: Any, key: str) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool),
             f"{key} must be a number, got {value!r}")
    return float(value)


def _validate_config(data: dict[str, Any]) -> None:
    """Enforce the full fusion-parameter schema contract.

    Raises ConfigValidationError.
    """
    _require(isinstance(data, dict), "configuration root must be a mapping")

    grid = data.get("grid")
    _require(isinstance(grid, dict), "missing required section: grid")
    for key in ("width_m", "height_m", "cell_size_m", "origin_lat", "origin_lon"):
        _require(key in grid, f"grid.{key} is required")
    width = _as_float(grid["width_m"], "grid.width_m")
    height = _as_float(grid["height_m"], "grid.height_m")
    cell = _as_float(grid["cell_size_m"], "grid.cell_size_m")
    _require(width > 0 and height > 0 and cell > 0, "grid dimensions must be positive")
    _require(
        width % cell == 0 and height % cell == 0,
        "grid.width_m and grid.height_m must be integer multiples of grid.cell_size_m",
    )
    origin_lat = _as_float(grid.get("origin_lat"), "grid.origin_lat")
    origin_lon = _as_float(grid.get("origin_lon"), "grid.origin_lon")
    _require(-80.0 <= origin_lat <= 84.0,
             "grid.origin_lat out of range [-80, 84] (UTM/MGRS operational limit)")
    _require(-180.0 <= origin_lon <= 180.0, "grid.origin_lon out of range [-180, 180]")

    sigma = _as_float(grid.get("lkp_sigma_m", 85.0), "grid.lkp_sigma_m")
    _require(sigma > 0, "grid.lkp_sigma_m must be positive")

    cols = round(width / cell)
    rows = round(height / cell)
    lkp = grid.get("lkp_cell", [cols // 2, rows // 2])
    _require(isinstance(lkp, (list, tuple)) and len(lkp) == 2,
             "grid.lkp_cell must be a [x, y] pair")
    lx, ly = lkp
    _require(
        isinstance(lx, int) and isinstance(ly, int) and 0 <= lx < cols and 0 <= ly < rows,
        f"grid.lkp_cell ({lx}, {ly}) outside grid bounds [0..{cols - 1}, 0..{rows - 1}]",
    )

    mission = data.get("mission", {})
    _require(isinstance(mission, dict), "section 'mission' must be a mapping")
    if mission.get("incident_epoch_s") is not None:
        epoch = _as_float(mission["incident_epoch_s"], "mission.incident_epoch_s")
        _require(epoch > 0, "mission.incident_epoch_s must be a positive epoch timestamp or null")

    t = data.get("thresholds")
    _require(isinstance(t, dict), "missing required section: thresholds")
    tau_p1 = _as_float(t.get("tau_p1"), "thresholds.tau_p1")
    tau_p2 = _as_float(t.get("tau_p2"), "thresholds.tau_p2")
    tau_p3 = _as_float(t.get("tau_p3", 0.15), "thresholds.tau_p3")
    for name, val in (("tau_p1", tau_p1), ("tau_p2", tau_p2), ("tau_p3", tau_p3)):
        _require(0.0 < val < 1.0, f"thresholds.{name} must lie in (0, 1)")
    _require(tau_p1 > tau_p2 > tau_p3,
             f"triage thresholds must strictly descend: tau_p1({tau_p1}) > tau_p2({tau_p2}) > tau_p3({tau_p3})")
    decay = _as_float(t.get("evidence_decay_factor"), "thresholds.evidence_decay_factor")
    _require(0.0 < decay <= 1.0, "thresholds.evidence_decay_factor must lie in (0, 1]")
    window = t.get("temporal_window_passes", 4)
    _require(isinstance(window, int) and window >= 2,
             "thresholds.temporal_window_passes must be an integer >= 2")
    _as_float(t.get("temporal_persistence_bonus"), "thresholds.temporal_persistence_bonus")
    _as_float(t.get("temporal_decay_penalty"), "thresholds.temporal_decay_penalty")
    _require(_as_float(t.get("pass_interval_seconds"), "thresholds.pass_interval_seconds") > 0,
             "thresholds.pass_interval_seconds must be positive")
    clamp = _as_float(t.get("llr_clamp", 15.0), "thresholds.llr_clamp")
    _require(clamp > 0, "thresholds.llr_clamp must be positive")
    ppt = _as_float(t.get("positive_pass_threshold", 0.30), "thresholds.positive_pass_threshold")
    _require(ppt > 0, "thresholds.positive_pass_threshold must be positive")

    caps = data.get("group_caps")
    _require(isinstance(caps, dict), "missing required section: group_caps")
    for g in EVIDENCE_GROUPS:
        _require(_as_float(caps.get(g), f"group_caps.{g}") > 0, f"group_caps.{g} must be positive")

    weights = data.get("group_weights")
    _require(isinstance(weights, dict), "missing required section: group_weights")
    for g in EVIDENCE_GROUPS:
        _require(_as_float(weights.get(g), f"group_weights.{g}") >= 0, f"group_weights.{g} must be non-negative")

    priors = data.get("sensor_priors")
    _require(isinstance(priors, dict) and priors, "missing required section: sensor_priors")
    for sensor, p in priors.items():
        _require(isinstance(p, dict), f"sensor_priors.{sensor} must be a mapping")
        pd = _as_float(p.get("p_z_given_h"), f"sensor_priors.{sensor}.p_z_given_h")
        pn = _as_float(p.get("p_z_given_not_h"), f"sensor_priors.{sensor}.p_z_given_not_h")
        _require(0.0 < pd < 1.0 and 0.0 < pn < 1.0,
                 f"sensor_priors.{sensor} probabilities must lie in (0, 1)")
        _require(pd > pn,
                 f"sensor_priors.{sensor}: p_z_given_h({pd}) must exceed p_z_given_not_h({pn})")

    att = data.get("environmental_attenuation", {})
    _require(isinstance(att, dict), "section 'environmental_attenuation' must be a mapping")
    for k, v in att.items():
        _require(_as_float(v, f"environmental_attenuation.{k}") >= 0,
                 f"environmental_attenuation.{k} must be non-negative")

    s = data.get("survival_model")
    _require(isinstance(s, dict), "missing required section: survival_model")
    p1_max = _as_float(s.get("phase1_max_minutes"), "survival_model.phase1_max_minutes")
    p2_max = _as_float(s.get("phase2_max_minutes"), "survival_model.phase2_max_minutes")
    _require(0 < p1_max < p2_max, "survival_model phases require 0 < phase1_max_minutes < phase2_max_minutes")
    for key in ("phase1_survival_rate", "phase2_drop_rate"):
        val = _as_float(s.get(key), f"survival_model.{key}")
        _require(0.0 <= val <= 1.0, f"survival_model.{key} must lie in [0, 1]")
    floor2 = _as_float(s.get("phase2_floor_survival", 0.27), "survival_model.phase2_floor_survival")
    base_min = _as_float(s.get("baseline_minimum_survival"), "survival_model.baseline_minimum_survival")
    _require(0 < base_min <= floor2 < 1,
             "survival_model requires 0 < baseline_minimum_survival <= phase2_floor_survival < 1")
    _require(_as_float(s.get("phase3_hypo_halflife_minutes"), "survival_model.phase3_hypo_halflife_minutes") > 0,
             "survival_model.phase3_hypo_halflife_minutes must be positive")
    ref_density = _as_float(s.get("reference_density_kg_m3", 350.0), "survival_model.reference_density_kg_m3")
    _require(50.0 <= ref_density <= 850.0,
             "survival_model.reference_density_kg_m3 must lie in [50, 850]")


class ConfigLoader:
    _instance: Optional["ConfigLoader"] = None
    _lock = threading.RLock()

    def __new__(cls, config_path: str | None = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: str | None = None):
        with self._lock:
            target_path = config_path or os.getenv(
                "FUSION_CONFIG_PATH",
                str(Path(__file__).parent.parent.parent / "config" / "fusion_parameters.yaml")
            )
            if getattr(self, "_initialized", False) and getattr(self, "config_path", None) == target_path:
                return
            self.config_path = target_path
            self._config_data: dict[str, Any] = {}
            self.reload()
            self._initialized = True

    @classmethod
    def reset_instance(cls) -> None:
        """Explicitly reset the singleton instance (primarily for isolated test fixtures)."""
        with cls._lock:
            cls._instance = None

    def reload(self) -> dict[str, Any]:
        """Load and validate configuration from disk."""
        with self._lock:
            if not os.path.exists(self.config_path):
                raise FileNotFoundError(f"Configuration file does not exist: {self.config_path}")
            with open(self.config_path, encoding="utf-8") as f:
                new_data = yaml.safe_load(f)
            _validate_config(new_data)
            self._config_data = new_data
            return self._config_data

    def update_parameters_in_memory(self, new_content: dict[str, Any], activated_by: str = "REST_API") -> int:
        """
        Validate and apply a partial parameter update, bump the version, and
        persist atomically (write-to-temp then rename) so a crash mid-write
        can never leave a truncated configuration file on disk.
        """
        if not isinstance(new_content, dict):
            raise ConfigValidationError("parameter update payload must be a mapping")
        with self._lock:
            # Deep copy: nested sections (thresholds, priors, ...) must not be
            # mutated before validation succeeds.
            candidate = _deep_update(copy.deepcopy(self._config_data), new_content)
            try:
                _validate_config(candidate)
            except ConfigValidationError as exc:
                raise ConfigValidationError(f"rejected parameter update: {exc}") from exc

            current_v = self._config_data.get("version", 1)
            candidate["version"] = current_v + 1
            candidate["activated_by"] = activated_by

            path = Path(self.config_path)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".yaml.tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    yaml.dump(candidate, f, default_flow_style=False, sort_keys=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)
            except OSError:
                # Disk persistence is best-effort on read-only mounts; memory
                # state remains authoritative and already validated.
                pass
            self._config_data = candidate
            return self._config_data["version"]

    @property
    def config(self) -> dict[str, Any]:
        """Validated configuration snapshot. Mutations never reach engine state."""
        with self._lock:
            return copy.deepcopy(self._config_data)

    def get_thresholds(self) -> dict[str, float]:
        with self._lock:
            return copy.deepcopy(self._config_data.get("thresholds", {}))

    def get_group_caps(self) -> dict[str, float]:
        with self._lock:
            return copy.deepcopy(self._config_data.get("group_caps", {}))

    def get_group_weights(self) -> dict[str, float]:
        with self._lock:
            return copy.deepcopy(self._config_data.get("group_weights", {}))

    def get_sensor_priors(self, sensor_type: str | Enum) -> dict[str, float]:
        with self._lock:
            key = sensor_type.value if isinstance(sensor_type, Enum) else str(sensor_type)
            priors = self._config_data.get("sensor_priors", {})
            if key in priors:
                return copy.deepcopy(priors[key])
            raise KeyError(
                f"No sensor priors configured for '{key}'. "
                "Refusing to fuse evidence from an uncalibrated modality."
            )
