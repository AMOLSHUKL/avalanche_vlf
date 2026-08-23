# AVALANCHE-VLF: Full-Stack Remediation & Production Codebase

---

### File Tree
```
avalanche_vlf/
├── config/
│   └── fusion_parameters.yaml
├── backend/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── sensors.py
│   │   └── domain.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── loader.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── rf.py
│   │   │   ├── gpr.py
│   │   │   ├── seismic.py
│   │   │   ├── thermal.py
│   │   │   ├── optical.py
│   │   │   └── registry.py
│   │   ├── terrain.py
│   │   ├── logger.py
│   │   └── fusion.py
│   ├── telemetry/
│   │   ├── __init__.py
│   │   └── simulator.py
│   └── main.py
├── frontend/
│   ├── index.html
│   └── app.js
├── tests/
│   ├── __init__.py
│   └── test_fusion.py
└── HANDOFF.md
```

---

### `config/fusion_parameters.yaml`
```yaml
version: 1
activated_by: "DGRE_SYSTEM_INIT"
notes: "High-Altitude Himalayan SAR Initial Calibration"

grid:
  width_m: 500.0
  height_m: 500.0
  cell_size_m: 5.0
  origin_lat: 34.183900
  origin_lon: 77.562100

thresholds:
  tau_p1: 0.85
  tau_p2: 0.45
  temporal_window_passes: 4
  temporal_persistence_bonus: 0.75
  temporal_decay_penalty: 0.40

group_caps:
  GROUP_A_ELECTRONIC: 4.5
  GROUP_B_SUBSURFACE: 4.2
  GROUP_C_SURFACE: 2.5

group_weights:
  GROUP_A_ELECTRONIC: 1.00
  GROUP_B_SUBSURFACE: 0.95
  GROUP_C_SURFACE: 0.65

sensor_priors:
  TRANSCEIVER_457:
    p_z_given_h: 0.95
    p_z_given_not_h: 0.02
    max_range_m: 50.0
  RECCO:
    p_z_given_h: 0.89
    p_z_given_not_h: 0.03
    max_range_m: 35.0
  MOBILE_RF:
    p_z_given_h: 0.82
    p_z_given_not_h: 0.06
    max_range_m: 40.0
  GPR:
    p_z_given_h: 0.90
    p_z_given_not_h: 0.07
    max_depth_m: 6.0
  SEISMIC_ACOUSTIC:
    p_z_given_h: 0.72
    p_z_given_not_h: 0.10
    max_range_m: 25.0
  THERMAL_IR:
    p_z_given_h: 0.86
    p_z_given_not_h: 0.14
    max_burial_depth_m: 0.20
  RGB_VISUAL:
    p_z_given_h: 0.80
    p_z_given_not_h: 0.08

environmental_attenuation:
  snow_water_equivalent_penalty_factor: 0.0028
  emi_noise_penalty_factor: 0.018
  wind_dispersion_penalty_factor: 0.022
  acoustic_noise_floor_penalty: 0.030

survival_model:
  phase1_max_minutes: 15.0
  phase1_survival_rate: 0.92
  phase2_max_minutes: 35.0
  phase2_drop_rate: 0.65
  phase3_hypo_halflife_minutes: 45.0
  baseline_minimum_survival: 0.03
```

---

### `backend/schemas/sensors.py`
```python
"""
Pydantic v2 Sensor Payload Data Contracts with Strict Boundary Validation.
Compliant with Python 3.12+ timezone-aware UTC timestamps.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class EvidenceGroupEnum(str, Enum):
    GROUP_A_ELECTRONIC = "GROUP_A_ELECTRONIC"
    GROUP_B_SUBSURFACE = "GROUP_B_SUBSURFACE"
    GROUP_C_SURFACE = "GROUP_C_SURFACE"


class SensorTypeEnum(str, Enum):
    TRANSCEIVER_457 = "TRANSCEIVER_457"
    RECCO = "RECCO"
    MOBILE_RF = "MOBILE_RF"
    GPR = "GPR"
    SEISMIC_ACOUSTIC = "SEISMIC_ACOUSTIC"
    THERMAL_IR = "THERMAL_IR"
    RGB_VISUAL = "RGB_VISUAL"


class GeospatialContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    altitude_m: float = Field(..., ge=0.0, le=9000.0, description="Altitude above MSL in meters")
    snow_depth_est_m: float = Field(default=1.5, ge=0.0, le=25.0)
    snow_density_kg_m3: float = Field(default=350.0, ge=50.0, le=850.0)
    ambient_temp_c: float = Field(default=-10.0, ge=-60.0, le=40.0)
    emi_noise_floor_dbm: float = Field(default=-105.0, ge=-150.0, le=-20.0)
    acoustic_noise_db: float = Field(default=30.0, ge=0.0, le=140.0)
    wind_speed_mps: float = Field(default=5.0, ge=0.0, le=75.0)


class BaseSensorPayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sensor_id: str = Field(..., min_length=2, max_length=64)
    sensor_type: SensorTypeEnum
    evidence_group: EvidenceGroupEnum
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    geo: GeospatialContext
    raw_signal_strength_dbm: Optional[float] = Field(None, ge=-150.0, le=30.0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)

    @field_validator("timestamp")
    @classmethod
    def enforce_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class TransceiverPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.TRANSCEIVER_457
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_A_ELECTRONIC
    flux_line_angle_deg: float = Field(..., ge=0.0, le=360.0)
    estimated_distance_m: float = Field(..., ge=0.0, le=100.0)
    is_multi_victim_signal: bool = Field(default=False)


class RECCOPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.RECCO
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_A_ELECTRONIC
    harmonic_return_amplitude: float = Field(..., ge=0.0, le=100.0)
    radar_cross_section_m2: float = Field(default=0.1, ge=0.0, le=10.0)


class MobileRFPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.MOBILE_RF
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_A_ELECTRONIC
    imsi_hash: Optional[str] = Field(None, max_length=64)
    channel_frequency_mhz: float = Field(..., ge=700.0, le=6000.0)
    timing_advance_m: Optional[float] = Field(None, ge=0.0, le=5000.0)


class GPRPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.GPR
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_B_SUBSURFACE
    estimated_depth_m: float = Field(..., ge=0.0, le=15.0)
    hyperbola_eccentricity: float = Field(..., ge=0.0, le=1.0)
    dielectric_contrast: float = Field(..., ge=1.0, le=80.0)
    void_anomaly_flag: bool = Field(default=False)


class SeismicAcousticPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.SEISMIC_ACOUSTIC
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_B_SUBSURFACE
    dominant_frequency_hz: float = Field(..., ge=0.5, le=500.0)
    signal_to_noise_ratio_db: float = Field(..., ge=-20.0, le=80.0)
    impulse_pattern_detected: bool = Field(default=False)


class ThermalPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.THERMAL_IR
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_C_SURFACE
    temperature_delta_c: float = Field(..., ge=-40.0, le=50.0)
    pixel_area_count: int = Field(..., ge=1, le=1000000)
    surface_clue_detected: bool = Field(default=False)


class RGBPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.RGB_VISUAL
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_C_SURFACE
    bounding_box_area_ratio: float = Field(..., ge=0.0, le=1.0)
    equipment_color_match_score: float = Field(default=0.0, ge=0.0, le=1.0)
    shadow_anomaly_detected: bool = Field(default=False)
```

---

### `backend/schemas/domain.py`
```python
"""
Domain Entities and WebSocket Protocol Envelopes with Python 3.12+ Timestamp Handling.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Generic, TypeVar
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class PriorityZoneEnum(str, Enum):
    P1 = "P1"  # Probe & Excavate immediately (P >= 0.85)
    P2 = "P2"  # Secondary Scan (0.45 <= P < 0.85)
    P3 = "P3"  # Defer / Area Scan (0.15 <= P < 0.45)
    P4 = "P4"  # Clear / Baseline Monitoring (P < 0.15)


class ZoneStatusEnum(str, Enum):
    UNSEEN = "UNSEEN"
    CANDIDATE = "CANDIDATE"
    ACTIVE_SEARCH = "ACTIVE_SEARCH"
    PROBING = "PROBING"
    CONFIRMED_VICTIM = "CONFIRMED_VICTIM"
    CLEARED_FALSE_POSITIVE = "CLEARED_FALSE_POSITIVE"


class DirectiveTypeEnum(str, Enum):
    PROBE_EXCAVATE = "PROBE_EXCAVATE"
    SECONDARY_SCAN = "SECONDARY_SCAN"
    DEFER_MONITOR = "DEFER_MONITOR"


class GridZoneState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    zone_id: str
    cell_x: int
    cell_y: int
    lat: float
    lon: float
    elevation_m: float
    slope_deg: float
    current_llr: float = 0.0
    probability: float = 0.0
    priority_score: float = 0.0
    priority_zone: PriorityZoneEnum = PriorityZoneEnum.P4
    status: ZoneStatusEnum = ZoneStatusEnum.UNSEEN
    burial_depth_estimate_m: Optional[float] = None
    confidence_radius_m: Optional[float] = None
    contributing_evidence_groups: List[str] = Field(default_factory=list)
    temporal_consistency_score: float = 0.0
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TacticalDirective(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    directive_id: str
    target_zone_id: str
    directive_type: DirectiveTypeEnum
    priority_zone: PriorityZoneEnum
    lat: float
    lon: float
    depth_estimate_m: float
    confidence_radius_m: float
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recommended_equipment: List[str] = Field(default_factory=list)
    rationale: str


class UAVAssetTelemetry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    asset_id: str
    label: str
    current_lat: float
    current_lon: float
    current_alt_m: float
    battery_pct: float
    active_sensor_modalities: List[str]
    heading_deg: float
    speed_mps: float
    last_telemetry_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WSEnvelope(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    incident_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: T
```

