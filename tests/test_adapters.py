"""
Adapter-level unit tests: every evaluate_quality() curve is bounded,
monotonic in its primary physical variable, and safe at zero/extreme
inputs. Closes the coverage gap where quality curves were exercised only
indirectly through end-to-end fusion scenarios.
"""
import pytest

from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.engine.adapters.registry import AdapterRegistry
from backend.schemas.sensors import (
    GeospatialContext,
    GPRPayload,
    MobileRFPayload,
    RECCOPayload,
    RGBPayload,
    SeismicAcousticPayload,
    SensorTypeEnum,
    ThermalPayload,
    TransceiverPayload,
)

QUALITY_FLOOR = 0.01


@pytest.fixture
def registry():
    ConfigLoader.reset_instance()
    return AdapterRegistry(ConfigLoader())


def _geo(**overrides) -> GeospatialContext:
    defaults = {"lat": 34.1839, "lon": 77.5621, "altitude_m": 3860.0}
    defaults.update(overrides)
    return GeospatialContext(**defaults)


def _transceiver(dist: float, **kw) -> TransceiverPayload:
    return TransceiverPayload(
        sensor_id="T_TEST", geo=_geo(**kw.pop("geo", {})), confidence_score=0.9,
        flux_line_angle_deg=30.0, estimated_distance_m=dist,
        **kw,
    )


def _recco(rcs: float) -> RECCOPayload:
    return RECCOPayload(
        sensor_id="R_TEST", geo=_geo(), confidence_score=0.9,
        harmonic_return_amplitude=65.0, radar_cross_section_m2=rcs,
    )


def _mobile(ta) -> MobileRFPayload:
    return MobileRFPayload(
        sensor_id="M_TEST", geo=_geo(), confidence_score=0.9,
        channel_frequency_mhz=1800.0, timing_advance_m=ta,
    )


def _gpr(depth: float, ecc: float = 0.9, conf: float = 0.9, density: float = 350.0) -> GPRPayload:
    return GPRPayload(
        sensor_id="G_TEST", geo=_geo(snow_density_kg_m3=density), confidence_score=conf,
        estimated_depth_m=depth, hyperbola_eccentricity=ecc, dielectric_contrast=7.5,
    )


def _seismic(snr: float, ambient_db: float = 30.0, impulse: bool = True) -> SeismicAcousticPayload:
    return SeismicAcousticPayload(
        sensor_id="S_TEST", geo=_geo(acoustic_noise_db=ambient_db), confidence_score=0.9,
        dominant_frequency_hz=18.5, signal_to_noise_ratio_db=snr,
        impulse_pattern_detected=impulse,
    )


def _thermal(delta_c: float, snow_depth: float, wind: float = 5.0,
             surface_clue: bool = False) -> ThermalPayload:
    return ThermalPayload(
        sensor_id="TH_TEST", geo=_geo(snow_depth_est_m=snow_depth, wind_speed_mps=wind),
        confidence_score=0.9, temperature_delta_c=delta_c, pixel_area_count=240,
        surface_clue_detected=surface_clue,
    )


def _rgb(color: float, area: float, shadow: bool = True) -> RGBPayload:
    return RGBPayload(
        sensor_id="O_TEST", geo=_geo(), confidence_score=0.9,
        bounding_box_area_ratio=area, equipment_color_match_score=color,
        shadow_anomaly_detected=shadow,
    )


