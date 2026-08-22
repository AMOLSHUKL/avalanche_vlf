"""
Abstract Base Sensor Adapter with Symmetric Negative-Evidence Log-Likelihood Formulation.
"""
from abc import ABC, abstractmethod
import math
from typing import Any
from backend.config.loader import ConfigLoader
from backend.schemas.sensors import BaseSensorPayload


class BaseSensorAdapter(ABC):
    def __init__(self, sensor_type: str, config_loader: ConfigLoader):
        self.sensor_type = sensor_type
        self.config_loader = config_loader

    @abstractmethod
    def parse_raw(self, raw_input: Any) -> BaseSensorPayload:
        pass

    def compute_llr(self, payload: BaseSensorPayload) -> float:
        """
        Expected log-likelihood ratio under a sensor-reliability mixture.

        The confidence score c is interpreted as the probability that the
        reading reflects the true state of the cell. The expected LLR is then:

            LLR_eff = c * ln(P(z|H) / P(z|~H)) + (1-c) * ln((1-P(z|H)) / (1-P(z|~H)))

        Properties:
            - c near 1.0 yields strongly positive evidence.
            - c = 0.0 yields the "sensor reports nothing found" LLR, which is
              negative but bounded by the false-alarm rate P(z|~H).
            - The neutral point c* where LLR_eff = 0 is NOT 0.5; it depends on
              how discriminative the modality is:
                  c* = ln((1-P(z|~H))/(1-P(z|H))) /
                       [ln(P(z|H)/P(z|~H)) + ln((1-P(z|~H))/(1-P(z|H)))]
              A sharper sensor pushes c* lower, so moderate confidence already
              supports presence. This asymmetry is intentional and calibrated.

        Sensor priors are validated at load time (0 < p < 1, and
        P(z|H) > P(z|~H)); missing modalities fail loudly rather than fusing
        with silent defaults.
        """
        priors = self.config_loader.get_sensor_priors(self.sensor_type)
        p_z_h = max(0.001, min(0.999, float(priors["p_z_given_h"])))
        p_z_not_h = max(0.001, min(0.999, float(priors["p_z_given_not_h"])))

        llr_detect = math.log(p_z_h / p_z_not_h)
        llr_null = math.log((1.0 - p_z_h) / (1.0 - p_z_not_h))

        # Continuous symmetric interpolation based on confidence score c in [0, 1]
        c = max(0.0, min(1.0, float(payload.confidence_score)))
        effective_llr = (c * llr_detect) + ((1.0 - c) * llr_null)
        return float(effective_llr)

    @abstractmethod
    def evaluate_quality(self, payload: BaseSensorPayload) -> float:
        pass