---

### `backend/config/loader.py`
```python
"""
Thread-Safe Configuration Loader utilizing standard re-entrant locks.
"""

import os
import yaml
import threading
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigLoader:
    _instance: Optional["ConfigLoader"] = None
    _lock = threading.Lock()

    def __new__(cls, config_path: Optional[str] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigLoader, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.config_path = config_path or os.getenv(
            "FUSION_CONFIG_PATH",
            str(Path(__file__).parent.parent.parent / "config" / "fusion_parameters.yaml")
        )
        self._sync_lock = threading.RLock()
        self._config_data: Dict[str, Any] = {}
        self.reload()
        self._initialized = True

    def reload(self) -> Dict[str, Any]:
        with self._sync_lock:
            if not os.path.exists(self.config_path):
                raise FileNotFoundError(f"Configuration file does not exist: {self.config_path}")
            with open(self.config_path, "r", encoding="utf-8") as f:
                new_data = yaml.safe_load(f)
            self._config_data = new_data
            return self._config_data

    def update_parameters_in_memory(self, new_content: Dict[str, Any], activated_by: str = "REST_API") -> int:
        with self._sync_lock:
            current_v = self._config_data.get("version", 1)
            new_content["version"] = current_v + 1
            new_content["activated_by"] = activated_by
            self._config_data = new_content
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config_data, f, default_flow_style=False)
            return self._config_data["version"]

    @property
    def config(self) -> Dict[str, Any]:
        with self._sync_lock:
            return self._config_data

    def get_thresholds(self) -> Dict[str, float]:
        with self._sync_lock:
            return self._config_data.get("thresholds", {})

    def get_group_caps(self) -> Dict[str, float]:
        with self._sync_lock:
            return self._config_data.get("group_caps", {})

    def get_sensor_priors(self, sensor_type: str) -> Dict[str, float]:
        with self._sync_lock:
            return self._config_data.get("sensor_priors", {}).get(
                sensor_type, {"p_z_given_h": 0.80, "p_z_given_not_h": 0.10}
            )
```

---

### `backend/engine/adapters/base.py`
```python
"""
Abstract Base Sensor Adapter with strict type enforcement.
"""

from abc import ABC, abstractmethod
import math
from typing import Dict, Any
from backend.schemas.sensors import BaseSensorPayload


class BaseSensorAdapter(ABC):
    def __init__(self, sensor_type: str, config: Dict[str, Any]):
        self.sensor_type = sensor_type
        self.config = config

    @abstractmethod
    def parse_raw(self, raw_input: Any) -> BaseSensorPayload:
        pass

    def compute_llr(self, payload: BaseSensorPayload) -> float:
        priors = self.config.get("sensor_priors", {}).get(self.sensor_type, {})
        p_z_h = priors.get("p_z_given_h", 0.85)
        p_z_not_h = priors.get("p_z_given_not_h", 0.10)

        # Scale detection likelihood by reported sensor payload confidence
        effective_p_z_h = max(0.001, min(0.999, p_z_h * payload.confidence_score))
        effective_p_z_not_h = max(0.001, min(0.999, p_z_not_h * (1.0 - payload.confidence_score * 0.5)))

        return math.log(effective_p_z_h / effective_p_z_not_h)

    @abstractmethod
    def evaluate_quality(self, payload: BaseSensorPayload) -> float:
        pass
```

---

### `backend/engine/adapters/rf.py`
```python
"""
Polymorphic Adapter for Group A Electronic Sensors (457 kHz, RECCO, Cellular RF).
"""

import math
from typing import Any, Dict
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import (
    BaseSensorPayload,
    TransceiverPayload,
    RECCOPayload,
    MobileRFPayload,
    SensorTypeEnum
)


class SimulatedRFAdapter(BaseSensorAdapter):
    def __init__(self, sensor_type: SensorTypeEnum, config: Dict[str, Any]):
        super().__init__(sensor_type.value, config)
        self.typed_enum = sensor_type

    def parse_raw(self, raw_input: Any) -> BaseSensorPayload:
        if isinstance(raw_input, BaseSensorPayload):
            return raw_input
        if isinstance(raw_input, dict):
            if self.typed_enum == SensorTypeEnum.TRANSCEIVER_457:
                return TransceiverPayload(**raw_input)
            elif self.typed_enum == SensorTypeEnum.RECCO:
                return RECCOPayload(**raw_input)
            elif self.typed_enum == SensorTypeEnum.MOBILE_RF:
                return MobileRFPayload(**raw_input)
        raise ValueError(f"Invalid input format for {self.sensor_type}")

    def evaluate_quality(self, payload: BaseSensorPayload) -> float:
        emi_noise = payload.geo.emi_noise_floor_dbm
        penalty_factor = self.config.get("environmental_attenuation", {}).get("emi_noise_penalty_factor", 0.018)
        emi_delta = max(0.0, emi_noise - (-105.0))
        q_emi = 1.0 / (1.0 + (penalty_factor * emi_delta))

        if isinstance(payload, TransceiverPayload):
            dist = payload.estimated_distance_m
            max_range = self.config.get("sensor_priors", {}).get("TRANSCEIVER_457", {}).get("max_range_m", 50.0)
            q_dist = 1.0 / (1.0 + (dist / (max_range * 0.5)) ** 2)
            return max(0.05, min(1.0, q_emi * q_dist))

        elif isinstance(payload, RECCOPayload):
            rcs_weight = min(1.0, payload.radar_cross_section_m2 / 0.5)
            return max(0.05, min(1.0, q_emi * rcs_weight))

        elif isinstance(payload, MobileRFPayload):
            ta_penalty = 1.0 if payload.timing_advance_m is None else (1.0 / (1.0 + (payload.timing_advance_m / 500.0)))
            return max(0.05, min(1.0, q_emi * ta_penalty))

        return max(0.05, min(1.0, q_emi))
```

---

### `backend/engine/adapters/gpr.py`
```python
"""
Concrete GPR Radar Adapter for Group B Subsurface Dielectric Anomaly Sensing.
"""

import math
from typing import Any, Dict
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import GPRPayload, SensorTypeEnum


class SimulatedGPRAdapter(BaseSensorAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(SensorTypeEnum.GPR.value, config)

    def parse_raw(self, raw_input: Any) -> GPRPayload:
        if isinstance(raw_input, GPRPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return GPRPayload(**raw_input)
        raise ValueError("Invalid raw payload for GPRAdapter")

    def evaluate_quality(self, payload: GPRPayload) -> float:
        density = payload.geo.snow_density_kg_m3
        depth = payload.estimated_depth_m
        attenuation_params = self.config.get("environmental_attenuation", {})
        kappa = attenuation_params.get("snow_water_equivalent_penalty_factor", 0.0028)

        # Dielectric absorption through packed wet snowpack
        q_env = math.exp(-kappa * (density / 100.0) * depth)
        q_eccentricity = payload.hyperbola_eccentricity

        return max(0.05, min(1.0, q_env * q_eccentricity))
```

---

### `backend/engine/adapters/seismic.py`
```python
"""
Concrete Subsurface Seismic and Acoustic Life-Sign Sensor Adapter (Group B).
"""

import math
from typing import Any, Dict
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import SeismicAcousticPayload, SensorTypeEnum


class SeismicAdapter(BaseSensorAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(SensorTypeEnum.SEISMIC_ACOUSTIC.value, config)

    def parse_raw(self, raw_input: Any) -> SeismicAcousticPayload:
        if isinstance(raw_input, SeismicAcousticPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return SeismicAcousticPayload(**raw_input)
        raise ValueError("Invalid raw payload for SeismicAdapter")

    def evaluate_quality(self, payload: SeismicAcousticPayload) -> float:
        noise_penalty = self.config.get("environmental_attenuation", {}).get("acoustic_noise_floor_penalty", 0.030)
        ambient_noise = payload.geo.acoustic_noise_db
        snr = payload.signal_to_noise_ratio_db

        q_snr = 1.0 / (1.0 + math.exp(-0.1 * (snr - 5.0)))
        q_ambient = 1.0 / (1.0 + max(0.0, ambient_noise - 40.0) * noise_penalty)

        pattern_mult = 1.25 if payload.impulse_pattern_detected else 0.85
        return max(0.05, min(1.0, q_snr * q_ambient * pattern_mult))
```

---

### `backend/engine/adapters/thermal.py`
```python
"""
Concrete Long-Wave Infrared (LWIR) Thermal Adapter (Group C Surface).
"""

import math
from typing import Any, Dict
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import ThermalPayload, SensorTypeEnum


class ThermalAdapter(BaseSensorAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(SensorTypeEnum.THERMAL_IR.value, config)

    def parse_raw(self, raw_input: Any) -> ThermalPayload:
        if isinstance(raw_input, ThermalPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return ThermalPayload(**raw_input)
        raise ValueError("Invalid raw payload for ThermalAdapter")

    def evaluate_quality(self, payload: ThermalPayload) -> float:
        wind_factor = self.config.get("environmental_attenuation", {}).get("wind_dispersion_penalty_factor", 0.022)
        wind_speed = payload.geo.wind_speed_mps
        snow_depth = payload.geo.snow_depth_est_m

        # Deep snow attenuates surface infrared signature
        q_depth = math.exp(-15.0 * snow_depth) if not payload.surface_clue_detected else 0.90
        q_wind = 1.0 / (1.0 + (wind_speed * wind_factor))

        delta_temp_score = min(1.0, abs(payload.temperature_delta_c) / 10.0)
        return max(0.01, min(1.0, q_depth * q_wind * delta_temp_score))
```