class TestQualityBoundsAndMonotonicity:
    def test_transceiver_quality_bounded_and_decreasing_with_range(self, registry):
        rf = registry.get_adapter(SensorTypeEnum.TRANSCEIVER_457)
        sweep = [_transceiver(d) for d in (0.0, 2.0, 10.0, 25.0, 50.0, 100.0)]
        qualities = [rf.evaluate_quality(p) for p in sweep]
        for q in qualities:
            assert QUALITY_FLOOR <= q <= 1.0
        assert qualities == sorted(qualities, reverse=True)

    def test_transceiver_quality_is_half_at_reference_range(self, registry):
        """At d* = max_range/2 the saturating near-field curve must pass 0.5."""
        rf = registry.get_adapter(SensorTypeEnum.TRANSCEIVER_457)
        # Default emi floor (-105 dBm) yields no penalty: q == q_dist exactly.
        q = rf.evaluate_quality(_transceiver(25.0))
        assert q == pytest.approx(0.5, abs=1e-6)

    def test_recco_quality_saturates_above_reference_rcs(self, registry):
        rf = registry.get_adapter(SensorTypeEnum.RECCO)
        weak = rf.evaluate_quality(_recco(0.05))
        strong = rf.evaluate_quality(_recco(0.45))
        saturated = rf.evaluate_quality(_recco(5.0))
        assert QUALITY_FLOOR <= weak < strong <= saturated <= 1.0
        assert saturated == rf.evaluate_quality(_recco(9.9))

    def test_mobile_rf_quality_penalizes_large_timing_advance(self, registry):
        rf = registry.get_adapter(SensorTypeEnum.MOBILE_RF)
        none_ta = rf.evaluate_quality(_mobile(None))
        near = rf.evaluate_quality(_mobile(50.0))
        far = rf.evaluate_quality(_mobile(5000.0))
        assert QUALITY_FLOOR <= far < near <= none_ta <= 1.0

    def test_gpr_quality_attenuates_with_depth_and_density(self, registry):
        gpr = registry.get_adapter(SensorTypeEnum.GPR)
        shallow_dry = gpr.evaluate_quality(_gpr(depth=0.5, density=200.0))
        shallow_wet = gpr.evaluate_quality(_gpr(depth=0.5, density=600.0))
        deep_wet = gpr.evaluate_quality(_gpr(depth=6.0, density=600.0))
        assert QUALITY_FLOOR <= deep_wet <= shallow_wet < shallow_dry <= 1.0

    def test_gpr_eccentrity_gate_applies_only_to_positive_detections(self, registry):
        gpr = registry.get_adapter(SensorTypeEnum.GPR)
        detection_low_fit = gpr.evaluate_quality(_gpr(depth=1.0, ecc=0.1, conf=0.9))
        detection_high_fit = gpr.evaluate_quality(_gpr(depth=1.0, ecc=0.9, conf=0.9))
        clear_scan_a = gpr.evaluate_quality(_gpr(depth=1.0, ecc=0.1, conf=0.05))
        clear_scan_b = gpr.evaluate_quality(_gpr(depth=1.0, ecc=0.9, conf=0.05))
        assert detection_high_fit > detection_low_fit
        assert clear_scan_a == clear_scan_b

    def test_seismic_quality_rises_with_snr_falls_with_noise(self, registry):
        seis = registry.get_adapter(SensorTypeEnum.SEISMIC_ACOUSTIC)
        quiet_strong = seis.evaluate_quality(_seismic(40.0, ambient_db=20.0))
        noisy_strong = seis.evaluate_quality(_seismic(40.0, ambient_db=120.0))
        noisy_weak = seis.evaluate_quality(_seismic(-15.0, ambient_db=120.0))
        assert QUALITY_FLOOR <= noisy_weak < noisy_strong < quiet_strong <= 1.0

    def test_seismic_impulse_pattern_boosts_quality(self, registry):
        seis = registry.get_adapter(SensorTypeEnum.SEISMIC_ACOUSTIC)
        with_pattern = seis.evaluate_quality(_seismic(14.0, impulse=True))
        without_pattern = seis.evaluate_quality(_seismic(14.0, impulse=False))
        assert with_pattern > without_pattern

    def test_thermal_surface_clue_outperforms_deep_burial(self, registry):
        thermal = registry.get_adapter(SensorTypeEnum.THERMAL_IR)
        exposed = thermal.evaluate_quality(_thermal(4.2, snow_depth=1.5, surface_clue=True))
        buried = thermal.evaluate_quality(_thermal(4.2, snow_depth=1.5))
        assert exposed > buried >= QUALITY_FLOOR
        deeper = thermal.evaluate_quality(_thermal(4.2, snow_depth=5.0))
        assert buried > deeper or deeper == QUALITY_FLOOR

    def test_thermal_quality_penalizes_wind(self, registry):
        thermal = registry.get_adapter(SensorTypeEnum.THERMAL_IR)
        calm = thermal.evaluate_quality(_thermal(4.2, snow_depth=0.1, wind=0.0))
        gale = thermal.evaluate_quality(_thermal(4.2, snow_depth=0.1, wind=60.0))
        assert calm > gale >= QUALITY_FLOOR

    def test_optical_quality_tracks_color_and_area(self, registry):
        optical = registry.get_adapter(SensorTypeEnum.RGB_VISUAL)
        strong = optical.evaluate_quality(_rgb(0.95, 0.2, shadow=True))
        mid = optical.evaluate_quality(_rgb(0.5, 0.05, shadow=True))
        weak = optical.evaluate_quality(_rgb(0.1, 0.001, shadow=False))
        assert QUALITY_FLOOR <= weak < mid < strong <= 1.0


class TestComputeLLRContract:
    def test_llr_interpolation_signs_and_monotonicity(self, registry):
        adapter: BaseSensorAdapter = registry.get_adapter(SensorTypeEnum.GPR)
        payload = _gpr(1.0)
        scores = [c / 10.0 for c in range(11)]
        llrs = []
        for c in scores:
            payload = payload.model_copy(update={"confidence_score": c})
            llrs.append(adapter.compute_llr(payload))
        # Zero-confidence reads report absence (negative evidence), full
        # confidence reports presence, and evidence strength rises with c.
        assert llrs[0] < 0.0 < llrs[-1]
        assert llrs == sorted(llrs)

    def test_unconfigured_sensor_priors_fail_loudly(self, registry):
        adapter: BaseSensorAdapter = registry.get_adapter(SensorTypeEnum.GPR)
        original = adapter.sensor_type
        adapter.sensor_type = "UNREGISTERED_SENSOR"
        try:
            with pytest.raises(KeyError):
                adapter.compute_llr(_gpr(1.0))
        finally:
            adapter.sensor_type = original
