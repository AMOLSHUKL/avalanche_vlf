"""
Concrete Adapter for Group C Surface Long-Wave Infrared (LWIR) Thermal Imaging.
"""

import math
from typing import Any

from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import SensorTypeEnum, ThermalPayload


class ThermalAdapter(BaseSensorAdapter):
    def __init__(self, config_loader: ConfigLoader):
        super().__init__(SensorTypeEnum.THERMAL_IR.value, config_loader)

    def parse_raw(self, raw_input: Any) -> ThermalPayload:
        if isinstance(raw_input, ThermalPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return ThermalPayload(**raw_input)
        raise ValueError("Invalid payload format for ThermalAdapter")

    def evaluate_quality(self, payload: ThermalPayload) -> float:
        wind_factor = self.config_loader.config.get("environmental_attenuation", {}).get("wind_dispersion_penalty_factor", 0.022)
        wind_speed = payload.geo.wind_speed_mps
        snow_depth = payload.geo.snow_depth_est_m

        # Calibrated thermal skin-depth attenuation
        if payload.surface_clue_detected:
            q_depth = 0.95
        else:
            q_depth = math.exp(-3.5 * snow_depth)

        q_wind = 1.0 / (1.0 + (wind_speed * wind_factor))
        delta_temp_score = min(1.0, max(0.1, abs(payload.temperature_delta_c) / 8.0))

        return max(0.01, min(1.0, q_depth * q_wind * delta_temp_score))