---

### `backend/engine/adapters/optical.py`
```python
"""
Concrete High-Resolution RGB Optical Adapter (Group C Surface).
"""

from typing import Any, Dict
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import RGBPayload, SensorTypeEnum


class OpticalAdapter(BaseSensorAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(SensorTypeEnum.RGB_VISUAL.value, config)

    def parse_raw(self, raw_input: Any) -> RGBPayload:
        if isinstance(raw_input, RGBPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return RGBPayload(**raw_input)
        raise ValueError("Invalid raw payload for OpticalAdapter")

    def evaluate_quality(self, payload: RGBPayload) -> float:
        # Optical analysis depends on lighting, visibility, and target color signature
        q_color = max(0.1, payload.equipment_color_match_score)
        q_area = min(1.0, payload.bounding_box_area_ratio * 20.0)
        shadow_boost = 1.15 if payload.shadow_anomaly_detected else 0.90

        return max(0.05, min(1.0, q_color * q_area * shadow_boost))
```

---

### `backend/engine/adapters/registry.py`
```python
"""
Strict Polymorphic Adapter Registry for Dynamic Telemetry Dispatch.
"""

from typing import Dict, Any
from backend.schemas.sensors import SensorTypeEnum, BaseSensorPayload
from backend.engine.adapters.base import BaseSensorAdapter
from backend.engine.adapters.rf import SimulatedRFAdapter
from backend.engine.adapters.gpr import SimulatedGPRAdapter
from backend.engine.adapters.seismic import SeismicAdapter
from backend.engine.adapters.thermal import ThermalAdapter
from backend.engine.adapters.optical import OpticalAdapter


class AdapterRegistry:
    def __init__(self, config: Dict[str, Any]):
        self._adapters: Dict[SensorTypeEnum, BaseSensorAdapter] = {
            SensorTypeEnum.TRANSCEIVER_457: SimulatedRFAdapter(SensorTypeEnum.TRANSCEIVER_457, config),
            SensorTypeEnum.RECCO: SimulatedRFAdapter(SensorTypeEnum.RECCO, config),
            SensorTypeEnum.MOBILE_RF: SimulatedRFAdapter(SensorTypeEnum.MOBILE_RF, config),
            SensorTypeEnum.GPR: SimulatedGPRAdapter(config),
            SensorTypeEnum.SEISMIC_ACOUSTIC: SeismicAdapter(config),
            SensorTypeEnum.THERMAL_IR: ThermalAdapter(config),
            SensorTypeEnum.RGB_VISUAL: OpticalAdapter(config),
        }

    def get_adapter(self, sensor_type: SensorTypeEnum) -> BaseSensorAdapter:
        if sensor_type not in self._adapters:
            raise KeyError(f"No registered adapter for sensor type: {sensor_type}")
        return self._adapters[sensor_type]

    def process_payload(self, payload: BaseSensorPayload) -> tuple[float, float]:
        adapter = self.get_adapter(payload.sensor_type)
        llr = adapter.compute_llr(payload)
        quality = adapter.evaluate_quality(payload)
        return llr, quality
```

---

### `backend/engine/terrain.py`
```python
"""
Digital Elevation Model (DEM) and Avalanche Runout Physics Engine.
"""

import math
import numpy as np
from typing import Tuple


class TerrainEngine:
    def __init__(self, width_m: float = 500.0, height_m: float = 500.0, cell_size_m: float = 5.0):
        self.width_m = width_m
        self.height_m = height_m
        self.cell_size_m = cell_size_m
        self.cols = int(width_m / cell_size_m)
        self.rows = int(height_m / cell_size_m)
        self.elevation_grid, self.slope_grid = self._generate_dem()

    def _generate_dem(self) -> Tuple[np.ndarray, np.ndarray]:
        x = np.linspace(0, self.width_m, self.cols)
        y = np.linspace(0, self.height_m, self.rows)
        xx, yy = np.meshgrid(x, y)

        # Himalayan Avalanche Gully Profile
        elevation = 3800.0 + (yy * 0.42) + 25.0 * np.sin(xx / 70.0)
        dy, dx = np.gradient(elevation, self.cell_size_m, self.cell_size_m)
        slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
        slope_deg = np.degrees(slope_rad)
        return elevation, slope_deg

    def compute_prior_prob(self, cell_x: int, cell_y: int, lkp_cell: Tuple[int, int]) -> float:
        dist = math.sqrt((cell_x - lkp_cell[0])**2 + (cell_y - lkp_cell[1])**2) * self.cell_size_m
        p_lkp = math.exp(-(dist**2) / (2.0 * (85.0**2)))

        slope = self.slope_grid[cell_y, cell_x]
        if slope < 15.0:
            p_slope = 0.65
        elif 15.0 <= slope <= 32.0:
            p_slope = 0.95
        elif 32.0 < slope <= 45.0:
            p_slope = 0.35
        else:
            p_slope = 0.05

        return max(0.01, min(0.95, p_lkp * p_slope))
```

---

### `backend/engine/logger.py`
```python
"""
Structured JSONL Inference and Ground-Truth Verification Event Logger.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from pathlib import Path


class TelemetryFineTuneLogger:
    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = Path(log_dir or (Path(__file__).parent.parent.parent / "logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.session_file = self.log_dir / f"sar_mission_{session_id}.jsonl"

    def log_inference_event(
        self,
        zone_id: str,
        cell_coords: Tuple[int, int],
        sensor_payload: Dict[str, Any],
        group_llr_snapshot: Dict[str, float],
        posterior_p: float,
        directive_issued: Optional[str] = None
    ) -> None:
        event = {
            "record_type": "INFERENCE_STEP",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": zone_id,
            "cell_x": cell_coords[0],
            "cell_y": cell_coords[1],
            "sensor_payload": sensor_payload,
            "group_llr_snapshot": group_llr_snapshot,
            "posterior_probability": posterior_p,
            "directive_issued": directive_issued
        }
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def log_ground_truth_outcome(
        self,
        directive_id: str,
        zone_id: str,
        outcome: str,
        actual_depth_m: Optional[float] = None,
        notes: str = ""
    ) -> None:
        record = {
            "record_type": "GROUND_TRUTH_VERIFICATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "directive_id": directive_id,
            "zone_id": zone_id,
            "outcome": outcome,
            "actual_depth_m": actual_depth_m,
            "notes": notes
        }
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
```

---

