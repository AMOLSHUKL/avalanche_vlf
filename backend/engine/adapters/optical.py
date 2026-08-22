"""
Concrete Adapter for Group C Surface High-Resolution RGB Visual Sensing.
"""

from typing import Any
from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import RGBPayload, SensorTypeEnum


class OpticalAdapter(BaseSensorAdapter):
    def __init__(self, config_loader: ConfigLoader):
        super().__init__(SensorTypeEnum.RGB_VISUAL.value, config_loader)

    def parse_raw(self, raw_input: Any) -> RGBPayload:
        if isinstance(raw_input, RGBPayload):
            return raw_input
        if isinstance(raw_input, dict):
            return RGBPayload(**raw_input)
        raise ValueError("Invalid payload format for OpticalAdapter")

    def evaluate_quality(self, payload: RGBPayload) -> float:
        q_color = max(0.1, payload.equipment_color_match_score)
        q_area = min(1.0, payload.bounding_box_area_ratio * 20.0)
        shadow_boost = 1.15 if payload.shadow_anomaly_detected else 0.90

        return max(0.05, min(1.0, q_color * q_area * shadow_boost))