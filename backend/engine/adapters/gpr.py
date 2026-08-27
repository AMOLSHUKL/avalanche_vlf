"""
Concrete Adapter for Group B Subsurface Ground Penetrating Radar (GPR).
"""

import math
from typing import Any

from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import GPRPayload, SensorTypeEnum


class SimulatedGPRAdapter(BaseSensorAdapter):
    def __init__(self, config_loader: ConfigLoader):
        super().__init__(SensorTypeEnum.GPR.value, config_loader)

    def parse_raw(self, raw_input: Any) -> GPRPayload:
        if isinstance(raw_input, GPRPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return GPRPayload(**raw_input)
        raise ValueError("Invalid payload format for SimulatedGPRAdapter")

    def evaluate_quality(self, payload: GPRPayload) -> float:
        density = payload.geo.snow_density_kg_m3
        depth = payload.estimated_depth_m
        attenuation_params = self.config_loader.config.get("environmental_attenuation", {})
        kappa = attenuation_params.get("snow_water_equivalent_penalty_factor", 0.0028)
        # Dielectric absorption through wet snowpack
        q_env = math.exp(-kappa * (density / 100.0) * depth)
        # For positive detections, hyperbola eccentricity verifies point scatterer fit.
        # For negative scans (absence of target), snowpack dielectric transparency governs quality.
        q_radar = payload.hyperbola_eccentricity if payload.confidence_score >= 0.5 else 1.0
        return max(0.05, min(1.0, q_env * q_radar))