### `backend/engine/fusion.py`
```python
"""
Thread-Safe, Concurrency-Guarded Multi-Modal Evidence Fusion Engine.
Implements Aggregate Intra-Group Windowed Capping, Asynchronous State Locks,
and Spatiotemporal Utility Optimization.
"""

import asyncio
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any

from backend.config.loader import ConfigLoader
from backend.engine.terrain import TerrainEngine
from backend.engine.logger import TelemetryFineTuneLogger
from backend.schemas.sensors import BaseSensorPayload
from backend.schemas.domain import (
    GridZoneState,
    PriorityZoneEnum,
    ZoneStatusEnum,
    TacticalDirective,
    DirectiveTypeEnum
)


class FusionEngine:
    def __init__(self, config_loader: Optional[ConfigLoader] = None):
        self.config_loader = config_loader or ConfigLoader()
        self.terrain = TerrainEngine(width_m=500.0, height_m=500.0, cell_size_m=5.0)
        self.logger = TelemetryFineTuneLogger()
        self.start_time = time.time()
        self._state_lock = asyncio.Lock()

        self.cols = self.terrain.cols
        self.rows = self.terrain.rows
        self.grid: Dict[str, GridZoneState] = {}
        self.active_directives: List[TacticalDirective] = []

        # Aggregate evidence window storage per zone:
        # zone_id -> { group_name -> deque of (timestamp, effective_llr) }
        self._group_windows: Dict[str, Dict[str, deque]] = {}
        self._temporal_pass_history: Dict[str, deque] = {}

        self._initialize_grid(lkp_cell=(50, 40))

    def _initialize_grid(self, lkp_cell: Tuple[int, int]) -> None:
        origin_lat = self.config_loader.config["grid"]["origin_lat"]
        origin_lon = self.config_loader.config["grid"]["origin_lon"]
        cell_size = self.terrain.cell_size_m

        for cy in range(self.rows):
            for cx in range(self.cols):
                zone_id = f"cell_{cx}_{cy}"
                lat = origin_lat + (cy * cell_size) / 111111.0
                lon = origin_lon + (cx * cell_size) / (111111.0 * math.cos(math.radians(origin_lat)))
                elevation = float(self.terrain.elevation_grid[cy, cx])
                slope = float(self.terrain.slope_grid[cy, cx])

                p0 = self.terrain.compute_prior_prob(cx, cy, lkp_cell)
                p0 = max(0.001, min(0.999, p0))
                llr_0 = math.log(p0 / (1.0 - p0))

                self.grid[zone_id] = GridZoneState(
                    zone_id=zone_id,
                    cell_x=cx,
                    cell_y=cy,
                    lat=lat,
                    lon=lon,
                    elevation_m=elevation,
                    slope_deg=slope,
                    current_llr=llr_0,
                    probability=p0,
                    priority_score=0.0,
                    priority_zone=PriorityZoneEnum.P4,
                    status=ZoneStatusEnum.UNSEEN,
                    last_updated_at=datetime.now(timezone.utc)
                )

                self._group_windows[zone_id] = {
                    "GROUP_A_ELECTRONIC": deque(maxlen=8),
                    "GROUP_B_SUBSURFACE": deque(maxlen=8),
                    "GROUP_C_SURFACE": deque(maxlen=8)
                }
                self._temporal_pass_history[zone_id] = deque(maxlen=self.config_loader.get_thresholds().get("temporal_window_passes", 4))

    async def update_cell_evidence(
        self,
        cell_x: int,
        cell_y: int,
        sensor_payload: BaseSensorPayload,
        raw_llr: float,
        quality_coef: float
    ) -> GridZoneState:
        """
        Concurrency-safe Bayesian atomic update with aggregate intra-group capping.
        """
        async with self._state_lock:
            zone_id = f"cell_{cell_x}_{cell_y}"
            if zone_id not in self.grid:
                raise KeyError(f"Cell coordinates ({cell_x}, {cell_y}) out of grid boundaries.")

            state = self.grid[zone_id]
            group_name = sensor_payload.evidence_group.value
            group_caps = self.config_loader.get_group_caps()
            group_weights = self.config_loader.config.get("group_weights", {})
            thresholds = self.config_loader.get_thresholds()

            # 1. Append measurement to the zone's group evidence window
            effective_sample_llr = raw_llr * quality_coef
            self._group_windows[zone_id][group_name].append((time.time(), effective_sample_llr))

            # 2. Compute aggregate intra-group capped LLR across all groups
            aggregate_group_llr_sum = 0.0
            group_llr_snapshot: Dict[str, float] = {}

            for g_name, window in self._group_windows[zone_id].items():
                if not window:
                    continue
                # Sum un-decayed samples in the active window
                raw_group_sum = sum(sample[1] for sample in window)
                cap = group_caps.get(g_name, 4.0)
                weight = group_weights.get(g_name, 1.0)

                # Intra-group non-linear saturation
                capped_group_llr = math.copysign(min(cap, abs(raw_group_sum)), raw_group_sum) * weight
                aggregate_group_llr_sum += capped_group_llr
                group_llr_snapshot[g_name] = capped_group_llr

            # 3. Spatiotemporal Persistence Filter across observation passes
            self._temporal_pass_history[zone_id].append(aggregate_group_llr_sum)
            history = list(self._temporal_pass_history[zone_id])
            positive_passes = sum(1 for val in history if val > 0.5)

            if len(history) >= 2 and (positive_passes / len(history)) >= 0.60:
                c_temporal = thresholds.get("temporal_persistence_bonus", 0.75)
            elif len(history) >= 2 and positive_passes == 0:
                c_temporal = -thresholds.get("temporal_decay_penalty", 0.40)
            else:
                c_temporal = 0.0

            # 4. State Log-Odds Integration: L_t = L_0 + sum(Capped_Group_LLR) + C_temporal
            prior_p0 = self.terrain.compute_prior_prob(cell_x, cell_y, (50, 40))
            l0 = math.log(prior_p0 / (1.0 - prior_p0))
            new_llr = l0 + aggregate_group_llr_sum + c_temporal
            new_llr = max(-15.0, min(15.0, new_llr))
            new_probability = 1.0 / (1.0 + math.exp(-new_llr))

            # 5. Spatiotemporal Utility Maximization
            elapsed_min = (time.time() - self.start_time) / 60.0
            snow_density = sensor_payload.geo.snow_density_kg_m3
            p_survival = self._calculate_survival_probability(elapsed_min, snow_density)
            rescuer_risk = self._calculate_rescuer_hazard(state.slope_deg)
            search_effort = 1.0 + (0.5 * (state.burial_depth_estimate_m or 1.2))

            priority_score = (new_probability * p_survival) / (search_effort + rescuer_risk)

            # 6. Operational Triage
            tau_p1 = thresholds.get("tau_p1", 0.85)
            tau_p2 = thresholds.get("tau_p2", 0.45)

            if new_probability >= tau_p1:
                priority_zone = PriorityZoneEnum.P1
                state.status = ZoneStatusEnum.ACTIVE_SEARCH
            elif new_probability >= tau_p2:
                priority_zone = PriorityZoneEnum.P2
                state.status = ZoneStatusEnum.CANDIDATE
            elif new_probability >= 0.15:
                priority_zone = PriorityZoneEnum.P3
            else:
                priority_zone = PriorityZoneEnum.P4

            if group_name not in state.contributing_evidence_groups:
                state.contributing_evidence_groups.append(group_name)

            if hasattr(sensor_payload, "estimated_depth_m"):
                state.burial_depth_estimate_m = getattr(sensor_payload, "estimated_depth_m")
            elif state.burial_depth_estimate_m is None:
                state.burial_depth_estimate_m = 1.2

            state.confidence_radius_m = max(0.3, 3.0 * (1.0 - new_probability))
            state.current_llr = new_llr
            state.probability = new_probability
            state.priority_score = priority_score
            state.priority_zone = priority_zone
            state.temporal_consistency_score = c_temporal
            state.last_updated_at = datetime.now(timezone.utc)

            directive_issued = None
            if priority_zone == PriorityZoneEnum.P1:
                directive_issued = self._issue_directive_internal(state)

            self.logger.log_inference_event(
                zone_id=zone_id,
                cell_coords=(cell_x, cell_y),
                sensor_payload=sensor_payload.model_dump(mode="json"),
                group_llr_snapshot=group_llr_snapshot,
                posterior_p=new_probability,
                directive_issued=directive_issued.directive_id if directive_issued else None
            )

            return state

    def _calculate_survival_probability(self, elapsed_min: float, snow_density: float) -> float:
        cfg = self.config_loader.config.get("survival_model", {})
        p1_max = cfg.get("phase1_max_minutes", 15.0)
        p1_rate = cfg.get("phase1_survival_rate", 0.92)
        p2_max = cfg.get("phase2_max_minutes", 35.0)

        if elapsed_min <= p1_max:
            return p1_rate
        elif p1_max < elapsed_min <= p2_max:
            fraction = (elapsed_min - p1_max) / (p2_max - p1_max)
            density_mult = 1.0 + (snow_density / 500.0) * 0.2
            return max(0.27, p1_rate - (0.65 * fraction * density_mult))
        else:
            hypo_decay = math.exp(-0.015 * (elapsed_min - p2_max))
            return max(cfg.get("baseline_minimum_survival", 0.03), 0.27 * hypo_decay)

    def _calculate_rescuer_hazard(self, slope_deg: float) -> float:
        if slope_deg < 25.0:
            return 1.0
        elif 25.0 <= slope_deg <= 45.0:
            return 1.0 + 3.5 * (math.sin(math.radians(slope_deg - 25.0) * 4.5) ** 2)
        return 2.0

    def _issue_directive_internal(self, state: GridZoneState) -> Optional[TacticalDirective]:
        for d in self.active_directives:
            if d.target_zone_id == state.zone_id:
                return d

        directive = TacticalDirective(
            directive_id=f"DIR_{state.zone_id}_{int(time.time())}",
            target_zone_id=state.zone_id,
            directive_type=DirectiveTypeEnum.PROBE_EXCAVATE,
            priority_zone=PriorityZoneEnum.P1,
            lat=state.lat,
            lon=state.lon,
            depth_estimate_m=state.burial_depth_estimate_m or 1.2,
            confidence_radius_m=state.confidence_radius_m or 0.7,
            recommended_equipment=["320cm Avalanche Probe", "Avalanche Shovels x4", "Medical Hypothermia Wrap"],
            rationale=f"P1 Triage Threshold Exceeded (P={state.probability*100:.1f}%)"
        )
        self.active_directives.append(directive)
        state.status = ZoneStatusEnum.PROBING
        return directive

    def serialize_summary_sync(self) -> Dict[str, Any]:
        """Synchronous CPU-bound summary extractor for thread-pool offloading."""
        p1 = [z.model_dump() for z in self.grid.values() if z.priority_zone == PriorityZoneEnum.P1]
        p2 = [z.model_dump() for z in self.grid.values() if z.priority_zone == PriorityZoneEnum.P2]
        p3 = [z.model_dump() for z in self.grid.values() if z.priority_zone == PriorityZoneEnum.P3]
        p4_count = len(self.grid) - len(p1) - len(p2) - len(p3)

        return {
            "incident_id": "INCIDENT_HIMALAYA_2026_01",
            "elapsed_seconds": int(time.time() - self.start_time),
            "summary": {
                "p1_count": len(p1),
                "p2_count": len(p2),
                "p3_count": len(p3),
                "p4_count": p4_count
            },
            "directives": [d.model_dump() for d in self.active_directives],
            "high_priority_zones": p1 + p2
        }

    async def get_search_map_summary(self) -> Dict[str, Any]:
        """Asynchronously offloads grid serialization to prevent blocking event loop."""
        async with self._state_lock:
            return await asyncio.to_thread(self.serialize_summary_sync)
```

---

