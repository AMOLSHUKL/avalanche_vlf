"""
Concrete Adapter for Group B Subsurface Seismic & Micro-Acoustic Life-Sign Sensing.
"""

import math
from typing import Any

from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import SeismicAcousticPayload, SensorTypeEnum


class SeismicAdapter(BaseSensorAdapter):
    def __init__(self, config_loader: ConfigLoader):
        super().__init__(SensorTypeEnum.SEISMIC_ACOUSTIC.value, config_loader)

    def parse_raw(self, raw_input: Any) -> SeismicAcousticPayload:
        if isinstance(raw_input, SeismicAcousticPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return SeismicAcousticPayload(**raw_input)
        raise ValueError("Invalid payload format for SeismicAdapter")

    def evaluate_quality(self, payload: SeismicAcousticPayload) -> float:
        noise_penalty = self.config_loader.config.get("environmental_attenuation", {}).get("acoustic_noise_floor_penalty", 0.030)
        ambient_noise = payload.geo.acoustic_noise_db
        snr = payload.signal_to_noise_ratio_db

        q_snr = 1.0 / (1.0 + math.exp(-0.1 * (snr - 5.0)))
        q_ambient = 1.0 / (1.0 + max(0.0, ambient_noise - 40.0) * noise_penalty)
        pattern_mult = 1.25 if payload.impulse_pattern_detected else 0.85

        return max(0.05, min(1.0, q_snr * q_ambient * pattern_mult))
