"""
Pydantic v2 Sensor Payload Contracts with Physical Validation Bounds,
Micro-Doppler Respiration Signatures, Dielectric Permittivity, and UTC Enforcement.
"""
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceGroupEnum(StrEnum):
    GROUP_A_ELECTRONIC = "GROUP_A_ELECTRONIC"
    GROUP_B_SUBSURFACE = "GROUP_B_SUBSURFACE"
    GROUP_C_SURFACE = "GROUP_C_SURFACE"


class SensorTypeEnum(StrEnum):
    TRANSCEIVER_457 = "TRANSCEIVER_457"
    RECCO = "RECCO"
    MOBILE_RF = "MOBILE_RF"
    GPR = "GPR"
    SEISMIC_ACOUSTIC = "SEISMIC_ACOUSTIC"
    THERMAL_IR = "THERMAL_IR"
    RGB_VISUAL = "RGB_VISUAL"


class GeospatialContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees WGS84")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees WGS84")
    altitude_m: float = Field(..., ge=0.0, le=9000.0, description="Altitude AMSL in meters")
    snow_depth_est_m: float = Field(default=1.5, ge=0.0, le=25.0, description="Estimated snowpack thickness")
    snow_density_kg_m3: float = Field(default=350.0, ge=50.0, le=850.0, description="Bulk snow density")
    ambient_temp_c: float = Field(default=-10.0, ge=-60.0, le=40.0, description="Ambient air temperature")
    emi_noise_floor_dbm: float = Field(default=-105.0, ge=-150.0, le=-20.0, description="RF background noise floor")
    acoustic_noise_db: float = Field(default=30.0, ge=0.0, le=140.0, description="Ambient seismic/acoustic noise")
    wind_speed_mps: float = Field(default=5.0, ge=0.0, le=75.0, description="Surface wind velocity")


class BaseSensorPayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sensor_id: str = Field(..., min_length=2, max_length=64)
    sensor_type: SensorTypeEnum
    evidence_group: EvidenceGroupEnum
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    geo: GeospatialContext
    raw_signal_strength_dbm: float | None = Field(None, ge=-150.0, le=30.0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)

    @field_validator("timestamp")
    @classmethod
    def enforce_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class TransceiverPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.TRANSCEIVER_457
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_A_ELECTRONIC
    flux_line_angle_deg: float = Field(..., ge=0.0, le=360.0, description="Magnetic flux induction angle")
    estimated_distance_m: float = Field(..., ge=0.0, le=100.0, description="Estimated range along flux line")
    is_multi_victim_signal: bool = Field(default=False, description="Flag indicating overlapping beacon pulses")


class RECCOPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.RECCO
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_A_ELECTRONIC
    harmonic_return_amplitude: float = Field(..., ge=0.0, le=100.0, description="Non-linear harmonic return signal")
    radar_cross_section_m2: float = Field(default=0.1, ge=0.0, le=10.0, description="Estimated target RCS")


class MobileRFPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.MOBILE_RF
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_A_ELECTRONIC
    imsi_hash: str | None = Field(None, max_length=64, description="Anonymized SHA-256 subscriber identifier")
    channel_frequency_mhz: float = Field(..., ge=700.0, le=6000.0, description="Uplink carrier frequency")
    timing_advance_m: float | None = Field(None, ge=0.0, le=5000.0, description="Cellular propagation distance")


class GPRPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.GPR
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_B_SUBSURFACE
    estimated_depth_m: float = Field(..., ge=0.0, le=15.0, description="Radar two-way travel time depth estimate")
    hyperbola_eccentricity: float = Field(..., ge=0.0, le=1.0, description="B-scan point scatterer curvature fit")
    dielectric_contrast: float = Field(..., ge=1.0, le=80.0, description="Reflection coefficient intensity")
    relative_permittivity: float = Field(
        default=50.0,
        ge=1.0,
        le=85.0,
        description="Calculated target dielectric permittivity (Human muscle/tissue Er ~ 50-55, Rock Er ~ 6-9, Snow Er ~ 3.2)"
    )
    micro_doppler_frequency_hz: float | None = Field(
        default=None,
        ge=0.1,
        le=1.0,
        description="Extracted chest wall displacement frequency (Human respiration band: 0.1 - 1.0 Hz)"
    )
    respiration_locked: bool = Field(
        default=False,
        description="Flag indicating stationary micro-Doppler periodic respiration lock"
    )
    void_anomaly_flag: bool = Field(default=False, description="Flag indicating potential air pocket survival void")


class SeismicAcousticPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.SEISMIC_ACOUSTIC
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_B_SUBSURFACE
    dominant_frequency_hz: float = Field(..., ge=0.5, le=500.0, description="Peak acoustic spectral frequency")
    signal_to_noise_ratio_db: float = Field(..., ge=-20.0, le=80.0, description="Geophone signal-to-noise ratio")
    impulse_pattern_detected: bool = Field(default=False, description="Periodic tapping or calling pattern detection")


class ThermalPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.THERMAL_IR
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_C_SURFACE
    temperature_delta_c: float = Field(..., ge=-40.0, le=50.0, description="Differential surface thermal signature")
    pixel_area_count: int = Field(..., ge=1, le=1000000, description="Thermal anomaly blob pixel count")
    surface_clue_detected: bool = Field(default=False, description="Flag indicating direct snow surface thermal vent")


class RGBPayload(BaseSensorPayload):
    sensor_type: SensorTypeEnum = SensorTypeEnum.RGB_VISUAL
    evidence_group: EvidenceGroupEnum = EvidenceGroupEnum.GROUP_C_SURFACE
    bounding_box_area_ratio: float = Field(..., ge=0.0, le=1.0, description="Visual anomaly bounding box coverage")
    equipment_color_match_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Known gear/fabric HSV match")
    shadow_anomaly_detected: bool = Field(default=False, description="Crevasse or snow disturbance shadow pattern")
