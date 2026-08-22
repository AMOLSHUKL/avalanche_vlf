"""
Tactical Domain State Models and SAR Protocol Envelopes with Military Geotagging (MGRS),
Operational Phase Tracking, Marker Releases, and Safe Responder Approach Vectors.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class MissionPhaseEnum(str, Enum):
    ALERT_PREFLIGHT = "ALERT_PREFLIGHT"
    LAWNMOWER_SURFACE_SCAN = "LAWNMOWER_SURFACE_SCAN"
    DEEP_RADAR_SCAN = "DEEP_RADAR_SCAN"
    TARGET_VERIFICATION_MARKER_DROP = "TARGET_VERIFICATION_MARKER_DROP"
    SAR_VECTORING = "SAR_VECTORING"


class PriorityZoneEnum(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


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
    zone_id: str
    cell_x: int = Field(..., ge=0, description="Discrete grid coordinate X")
    cell_y: int = Field(..., ge=0, description="Discrete grid coordinate Y")
    lat: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude")
    mgrs_coord: str = Field(default="", description="Standard Military Grid Reference System (MGRS) coordinate")
    elevation_m: float = Field(..., ge=0.0, le=9000.0, description="Terrain surface elevation AMSL")
    slope_deg: float = Field(..., ge=0.0, le=90.0, description="Local terrain slope inclination")
    current_llr: float = Field(default=0.0, ge=-50.0, le=50.0, description="Cumulative Bayesian Log-Odds ratio")
    probability: float = Field(default=0.0, ge=0.0, le=1.0, description="Posterior occupancy probability")
    priority_score: float = Field(default=0.0, ge=0.0, description="Biophysical decision utility score")
    priority_zone: PriorityZoneEnum = PriorityZoneEnum.P4
    status: ZoneStatusEnum = ZoneStatusEnum.UNSEEN
    burial_depth_estimate_m: Optional[float] = Field(default=None, ge=0.0, le=25.0, description="Estimated burial depth Z")
    confidence_radius_m: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Estimated spatial uncertainty radius")
    contributing_evidence_groups: List[str] = Field(default_factory=list, description="List of contributing evidence groups")
    temporal_consistency_score: float = Field(default=0.0, ge=-10.0, le=10.0, description="Multi-pass persistence bonus/penalty")
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TacticalDirective(BaseModel):
    directive_id: str
    target_zone_id: str
    directive_type: DirectiveTypeEnum
    priority_zone: PriorityZoneEnum
    lat: float = Field(..., ge=-90.0, le=90.0, description="Target Latitude WGS84")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Target Longitude WGS84")
    mgrs_coord: str = Field(default="", description="Target MGRS coordinate string")
    depth_estimate_m: float = Field(..., ge=0.0, le=25.0, description="Target burial depth Z")
    confidence_radius_m: float = Field(..., ge=0.0, le=50.0, description="Spatial uncertainty radius")
    approach_azimuth_deg: float = Field(
        default=0.0,
        ge=0.0,
        le=360.0,
        description="Recommended responder approach heading avoiding secondary avalanche fall-lines"
    )
    marker_deployed: bool = Field(
        default=False,
        description="Flag indicating physical LED/RF homing chip release over target"
    )
    marker_frequency_mhz: Optional[float] = Field(
        default=None,
        ge=100.0,
        le=6000.0,
        description="Deployed RF beacon transmission frequency"
    )
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recommended_equipment: List[str] = Field(default_factory=list, description="Recommended probing and excavation equipment")
    rationale: str = Field(..., description="Operational rationale and sensor evidence justification")


class UAVAssetTelemetry(BaseModel):
    asset_id: str
    label: str
    current_lat: float = Field(..., ge=-90.0, le=90.0)
    current_lon: float = Field(..., ge=-180.0, le=180.0)
    current_alt_m: float = Field(..., ge=0.0, le=9000.0)
    battery_pct: float = Field(..., ge=0.0, le=100.0)
    active_sensor_modalities: List[str]
    heading_deg: float = Field(..., ge=0.0, le=360.0)
    speed_mps: float = Field(..., ge=0.0, le=100.0)
    last_telemetry_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WSEnvelope(BaseModel, Generic[T]):
    type: str
    incident_id: str
    mission_phase: Optional[MissionPhaseEnum] = Field(
        default=MissionPhaseEnum.LAWNMOWER_SURFACE_SCAN,
        description="Active 5-phase SAR operational lifecycle state"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: T