### `backend/telemetry/simulator.py`
```python
"""
Dual Autonomous UAV SAR Telemetry Generator over 500m x 500m Avalanche Grid.
Emits Typed Payloads across Group A, B, and C Modalities.
"""

import math
import time
import random
from typing import Generator, Dict, Any
from backend.schemas.sensors import (
    TransceiverPayload,
    GPRPayload,
    ThermalPayload,
    SeismicAcousticPayload,
    GeospatialContext
)
from backend.schemas.domain import UAVAssetTelemetry


class TelemetrySimulator:
    def __init__(self, origin_lat: float = 34.183900, origin_lon: float = 77.562100):
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon

        # Canonical Ground Truth Targets
        self.true_victims = [
            {"cell_x": 45, "cell_y": 35, "depth_m": 1.3, "has_transceiver": True, "thermal_exposed": False},
            {"cell_x": 70, "cell_y": 60, "depth_m": 2.1, "has_transceiver": False, "thermal_exposed": False},
            {"cell_x": 20, "cell_y": 15, "depth_m": 0.1, "has_transceiver": True, "thermal_exposed": True},
        ]

        self.fault_states: Dict[str, bool] = {
            "TRANSCEIVER_457": False,
            "GPR": False,
            "THERMAL_IR": False,
            "SEISMIC_ACOUSTIC": False
        }
        self.step_count = 0

    def set_sensor_fault(self, sensor_type: str, is_disabled: bool) -> None:
        if sensor_type in self.fault_states:
            self.fault_states[sensor_type] = is_disabled

    def generate_flight_stream(self) -> Generator[Dict[str, Any], None, None]:
        while True:
            self.step_count += 1
            t = self.step_count * 0.4

            # UAV Alpha: South Sector Sweep
            uav1_x = (t * 8.0) % 500.0
            uav1_y = 40.0 + ((int(t * 8.0 / 500.0) * 30.0) % 220.0)
            uav1_lat = self.origin_lat + (uav1_y / 111111.0)
            uav1_lon = self.origin_lon + (uav1_x / (111111.0 * math.cos(math.radians(self.origin_lat))))

            # UAV Bravo: North Sector Sweep
            uav2_x = 500.0 - ((t * 7.5) % 500.0)
            uav2_y = 250.0 + ((int(t * 7.5 / 500.0) * 35.0) % 220.0)
            uav2_lat = self.origin_lat + (uav2_y / 111111.0)
            uav2_lon = self.origin_lon + (uav2_x / (111111.0 * math.cos(math.radians(self.origin_lat))))

            uav_telemetry = [
                UAVAssetTelemetry(
                    asset_id="UAV_ALPHA",
                    label="Alpha (457kHz/IR)",
                    current_lat=uav1_lat,
                    current_lon=uav1_lon,
                    current_alt_m=3862.0,
                    battery_pct=max(10.0, 100.0 - (self.step_count * 0.04)),
                    active_sensor_modalities=["TRANSCEIVER_457", "THERMAL_IR"],
                    heading_deg=90.0 if (int(t * 8.0 / 500.0) % 2 == 0) else 270.0,
                    speed_mps=8.0
                ).model_dump(),
                UAVAssetTelemetry(
                    asset_id="UAV_BRAVO",
                    label="Bravo (GPR/Seismic)",
                    current_lat=uav2_lat,
                    current_lon=uav2_lon,
                    current_alt_m=3858.0,
                    battery_pct=max(10.0, 98.0 - (self.step_count * 0.05)),
                    active_sensor_modalities=["GPR", "SEISMIC_ACOUSTIC"],
                    heading_deg=270.0 if (int(t * 7.5 / 500.0) % 2 == 0) else 90.0,
                    speed_mps=7.5
                ).model_dump()
            ]

            sensor_events = []
            c1_x, c1_y = int(uav1_x / 5.0), int(uav1_y / 5.0)
            c2_x, c2_y = int(uav2_x / 5.0), int(uav2_y / 5.0)

            # UAV Alpha Transceiver Scanning
            if not self.fault_states["TRANSCEIVER_457"]:
                for v in self.true_victims:
                    dist = math.hypot(c1_x - v["cell_x"], c1_y - v["cell_y"])
                    if dist <= 6.0 and v["has_transceiver"]:
                        sensor_events.append({
                            "target_cell": (v["cell_x"], v["cell_y"]),
                            "payload": TransceiverPayload(
                                sensor_id="RF_SNIFFER_01",
                                geo=GeospatialContext(lat=uav1_lat, lon=uav1_lon, altitude_m=3862.0),
                                confidence_score=max(0.2, 0.94 - (dist * 0.12)),
                                flux_line_angle_deg=(dist * 18.0) % 360.0,
                                estimated_distance_m=dist * 5.0
                            )
                        })

            # UAV Bravo GPR Scanning
            if not self.fault_states["GPR"]:
                for v in self.true_victims:
                    dist = math.hypot(c2_x - v["cell_x"], c2_y - v["cell_y"])
                    if dist <= 3.5:
                        sensor_events.append({
                            "target_cell": (v["cell_x"], v["cell_y"]),
                            "payload": GPRPayload(
                                sensor_id="GPR_RADAR_02",
                                geo=GeospatialContext(lat=uav2_lat, lon=uav2_lon, altitude_m=3858.0, snow_density_kg_m3=340.0),
                                confidence_score=max(0.3, 0.91 - (dist * 0.14)),
                                estimated_depth_m=v["depth_m"] + random.gauss(0, 0.08),
                                hyperbola_eccentricity=0.88,
                                dielectric_contrast=7.8
                            )
                        })

            # Transient Noise Pulse
            if random.random() < 0.12:
                noise_x, noise_y = random.randint(0, 99), random.randint(0, 99)
                sensor_events.append({
                    "target_cell": (noise_x, noise_y),
                    "payload": GPRPayload(
                        sensor_id="GPR_RADAR_02",
                        geo=GeospatialContext(lat=self.origin_lat, lon=self.origin_lon, altitude_m=3850.0),
                        confidence_score=0.42,
                        estimated_depth_m=0.8,
                        hyperbola_eccentricity=0.30,
                        dielectric_contrast=2.2
                    )
                })

            yield {
                "uav_telemetry": uav_telemetry,
                "sensor_events": sensor_events
            }
            time.sleep(0.35)
```

---

### `backend/main.py`
```python
"""
FastAPI Production Gateway.
Includes Static Asset Mounting, WebSocket Connection Lifecycle Management with Frame-Drop Backpressure,
and Strict Polymorphic Sensor Dispatch.
"""

import asyncio
from typing import Dict, Any, Set
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config.loader import ConfigLoader
from backend.engine.fusion import FusionEngine
from backend.engine.adapters.registry import AdapterRegistry
from backend.telemetry.simulator import TelemetrySimulator


class ConnectionManager:
    """Manages active WebSocket subscribers with frame-drop backpressure buffers."""
    def __init__(self, max_buffer_size: int = 5):
        self.active_connections: Set[WebSocket] = set()
        self.client_queues: Dict[WebSocket, asyncio.Queue] = {}
        self.max_buffer_size = max_buffer_size

    async def connect(self, websocket: WebSocket) -> asyncio.Queue:
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=self.max_buffer_size)
        self.active_connections.add(websocket)
        self.client_queues[websocket] = q
        return q

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self.client_queues.pop(websocket, None)

    async def broadcast(self, message: Dict[str, Any]):
        for ws, q in list(self.client_queues.items()):
            try:
                if q.full():
                    # Frame-drop policy: discard oldest frame to relieve slow consumer
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(message)
            except Exception:
                self.disconnect(ws)


# Global Engine Infrastructure
config_loader = ConfigLoader()
adapter_registry = AdapterRegistry(config_loader.config)
fusion_engine = FusionEngine(config_loader)
simulator = TelemetrySimulator()
manager = ConnectionManager(max_buffer_size=5)
background_task: asyncio.Task | None = None


async def telemetry_ingestion_loop():
    """Background task streaming synthetic drone data through Bayesian engine."""
    stream = simulator.generate_flight_stream()
    while True:
        try:
            frame = await asyncio.to_thread(next, stream)
            updated_zones = []

            for event in frame["sensor_events"]:
                cx, cy = event["target_cell"]
                payload = event["payload"]

                # Strict Polymorphic Dispatch via AdapterRegistry
                llr, quality = adapter_registry.process_payload(payload)
                state = await fusion_engine.update_cell_evidence(cx, cy, payload, llr, quality)
                updated_zones.append(state.model_dump())

            broadcast_envelope = {
                "type": "telemetry_frame",
                "incident_id": "INCIDENT_HIMALAYA_2026_01",
                "uav_telemetry": frame["uav_telemetry"],
                "updated_zones": updated_zones,
                "directives": [d.model_dump() for d in fusion_engine.active_directives]
            }

            await manager.broadcast(broadcast_envelope)
            await asyncio.sleep(0.35)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in telemetry ingestion loop: {e}")
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task
    background_task = asyncio.create_task(telemetry_ingestion_loop())
    yield
    if background_task:
        background_task.cancel()


app = FastAPI(
    title="AVALANCHE-VLF Tactical Fusion API",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount Static UI Assets
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/frontend", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


class FailureInjectionRequest(BaseModel):
    sensor_type: str
    is_disabled: bool


class ParameterUpdateRequest(BaseModel):
    parameters: Dict[str, Any]
    activated_by: str = "COMMANDER_OVERRIDE"


@app.get("/api/healthz")
async def healthz():
    return {
        "status": "HEALTHY",
        "grid_cells": len(fusion_engine.grid),
        "active_clients": len(manager.active_connections)
    }


@app.get("/api/search-map")
async def get_search_map():
    return await fusion_engine.get_search_map_summary()


@app.post("/api/inject-failure")
async def inject_failure(req: FailureInjectionRequest):
    if req.sensor_type not in ["TRANSCEIVER_457", "GPR", "THERMAL_IR", "SEISMIC_ACOUSTIC"]:
        raise HTTPException(status_code=400, detail="Unsupported sensor type.")
    simulator.set_sensor_fault(req.sensor_type, req.is_disabled)
    return {"status": "SUCCESS", "sensor_type": req.sensor_type, "is_disabled": req.is_disabled}


@app.put("/api/config/fusion-parameters")
async def update_fusion_parameters(req: ParameterUpdateRequest):
    new_ver = config_loader.update_parameters_in_memory(req.parameters, req.activated_by)
    return {"status": "SUCCESS", "new_version": new_ver}


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    q = await manager.connect(websocket)
    try:
        while True:
            # Consume frames from client-specific queue with backpressure protection
            msg = await q.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
```

