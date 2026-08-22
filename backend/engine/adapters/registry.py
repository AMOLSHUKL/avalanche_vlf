"""
Polymorphic Adapter Registry Bound to Dynamic ConfigLoader.
"""

from typing import Dict
from backend.config.loader import ConfigLoader
from backend.schemas.sensors import SensorTypeEnum, BaseSensorPayload
from backend.engine.adapters.base import BaseSensorAdapter
from backend.engine.adapters.rf import SimulatedRFAdapter
from backend.engine.adapters.gpr import SimulatedGPRAdapter
from backend.engine.adapters.seismic import SeismicAdapter
from backend.engine.adapters.thermal import ThermalAdapter
from backend.engine.adapters.optical import OpticalAdapter


class AdapterRegistry:
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self._adapters: Dict[SensorTypeEnum, BaseSensorAdapter] = {
            SensorTypeEnum.TRANSCEIVER_457: SimulatedRFAdapter(SensorTypeEnum.TRANSCEIVER_457, config_loader),
            SensorTypeEnum.RECCO: SimulatedRFAdapter(SensorTypeEnum.RECCO, config_loader),
            SensorTypeEnum.MOBILE_RF: SimulatedRFAdapter(SensorTypeEnum.MOBILE_RF, config_loader),
            SensorTypeEnum.GPR: SimulatedGPRAdapter(config_loader),
            SensorTypeEnum.SEISMIC_ACOUSTIC: SeismicAdapter(config_loader),
            SensorTypeEnum.THERMAL_IR: ThermalAdapter(config_loader),
            SensorTypeEnum.RGB_VISUAL: OpticalAdapter(config_loader),
        }

    def get_adapter(self, sensor_type: SensorTypeEnum) -> BaseSensorAdapter:
        if sensor_type not in self._adapters:
            raise KeyError(f"No adapter registered for sensor type: {sensor_type}")
        return self._adapters[sensor_type]

    def process_payload(self, payload: BaseSensorPayload) -> tuple[float, float]:
        adapter = self.get_adapter(payload.sensor_type)
        llr = adapter.compute_llr(payload)
        quality = adapter.evaluate_quality(payload)
        return llr, quality