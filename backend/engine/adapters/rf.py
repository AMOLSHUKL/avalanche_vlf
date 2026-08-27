"""
Polymorphic Adapter for Group A Electronic Sensors.
"""

from typing import Any

from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import (
    BaseSensorPayload,
    MobileRFPayload,
    RECCOPayload,
    SensorTypeEnum,
    TransceiverPayload,
)


class SimulatedRFAdapter(BaseSensorAdapter):
    def __init__(self, sensor_type: SensorTypeEnum, config_loader: ConfigLoader):
        super().__init__(sensor_type.value, config_loader)
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
        raise ValueError(f"Invalid payload format for {self.sensor_type}")

    def evaluate_quality(self, payload: BaseSensorPayload) -> float:
        cfg = self.config_loader.config
        emi_noise = payload.geo.emi_noise_floor_dbm
        penalty_factor = cfg.get("environmental_attenuation", {}).get("emi_noise_penalty_factor", 0.018)
        emi_delta = max(0.0, emi_noise - (-105.0))
        q_emi = 1.0 / (1.0 + (penalty_factor * emi_delta))

        if isinstance(payload, TransceiverPayload):
            dist = payload.estimated_distance_m
            max_range = self.config_loader.get_sensor_priors("TRANSCEIVER_457").get("max_range_m", 50.0)
            # 457 kHz induction operates in the magnetic near field, where
            # flux-line coupling falls off as r^-3 (dipole regime), not the
            # far-field r^-2 of radiating systems.
            q_dist = 1.0 / (1.0 + (dist / (max_range * 0.5)) ** 3)
            return max(0.05, min(1.0, q_emi * q_dist))

        elif isinstance(payload, RECCOPayload):
            rcs_weight = min(1.0, payload.radar_cross_section_m2 / 0.5)
            return max(0.05, min(1.0, q_emi * rcs_weight))

        elif isinstance(payload, MobileRFPayload):
            ta_penalty = 1.0 if payload.timing_advance_m is None else (1.0 / (1.0 + (payload.timing_advance_m / 500.0)))
            return max(0.05, min(1.0, q_emi * ta_penalty))

        return max(0.05, min(1.0, q_emi))