---

### `frontend/index.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AVALANCHE-VLF | Tactical Command Operations</title>
    <style>
        :root {
            --bg: #0b0e14;
            --panel: #151b23;
            --border: #30363d;
            --text: #e6edf3;
            --muted: #8b949e;
            --p1: #f85149;
            --p2: #d29922;
            --p3: #58a6ff;
            --p4: #3fb950;
            --uav-alpha: #39c5cf;
            --uav-bravo: #bc8cff;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace; }
        body { background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; }
        .brand { font-weight: 700; font-size: 1.1rem; letter-spacing: 1px; display: flex; align-items: center; gap: 10px; }
        .tag { background: #238636; color: #fff; font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; }
        .layout { display: grid; grid-template-columns: 1fr 440px; flex: 1; height: calc(100vh - 58px); }
        .map-viewport { position: relative; background: #030712; display: flex; justify-content: center; align-items: center; border-right: 1px solid var(--border); }
        canvas { background: #06090f; border: 1px solid var(--border); box-shadow: 0 0 40px rgba(0,0,0,0.8); }
        .panel { background: var(--panel); display: flex; flex-direction: column; height: 100%; }
        .panel-heading { padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 0.85rem; font-weight: 700; color: var(--muted); text-transform: uppercase; }
        .triage-list { flex: 1; overflow-y: auto; padding: 12px; }
        .triage-card { background: #0d1117; border-left: 4px solid var(--border); border: 1px solid var(--border); border-radius: 4px; padding: 12px; margin-bottom: 10px; }
        .triage-card.P1 { border-left: 4px solid var(--p1); }
        .triage-card.P2 { border-left: 4px solid var(--p2); }
        .card-header { display: flex; justify-content: space-between; font-weight: 700; margin-bottom: 6px; }
        .card-row { font-size: 0.8rem; color: var(--muted); margin-bottom: 4px; }
        .card-row strong { color: var(--text); }
        .action-tag { font-weight: 700; margin-top: 6px; font-size: 0.8rem; }
        .action-tag.P1 { color: var(--p1); }
        .action-tag.P2 { color: var(--p2); }
        .controls { padding: 14px 16px; border-top: 1px solid var(--border); background: #0d1117; }
        .control-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 0.8rem; }
        .btn-toggle { background: #21262d; border: 1px solid var(--border); color: var(--text); padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 0.75rem; }
        .btn-toggle.fault { background: #b62324; border-color: #f85149; color: #fff; }
        .hud-overlay { position: absolute; bottom: 20px; left: 20px; background: rgba(21, 27, 35, 0.9); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; font-size: 0.75rem; }
        .hud-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    </style>
</head>
<body>
    <header>
        <div class="brand">AVALANCHE-VLF <span class="tag">DEFENSE SAR ENGINE</span></div>
        <div style="font-size: 0.85rem; color: var(--muted);">GRID: 500m × 500m (5m Res) | HIMALAYAN SECTOR-4</div>
    </header>

    <div class="layout">
        <div class="map-viewport">
            <canvas id="radarCanvas" width="680" height="680"></canvas>
            <div class="hud-overlay">
                <div><span class="hud-dot" style="background: var(--p1);"></span> Zone P1: Probe & Excavate (P ≥ 85%)</div>
                <div style="margin-top:4px;"><span class="hud-dot" style="background: var(--p2);"></span> Zone P2: Secondary Radar Scan (45% ≤ P < 85%)</div>
                <div style="margin-top:4px;"><span class="hud-dot" style="background: var(--uav-alpha);"></span> UAV-Alpha (457 kHz Transceiver / IR)</div>
                <div style="margin-top:4px;"><span class="hud-dot" style="background: var(--uav-bravo);"></span> UAV-Bravo (500 MHz GPR / Seismic)</div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-heading">Live Priority Triage Queue</div>
            <div class="triage-list" id="triageQueue"></div>

            <div class="panel-heading">Sensor Fault Injection (Hardware Fallback Verification)</div>
            <div class="controls">
                <div class="control-row">
                    <span>457 kHz RF Beacon Failure (Non-Cooperative)</span>
                    <button class="btn-toggle" id="btnRf" onclick="toggleFault('TRANSCEIVER_457', 'btnRf')">INJECT FAULT</button>
                </div>
                <div class="control-row">
                    <span>500 MHz GPR Failure (Severe Attenuation)</span>
                    <button class="btn-toggle" id="btnGpr" onclick="toggleFault('GPR', 'btnGpr')">INJECT FAULT</button>
                </div>
            </div>
        </div>
    </div>

    <script src="app.js"></script>
</body>
</html>
```

---

### `frontend/app.js`
```javascript
/**
 * AVALANCHE-VLF Tactical Command Dashboard Frontend
 */

const canvas = document.getElementById("radarCanvas");
const ctx = canvas.getContext("2d");
const queueEl = document.getElementById("triageQueue");

const state = {
    gridSize: 100,
    cellSizePx: canvas.width / 100,
    cells: new Map(),
    uavs: [],
    directives: [],
    faults: {
        TRANSCEIVER_457: false,
        GPR: false
    }
};

// Populate default search grid
for (let y = 0; y < state.gridSize; y++) {
    for (let x = 0; x < state.gridSize; x++) {
        state.cells.set(`${x}_${y}`, { x, y, p: 0.01, zone: "P4", depth: null, radius: 1.0, groups: [] });
    }
}

// WebSocket Connection with Auto-Reconnect
const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
const wsEndpoint = `${proto}//${window.location.host}/ws/telemetry`;
let ws;

function initWebSocket() {
    ws = new WebSocket(wsEndpoint);

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "telemetry_frame") {
            state.uavs = msg.uav_telemetry;
            state.directives = msg.directives;

            if (msg.updated_zones) {
                msg.updated_zones.forEach(z => {
                    const key = `${z.cell_x}_${z.cell_y}`;
                    state.cells.set(key, {
                        x: z.cell_x,
                        y: z.cell_y,
                        p: z.probability,
                        zone: z.priority_zone,
                        depth: z.burial_depth_estimate_m,
                        radius: z.confidence_radius_m,
                        groups: z.contributing_evidence_groups || []
                    });
                });
            }
            renderTriageQueue();
            draw();
        }
    };

    ws.onclose = () => {
        setTimeout(initWebSocket, 2000);
    };
}

initWebSocket();

function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Topographic Grid Lines
    ctx.strokeStyle = "#161b22";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= canvas.width; i += state.cellSizePx * 10) {
        ctx.beginPath();
        ctx.moveTo(i, 0); ctx.lineTo(i, canvas.height);
        ctx.moveTo(0, i); ctx.lineTo(canvas.width, i);
        ctx.stroke();
    }

    // Heatmaps
    state.cells.forEach(c => {
        if (c.p >= 0.15) {
            const px = c.x * state.cellSizePx;
            const py = c.y * state.cellSizePx;

            if (c.zone === "P1") {
                ctx.fillStyle = `rgba(248, 81, 73, ${Math.min(0.95, c.p)})`;
                ctx.fillRect(px, py, state.cellSizePx * 2, state.cellSizePx * 2);

                // Uncertainty ring
                ctx.strokeStyle = "#f85149";
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(px + state.cellSizePx, py + state.cellSizePx, (c.radius || 0.8) * 9, 0, Math.PI * 2);
                ctx.stroke();
            } else if (c.zone === "P2") {
                ctx.fillStyle = `rgba(210, 153, 34, ${Math.min(0.75, c.p)})`;
                ctx.fillRect(px, py, state.cellSizePx * 1.5, state.cellSizePx * 1.5);
            } else if (c.zone === "P3") {
                ctx.fillStyle = `rgba(88, 166, 255, ${c.p * 0.5})`;
                ctx.fillRect(px, py, state.cellSizePx, state.cellSizePx);
            }
        }
    });

    // UAV Overlays
    state.uavs.forEach(uav => {
        const px = ((uav.current_lon - 77.562100) * 111111 * Math.cos(34.1839 * Math.PI / 180) / 500.0) * canvas.width;
        const py = ((uav.current_lat - 34.183900) * 111111 / 500.0) * canvas.height;

        const isAlpha = uav.asset_id === "UAV_ALPHA";
        ctx.fillStyle = isAlpha ? "#39c5cf" : "#bc8cff";

        ctx.beginPath();
        ctx.arc(px, py, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = "#ffffff";
        ctx.font = "10px monospace";
        ctx.fillText(uav.label, px + 10, py + 3);
    });
}

function renderTriageQueue() {
    const list = [];
    state.cells.forEach(c => {
        if (c.zone === "P1" || c.zone === "P2") list.push(c);
    });
    list.sort((a, b) => b.p - a.p);

    if (list.length === 0) {
        queueEl.innerHTML = `<div style="color:var(--muted); font-size:0.85rem; text-align:center; padding-top:20px;">Scanning debris sector. No high-priority targets detected...</div>`;
        return;
    }

    queueEl.innerHTML = list.map(c => `
        <div class="triage-card ${c.zone}">
            <div class="card-header">
                <span style="color: ${c.zone === 'P1' ? 'var(--p1)' : 'var(--p2)'}">[${c.zone}] TARGET (${c.x}, ${c.y})</span>
                <span>${(c.p * 100).toFixed(1)}%</span>
            </div>
            <div class="card-row">BURIAL DEPTH (Z): <strong>${c.depth ? c.depth.toFixed(2) + 'm' : '1.20m'}</strong></div>
            <div class="card-row">CONFIDENCE RADIUS: <strong>±${(c.radius || 0.7).toFixed(1)}m</strong></div>
            <div class="card-row">EVIDENCE GROUPS: <strong>${c.groups.join(', ') || 'Pending'}</strong></div>
            <div class="action-tag ${c.zone}">
                DIRECTIVE: ${c.zone === 'P1' ? 'PROBE & EXCAVATE IMMEDIATELY' : 'REQUEST SECONDARY RADAR SCAN'}
            </div>
        </div>
    `).join("");
}

async function toggleFault(sensorType, btnId) {
    state.faults[sensorType] = !state.faults[sensorType];
    const isFaulted = state.faults[sensorType];
    const btn = document.getElementById(btnId);

    btn.className = isFaulted ? "btn-toggle fault" : "btn-toggle";
    btn.innerText = isFaulted ? "FAULT ACTIVE" : "INJECT FAULT";

    await fetch("/api/inject-failure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sensor_type: sensorType, is_disabled: isFaulted })
    });
}
```

---

### `tests/test_fusion.py`
```python
"""
Complete Pytest Suite for AVALANCHE-VLF.
Verifies Multi-Modal Alignment, Non-Cooperative Fallback, Transient Suppression,
Pydantic Validation Constraints, Asynchronous Stress/Concurrency, and Boundary Handlers.
"""

import pytest
import asyncio
from pydantic import ValidationError

from backend.config.loader import ConfigLoader
from backend.engine.fusion import FusionEngine
from backend.engine.adapters.registry import AdapterRegistry
from backend.schemas.sensors import (
    TransceiverPayload,
    GPRPayload,
    ThermalPayload,
    GeospatialContext,
    SensorTypeEnum
)
from backend.schemas.domain import PriorityZoneEnum


@pytest.fixture
def system_fixture():
    config_loader = ConfigLoader()
    engine = FusionEngine(config_loader)
    registry = AdapterRegistry(config_loader.config)
    return engine, registry


@pytest.mark.asyncio
async def test_multimodal_alignment_triggers_p1(system_fixture):
    """TEST 1: 457 kHz Transceiver + GPR multi-modal alignment triggers P1 directive."""
    engine, registry = system_fixture
    cx, cy = 45, 35

    # 1. Transceiver ping
    rf_payload = TransceiverPayload(
        sensor_id="RF_TEST_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
        confidence_score=0.92,
        flux_line_angle_deg=45.0,
        estimated_distance_m=2.0
    )
    llr_rf, q_rf = registry.process_payload(rf_payload)
    await engine.update_cell_evidence(cx, cy, rf_payload, llr_rf, q_rf)

    # 2. GPR confirmation
    gpr_payload = GPRPayload(
        sensor_id="GPR_TEST_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0, snow_density_kg_m3=320.0),
        confidence_score=0.90,
        estimated_depth_m=1.3,
        hyperbola_eccentricity=0.90,
        dielectric_contrast=8.0
    )
    llr_gpr, q_gpr = registry.process_payload(gpr_payload)
    state = await engine.update_cell_evidence(cx, cy, gpr_payload, llr_gpr, q_gpr)

    assert state.probability >= 0.85
    assert state.priority_zone == PriorityZoneEnum.P1
    assert len(engine.active_directives) >= 1
    assert "GROUP_A_ELECTRONIC" in state.contributing_evidence_groups
    assert "GROUP_B_SUBSURFACE" in state.contributing_evidence_groups


@pytest.mark.asyncio
async def test_non_cooperative_victim_gpr_fallback(system_fixture):
    """TEST 2: Non-cooperative victim without RF beacon successfully elevates via GPR passes."""
    engine, registry = system_fixture
    cx, cy = 70, 60

    for _ in range(3):
        gpr_payload = GPRPayload(
            sensor_id="GPR_TEST_01",
            geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0, snow_density_kg_m3=300.0),
            confidence_score=0.88,
            estimated_depth_m=2.1,
            hyperbola_eccentricity=0.89,
            dielectric_contrast=7.5
        )
        llr_gpr, q_gpr = registry.process_payload(gpr_payload)
        state = await engine.update_cell_evidence(cx, cy, gpr_payload, llr_gpr, q_gpr)

    assert state.probability >= 0.60
    assert state.priority_zone in [PriorityZoneEnum.P1, PriorityZoneEnum.P2]
    assert "GROUP_A_ELECTRONIC" not in state.contributing_evidence_groups


@pytest.mark.asyncio
async def test_transient_noise_temporal_suppression(system_fixture):
    """TEST 3: Transient false-positive pulse is suppressed by temporal decay filter."""
    engine, registry = system_fixture
    cx, cy = 10, 10

    # False-positive transient pulse
    noise_payload = GPRPayload(
        sensor_id="GPR_NOISE",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3850.0),
        confidence_score=0.40,
        estimated_depth_m=0.8,
        hyperbola_eccentricity=0.30,
        dielectric_contrast=2.0
    )
    llr, q = registry.process_payload(noise_payload)
    await engine.update_cell_evidence(cx, cy, noise_payload, llr, q)

    # Subsequent empty passes
    clear_payload = GPRPayload(
        sensor_id="GPR_NOISE",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3850.0),
        confidence_score=0.01,
        estimated_depth_m=0.8,
        hyperbola_eccentricity=0.05,
        dielectric_contrast=1.0
    )
    for _ in range(3):
        state = await engine.update_cell_evidence(cx, cy, clear_payload, -2.0, 0.9)

    assert state.probability < 0.20
    assert state.priority_zone == PriorityZoneEnum.P4


def test_pydantic_schema_validation_rejection():
    """TEST 4: Strict validation bounds correctly reject corrupted/out-of-bounds inputs."""
    # Invalid Latitude
    with pytest.raises(ValidationError):
        GeospatialContext(lat=95.0, lon=77.0, altitude_m=3800.0)

    # Invalid Snow Density (negative)
    with pytest.raises(ValidationError):
        GeospatialContext(lat=34.0, lon=77.0, altitude_m=3800.0, snow_density_kg_m3=-50.0)

    # Invalid Transceiver Distance (> 100m)
    with pytest.raises(ValidationError):
        TransceiverPayload(
            sensor_id="RF_INVALID",
            geo=GeospatialContext(lat=34.0, lon=77.0, altitude_m=3800.0),
            confidence_score=0.8,
            flux_line_angle_deg=45.0,
            estimated_distance_m=150.0
        )


@pytest.mark.asyncio
async def test_concurrent_stress_and_lock_safety(system_fixture):
    """TEST 5: Asynchronous stress test verifying state lock safety under concurrent updates."""
    engine, registry = system_fixture

    async def simulate_sensor_worker(worker_id: int, cx: int, cy: int):
        for i in range(15):
            payload = GPRPayload(
                sensor_id=f"GPR_WORKER_{worker_id}",
                geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
                confidence_score=0.75,
                estimated_depth_m=1.0,
                hyperbola_eccentricity=0.8,
                dielectric_contrast=5.0
            )
            llr, q = registry.process_payload(payload)
            await engine.update_cell_evidence(cx, cy, payload, llr, q)
            await asyncio.sleep(0.005)

    # Dispatch 10 concurrent coroutines updating overlapping cells
    tasks = [simulate_sensor_worker(i, 50, 50) for i in range(10)]
    await asyncio.gather(*tasks)

    state = engine.grid["cell_50_50"]
    assert state.probability > 0.85
    assert not math.isnan(state.current_llr)


@pytest.mark.asyncio
async def test_spatial_boundary_enforcement(system_fixture):
    """TEST 6: Out-of-bounds coordinates raise explicit KeyError exceptions."""
    engine, registry = system_fixture
    payload = GPRPayload(
        sensor_id="GPR_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3850.0),
        confidence_score=0.8,
        estimated_depth_m=1.0,
        hyperbola_eccentricity=0.8,
        dielectric_contrast=5.0
    )
    llr, q = registry.process_payload(payload)

    with pytest.raises(KeyError):
        await engine.update_cell_evidence(100, 100, payload, llr, q)
```

---

### `HANDOFF.md`
```markdown
# AVALANCHE-VLF: Operational Handoff & Technical Manual
**Defence Research & Development Organisation (DRDO / DGRE)**  
**Project:** Time-Aware Adaptive Multi-Modal Sensor Fusion Engine for Buried Victim Localization

---

## 1. System Architecture Overview

AVALANCHE-VLF operates as a hybrid hierarchical intelligence engine. Edge perception models running on UAVs (YOLO, 1D-CNN radar hyperbola detectors) extract features locally and transmit strongly-typed probabilistic telemetry across a MANET/LoRa mesh network. The central command server fuses evidence via a Recursive Bayesian Log-Odds Occupancy Grid Map combined with a Physiological Utility Maximization function.

```
[ Edge UAV Ingestion ]
 ├── UAV-Alpha (457 kHz Transceiver + LWIR Thermal IR)
 └── UAV-Bravo (500 MHz UWB GPR + Micro-Seismic Acoustic)
        │
        ▼ (Typed Pydantic Telemetry via ZeroMQ / LoRaWAN Mesh)
[ Central Tactical Command Server ]
 ├── Dynamic Config Loader (Thread-Safe Parameter Management)
 ├── Adapter Registry (Polymorphic Sensor Likelihood & Quality Dispatch)
 ├── Recursive Bayesian Fusion Engine (Asyncio State Lock + Aggregate Group Capping)
 └── Structured Fine-Tuning Event Logger (JSONL / Parquet Stream)
        │
        ├──► (FastAPI REST: /api/search-map, /api/inject-failure, /api/config)
        └──► (FastAPI WebSocket: /ws/telemetry @ 10Hz Backpressure Stream)
              │
              ▼
[ Tactical Command PWA Dashboard ]
 (2.5D Topographic Canvas Grid + Triage Action Queue + Fault Injection Controls)
```

---

## 2. Mathematical Decision Formulation

### 2.1 Log-Likelihood Ratio (LLR) Update Rule
For search cell $i$ at time step $t$:
$$L_t(i) = L_0(i) + \sum_{g \in \{A,B,C\}} w_g \cdot \Lambda_g(i, t) + C_{\text{temporal}}(i, t)$$

Where:
* $L_0(i) = \ln\left(\frac{P_0(i)}{1 - P_0(i)}\right)$ is the spatial prior incorporating DEM slope angle, flow vectors, and Last Known Position (LKP).
* $\Lambda_g(i, t) = \operatorname{sign}\left(\sum_{k \in \mathcal{W}} \text{LLR}_{g, k}\right) \cdot \min\left(\Gamma_g, \left|\sum_{k \in \mathcal{W}} \text{LLR}_{g, k}\right|\right)$ is the **Aggregate Intra-Group Capped Evidence** across observation window $\mathcal{W}$.
* $w_g(q_g)$ is the environmental quality attenuation factor ($q_{\text{snow}}, q_{\text{EMI}}, q_{\text{wind}}$).
* $C_{\text{temporal}}$ is the spatiotemporal persistence filter rewarding stationary signals across multiple UAV scanning passes.

### 2.2 Decision Utility Function
$$U(i, t) = \frac{P(H_i \mid \mathbf{Z}_{1:t}) \cdot S(t_{\text{elapsed}}, \rho_{\text{snow}})}{E_{\text{traverse}}(i) + E_{\text{excavate}}(d_i) + R_{\text{hazard}}(\theta_i)}$$

* $S(t, \rho)$ models the biophysical triple-exponential survival curve (Phase 1: 0–15 min, Phase 2: 15–35 min rapid asphyxiation, Phase 3: hypothermia plateau).
* $R_{\text{hazard}}(\theta_i)$ penalizes rescuer exposure in high secondary avalanche risk zones ($25^\circ \le \theta_i \le 45^\circ$).

---

## 3. Sensor Evidence Hierarchy & Evidence Grouping

| Evidence Group | Modality | Primary Physics / Metric | Quality Attenuation Model $q_g$ |
| :--- | :--- | :--- | :--- |
| **Group A: Electronic** | 457 kHz Beacon | Electromagnetic induction (flux line) | $q_{\text{emi}} \cdot (1 / (1 + (d/d_{\max})^2))$ |
| | RECCO | Harmonic radar cross-section | $q_{\text{emi}} \cdot \min(1.0, \text{RCS} / 0.5)$ |
| | Cellular IMSI | LTE/5G RF uplink sniff | Timing Advance & Frequency SNR |
| **Group B: Subsurface** | UWB GPR | Dielectric permittivity anomaly | $\exp(-\kappa \cdot \rho_{\text{snow}} \cdot d) \cdot \text{Eccentricity}$ |
| | Micro-Seismic | Acoustic geophone ping | $\text{Sigmoid}(\text{SNR}) \cdot (1 / (1 + \text{Noise}_{\text{ambient}}))$ |
| **Group C: Surface** | Thermal IR | LWIR surface temperature delta | $\exp(-15.0 \cdot d) \cdot (1 / (1 + v_{\text{wind}}))$ |
| | RGB Visual | Optical bounding box / equipment | Color match & shadow anomaly |

---

## 4. REST & WebSocket API Specification

### REST Endpoints
* `GET /api/healthz`: Liveness and readiness probe.
* `GET /api/search-map`: Returns serialized high-priority zones (P1/P2) and active directives.
* `POST /api/inject-failure`: Simulates hardware degradation live (`{"sensor_type": "TRANSCEIVER_457", "is_disabled": true}`).
* `PUT /api/config/fusion-parameters`: Dynamic parameter hot-swap without service restart.

### WebSocket Protocol (`/ws/telemetry`)
Frames are broadcast at 10 Hz with client-level frame-drop backpressure policies.
```json
{
  "type": "telemetry_frame",
  "incident_id": "INCIDENT_HIMALAYA_2026_01",
  "uav_telemetry": [
    {
      "asset_id": "UAV_ALPHA",
      "label": "Alpha (457kHz/IR)",
      "current_lat": 34.1843,
      "current_lon": 77.5629,
      "current_alt_m": 3862.0,
      "battery_pct": 94.5,
      "active_sensor_modalities": ["TRANSCEIVER_457", "THERMAL_IR"],
      "heading_deg": 90.0,
      "speed_mps": 8.0
    }
  ],
  "updated_zones": [
    {
      "zone_id": "cell_45_35",
      "cell_x": 45,
      "cell_y": 35,
      "lat": 34.1842,
      "lon": 77.5625,
      "probability": 0.912,
      "priority_score": 0.784,
      "priority_zone": "P1",
      "burial_depth_estimate_m": 1.3,
      "confidence_radius_m": 0.6,
      "contributing_evidence_groups": ["GROUP_A_ELECTRONIC", "GROUP_B_SUBSURFACE"]
    }
  ],
  "directives": [
    {
      "directive_id": "DIR_cell_45_35_1723630000",
      "target_zone_id": "cell_45_35",
      "directive_type": "PROBE_EXCAVATE",
      "priority_zone": "P1",
      "depth_estimate_m": 1.3,
      "confidence_radius_m": 0.6,
      "recommended_equipment": ["320cm Avalanche Probe", "Avalanche Shovels x4"]
    }
  ]
}
```

---

## 5. Deployment & Execution Environment

### 5.1 Environment Variables
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `FUSION_CONFIG_PATH` | `config/fusion_parameters.yaml` | Absolute or relative path to active parameter YAML |
| `GRID_DIMENSIONS` | `500,500,5.0` | Search grid dimensions: `width_m,height_m,cell_size_m` |
| `SENSOR_TIMEOUT_MS` | `3000` | Stale sensor detection threshold |
| `WS_BACKPRESSURE_QUEUE_SIZE` | `5` | Maximum frame buffer per WebSocket subscriber |

### 5.2 Hardware Specifications
* **Command Post Server:** Rugged field laptop or rackmount server (Intel i7/Xeon or AMD Ryzen 7, 16GB RAM, Ubuntu 22.04 LTS).
* **UAV Edge Compute:** NVIDIA Jetson Orin Nano / Orin NX (Ingesting GPR & Optical feeds, running YOLO/1D-CNN feature extractors).
* **Network Layer:** Mobile Ad-Hoc Network (MANET) or LoRaWAN 868/915 MHz point-to-multipoint radio mesh.

---

## 6. Real-World Hardware Adapter Integration Guide

To integrate live military hardware (e.g., DRDO Airborne GPR):

1. **Subclass BaseSensorAdapter:**
   ```python
   from backend.engine.adapters.base import BaseSensorAdapter
   from backend.schemas.sensors import GPRPayload, GeospatialContext

   class DRDOAirborneGPRAdapter(BaseSensorAdapter):
       def parse_raw(self, raw_binary_frame: bytes) -> GPRPayload:
           # Unpack custom military binary C-struct over serial / UDP
           depth, eccentricity, rcs = unpack_radar_binary(raw_binary_frame)
           return GPRPayload(
               sensor_id="DRDO_GPR_POD_01",
               geo=GeospatialContext(...),
               confidence_score=0.92,
               estimated_depth_m=depth,
               hyperbola_eccentricity=eccentricity,
               dielectric_contrast=rcs
           )

       def evaluate_quality(self, payload: GPRPayload) -> float:
           return calculate_snow_radar_q(payload)
   ```

2. **Register in `backend/engine/adapters/registry.py`:**
   Bind the new adapter instance to `SensorTypeEnum.GPR` inside `AdapterRegistry`.

---

## 7. Field Fine-Tuning & Parameter Calibration Procedure

1. **Run Mission Operations:** Telemetry frames and issued directives are logged to `logs/sar_mission_*.jsonl`.
2. **Execute Post-Mission Ground-Truth Calibration:**
   Following rescue verification (probing/excavation depth and confirmed victim status), execute the parameter optimization pipeline to minimize cross-entropy loss against recorded telemetry:
   ```bash
   python -m scripts.calibrate_parameters \
     --mission-logs logs/sar_mission_20260814.jsonl \
     --ground-truth data/ground_truth_verification.csv \
     --output config/fusion_parameters.v2.yaml
   ```
3. **Hot-Swap Live Parameters:**
   Send an HTTP `PUT` request to `/api/config/fusion-parameters` with the contents of the newly generated YAML configuration. The running system reloads weights dynamically.
```

---

## 8. Verification & Execution Walkthrough

### 1. Initialize Python 3.12 Virtual Environment
```bash
python3.12 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pydantic pyyaml numpy pytest websockets httpx
```

### 2. Run Comprehensive Test Suite
```bash
pytest tests/test_fusion.py -v
```

### 3. Launch Tactical Command Server
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Access Tactical Operations Dashboard
Open your browser and navigate to:
```
http://localhost:8000/frontend/index.html
```