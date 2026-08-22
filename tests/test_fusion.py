"""
Complete Pytest Verification Suite for AVALANCHE-VLF.
Validates Mathematical Integrity, Symmetric Evidence, Leaky Anti-Windup Accumulation,
Dynamic Survival Parameter Binding, MGRS Geotagging, Micro-Doppler Life-Signs,
Safe Approach Azimuth, 16-Byte LoRa C-Struct Packaging, and Concurrency Lock Safety.
"""
import pytest
import asyncio
import math
from pydantic import ValidationError
from backend.config.loader import ConfigLoader
from backend.engine.fusion import FusionEngine
from backend.engine.adapters.registry import AdapterRegistry
from backend.telemetry.simulator import TelemetrySimulator
from backend.telemetry.lora_packet import LoRaTargetPacket, LORA_PACKET_SIZE
from backend.schemas.sensors import (
    TransceiverPayload,
    GPRPayload,
    ThermalPayload,
    SeismicAcousticPayload,
    GeospatialContext
)
from backend.schemas.domain import (
    PriorityZoneEnum,
    TacticalDirective,
    DirectiveTypeEnum,
    MissionPhaseEnum
)


@pytest.fixture
def system_fixture():
    ConfigLoader.reset_instance()
    config_loader = ConfigLoader()
    engine = FusionEngine(config_loader)
    registry = AdapterRegistry(config_loader)
    return engine, registry, config_loader


@pytest.mark.asyncio
async def test_multimodal_alignment_triggers_p1(system_fixture):
    """TEST 1: 457 kHz Transceiver + GPR multi-modal alignment triggers P1 directive."""
    engine, registry, _ = system_fixture
    cx, cy = 45, 35

    # 1. Transceiver ping (Group A)
    rf_payload = TransceiverPayload(
        sensor_id="RF_TEST_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
        confidence_score=0.92,
        flux_line_angle_deg=45.0,
        estimated_distance_m=2.0
    )
    llr_rf, q_rf = registry.process_payload(rf_payload)
    await engine.update_cell_evidence(cx, cy, rf_payload, llr_rf, q_rf)

    # 2. GPR confirmation with Micro-Doppler life-sign (Group B)
    gpr_payload = GPRPayload(
        sensor_id="GPR_TEST_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0, snow_density_kg_m3=320.0),
        confidence_score=0.90,
        estimated_depth_m=1.3,
        hyperbola_eccentricity=0.90,
        dielectric_contrast=8.0,
        relative_permittivity=52.0,
        micro_doppler_frequency_hz=0.28,
        respiration_locked=True
    )
    llr_gpr, q_gpr = registry.process_payload(gpr_payload)
    state = await engine.update_cell_evidence(cx, cy, gpr_payload, llr_gpr, q_gpr)

    assert state.probability >= 0.85
    assert state.priority_zone == PriorityZoneEnum.P1
    assert len(engine.active_directives) >= 1
    assert "GROUP_A_ELECTRONIC" in state.contributing_evidence_groups
    assert "GROUP_B_SUBSURFACE" in state.contributing_evidence_groups


@pytest.mark.asyncio
async def test_non_cooperative_victim_gpr_fallback(system_fixture):
    """TEST 2: Non-cooperative victim without RF beacon successfully elevates via GPR passes."""
    engine, registry, _ = system_fixture
    cx, cy = 70, 60

    for _ in range(4):
        gpr_payload = GPRPayload(
            sensor_id="GPR_TEST_01",
            geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0, snow_density_kg_m3=300.0),
            confidence_score=0.92,
            estimated_depth_m=2.1,
            hyperbola_eccentricity=0.89,
            dielectric_contrast=7.5,
            relative_permittivity=49.0,
            micro_doppler_frequency_hz=0.22,
            respiration_locked=True
        )
        llr_gpr, q_gpr = registry.process_payload(gpr_payload)
        state = await engine.update_cell_evidence(cx, cy, gpr_payload, llr_gpr, q_gpr)

    assert state.probability >= 0.60
    assert state.priority_zone in [PriorityZoneEnum.P1, PriorityZoneEnum.P2]
    assert "GROUP_A_ELECTRONIC" not in state.contributing_evidence_groups


@pytest.mark.asyncio
async def test_symmetric_negative_evidence_and_temporal_suppression(system_fixture):
    """TEST 3: Low confidence noise emits negative LLR and decays posterior probability."""
    engine, registry, _ = system_fixture
    cx, cy = 10, 10

    clear_payload = GPRPayload(
        sensor_id="GPR_CLEAR",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3850.0),
        confidence_score=0.02,
        estimated_depth_m=0.8,
        hyperbola_eccentricity=0.05,
        dielectric_contrast=1.0,
        relative_permittivity=3.2,
        micro_doppler_frequency_hz=None,
        respiration_locked=False
    )
    llr, q = registry.process_payload(clear_payload)
    assert llr < 0.0  # Verifies symmetric negative LLR formulation

    for _ in range(3):
        engine._pass_tracker[f"cell_{cx}_{cy}"]["last_pass_time"] -= 6.0
        state = await engine.update_cell_evidence(cx, cy, clear_payload, llr, q)

    assert state.probability < 0.20
    assert state.priority_zone == PriorityZoneEnum.P4


@pytest.mark.asyncio
async def test_leaky_anti_windup_evidence_retraction(system_fixture):
    """TEST 4: Bounded accumulator allows fast evidence retraction without windup lag."""
    engine, registry, _ = system_fixture
    cx, cy = 25, 25

    # 1. Accumulate positive evidence
    pos_payload = GPRPayload(
        sensor_id="GPR_POS",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
        confidence_score=0.95,
        estimated_depth_m=1.0,
        hyperbola_eccentricity=0.9,
        dielectric_contrast=7.0,
        relative_permittivity=52.0
    )
    llr_pos, q_pos = registry.process_payload(pos_payload)
    for _ in range(10):
        await engine.update_cell_evidence(cx, cy, pos_payload, llr_pos, q_pos)

    assert engine.grid[f"cell_{cx}_{cy}"].probability > 0.85

    # 2. Inject negative evidence; verifies rapid probability drop due to bounded accumulator
    neg_payload = GPRPayload(
        sensor_id="GPR_NEG",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
        confidence_score=0.01,
        estimated_depth_m=1.0,
        hyperbola_eccentricity=0.1,
        dielectric_contrast=1.0,
        relative_permittivity=3.2
    )
    llr_neg, q_neg = registry.process_payload(neg_payload)
    for _ in range(6):
        state = await engine.update_cell_evidence(cx, cy, neg_payload, llr_neg, q_neg)

    assert state.probability < 0.50


def test_rescuer_hazard_monotonicity(system_fixture):
    """TEST 5: Rescuer slope hazard function is monotonically increasing for slopes >= 25 degrees."""
    engine, _, _ = system_fixture
    h_20 = engine.terrain.calculate_rescuer_hazard(20.0)
    h_35 = engine.terrain.calculate_rescuer_hazard(35.0)
    h_45 = engine.terrain.calculate_rescuer_hazard(45.0)
    h_55 = engine.terrain.calculate_rescuer_hazard(55.0)

    assert h_20 == 1.0
    assert h_35 > h_20
    assert h_45 >= h_35
    assert h_55 > h_45


def test_safe_approach_azimuth_is_contour_perpendicular(system_fixture):
    """Approach heading must be perpendicular (dot product ~ 0) to the terrain
    gradient expressed in compass-frame components (East, North)."""
    import math as _math

    engine, _, _ = system_fixture
    terrain = engine.terrain

    for cx, cy in [(10, 10), (25, 25), (45, 35), (70, 60), (90, 90)]:
        cy_min, cy_max = max(0, cy - 1), min(terrain.rows - 1, cy + 1)
        cx_min, cx_max = max(0, cx - 1), min(terrain.cols - 1, cx + 1)
        dz_dy = (
            float(terrain.elevation_grid[cy_max, cx])
            - float(terrain.elevation_grid[cy_min, cx])
        ) / (2.0 * terrain.cell_size_m)
        dz_dx = (
            float(terrain.elevation_grid[cy, cx_max])
            - float(terrain.elevation_grid[cy, cx_min])
        ) / (2.0 * terrain.cell_size_m)

        approach_deg = engine._calculate_safe_approach_azimuth(cx, cy)
        rad = _math.radians(approach_deg)
        # Compass bearing -> unit vector in (East, North) frame
        ux, uy = _math.sin(rad), _math.cos(rad)
        grad_norm = _math.hypot(dz_dx, dz_dy)
        dot = (dz_dx * ux + dz_dy * uy) / grad_norm
        assert abs(dot) < 1e-9, f"approach not contour-parallel at cell ({cx},{cy}): dot={dot}"
        assert 0.0 <= approach_deg < 360.0


def test_mgrs_matches_true_geodetic_conversion(system_fixture):
    """Grid MGRS tags must equal the real WGS84->MGRS conversion of each
    cell's lat/lon, not fabricated offsets."""
    from backend.engine.geo import geodetic_to_mgrs

    engine, _, _ = system_fixture
    for zone_id, state in list(engine.grid.items())[:200]:
        expected = geodetic_to_mgrs(state.lat, state.lon, precision_digits=5)
        assert state.mgrs_coord == expected, f"mismatch at {zone_id}"


def test_survival_clock_anchored_to_incident_epoch(tmp_path, monkeypatch):
    """Survival time must be measured from the incident epoch, not server start."""
    import shutil
    import time as _time
    from backend.config.loader import ConfigLoader

    isolated_cfg = tmp_path / "fusion_parameters.yaml"
    shutil.copy("config/fusion_parameters.yaml", isolated_cfg)
    monkeypatch.setenv("FUSION_CONFIG_PATH", str(isolated_cfg))

    ConfigLoader.reset_instance()
    try:
        loader = ConfigLoader()
        twenty_five_minutes_ago = _time.time() - 1500.0
        loader.update_parameters_in_memory(
            {"mission": {"incident_epoch_s": twenty_five_minutes_ago}}, "TEST"
        )
        engine = FusionEngine(loader)

        snapshot = engine.get_survival_clock_snapshot()
        assert abs(snapshot["elapsed_min"] - 25.0) < 0.05
        s = snapshot["survival_probability"]
        # 25 minutes into a mission sits inside the Phase 2 asphyxiation cliff
        assert 0.27 <= s < 0.92
    finally:
        ConfigLoader.reset_instance()


def test_pydantic_schema_validation_bounds():
    """TEST 6: Strict validation bounds reject invalid sensors and domain payloads."""
    with pytest.raises(ValidationError):
        GeospatialContext(lat=95.0, lon=77.0, altitude_m=3800.0)

    with pytest.raises(ValidationError):
        GPRPayload(
            sensor_id="GPR_ERR",
            geo=GeospatialContext(lat=34.0, lon=77.0, altitude_m=3800.0),
            confidence_score=0.9,
            estimated_depth_m=1.0,
            hyperbola_eccentricity=0.8,
            dielectric_contrast=5.0,
            relative_permittivity=120.0  # Out of bounds (>85.0)
        )

    with pytest.raises(ValidationError):
        TacticalDirective(
            directive_id="DIR_01",
            target_zone_id="cell_0_0",
            directive_type=DirectiveTypeEnum.PROBE_EXCAVATE,
            priority_zone=PriorityZoneEnum.P1,
            lat=34.0,
            lon=77.0,
            depth_estimate_m=-1.5,  # Invalid negative depth
            confidence_radius_m=0.5,
            rationale="Test"
        )


@pytest.mark.asyncio
async def test_dynamic_survival_parameter_binding(system_fixture):
    """TEST 7: Survival model dynamically computes decay rates across all 3 physiological phases."""
    engine, _, _ = system_fixture

    # 10 minutes (Phase 1: Clear Airway Plateau)
    s_10 = engine._calculate_survival_probability(10.0, 350.0)
    assert s_10 == 0.92

    # 25 minutes (Phase 2: Asphyxiation Cliff)
    s_25 = engine._calculate_survival_probability(25.0, 350.0)
    assert 0.27 <= s_25 < 0.92

    # 60 minutes (Phase 3: Hypothermia Plateau)
    s_60 = engine._calculate_survival_probability(60.0, 350.0)
    assert 0.03 <= s_60 <= 0.27


@pytest.mark.asyncio
async def test_concurrent_stress_and_lock_safety(system_fixture):
    """TEST 8: Asynchronous stress test verifying state lock safety under parallel sensor workers."""
    engine, registry, _ = system_fixture

    async def simulate_sensor_worker(worker_id: int, cx: int, cy: int):
        for _ in range(10):
            payload = GPRPayload(
                sensor_id=f"GPR_WORKER_{worker_id}",
                geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
                confidence_score=0.85,
                estimated_depth_m=1.0,
                hyperbola_eccentricity=0.8,
                dielectric_contrast=5.0,
                relative_permittivity=52.0
            )
            llr, q = registry.process_payload(payload)
            await engine.update_cell_evidence(cx, cy, payload, llr, q)
            await asyncio.sleep(0.001)

    tasks = [simulate_sensor_worker(i, 50, 50) for i in range(8)]
    await asyncio.gather(*tasks)

    state = engine.grid["cell_50_50"]
    assert state.probability > 0.85
    assert not math.isnan(state.current_llr)


@pytest.mark.asyncio
async def test_mgrs_and_approach_azimuth_directive(system_fixture):
    """TEST 9: Directive synthesis generates MGRS format, marker status, and safe approach heading."""
    engine, registry, _ = system_fixture
    cx, cy = 45, 35

    # Push to P1
    rf_payload = TransceiverPayload(
        sensor_id="RF_SNIFFER_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
        confidence_score=0.95,
        flux_line_angle_deg=30.0,
        estimated_distance_m=1.5
    )
    llr, q = registry.process_payload(rf_payload)
    await engine.update_cell_evidence(cx, cy, rf_payload, llr, q)

    gpr_payload = GPRPayload(
        sensor_id="GPR_01",
        geo=GeospatialContext(lat=34.1839, lon=77.5621, altitude_m=3860.0),
        confidence_score=0.92,
        estimated_depth_m=1.3,
        hyperbola_eccentricity=0.9,
        dielectric_contrast=7.5,
        relative_permittivity=52.5,
        micro_doppler_frequency_hz=0.28,
        respiration_locked=True
    )
    llr2, q2 = registry.process_payload(gpr_payload)
    state = await engine.update_cell_evidence(cx, cy, gpr_payload, llr2, q2)

    assert state.priority_zone == PriorityZoneEnum.P1
    # Real WGS84 -> MGRS conversion: zone 43, band S, 100 km square GT
    assert state.mgrs_coord.startswith("43S GT ")
    assert len(engine.active_directives) >= 1

    directive = engine.active_directives[0]
    assert directive.target_zone_id == f"cell_{cx}_{cy}"
    assert directive.mgrs_coord == state.mgrs_coord
    assert directive.marker_deployed is True
    # Marker frequency is config-driven (India SRD band default 866.0 MHz)
    config_loader = system_fixture[2]
    assert directive.marker_frequency_mhz == float(
        config_loader.config["mission"]["marker_frequency_mhz"]
    )
    assert 0.0 <= directive.approach_azimuth_deg < 360.0


def test_lora_binary_packet_roundtrip(system_fixture):
    """TEST 10: Validates 16-byte packed C-struct serialization, CRC16, field deserialization,
    and exact MGRS reconstruction through the mission grid frame."""
    engine, _, _ = system_fixture
    directive = TacticalDirective(
        directive_id="DIR_cell_45_35_1723630000",
        target_zone_id="cell_45_35",
        directive_type=DirectiveTypeEnum.PROBE_EXCAVATE,
        priority_zone=PriorityZoneEnum.P1,
        lat=34.1843,
        lon=77.5629,
        mgrs_coord="43S GT 36343 85694",
        depth_estimate_m=1.30,
        confidence_radius_m=0.7,
        approach_azimuth_deg=135.0,
        marker_deployed=True,
        marker_frequency_mhz=866.0,
        recommended_equipment=["Probe", "Shovel"],
        rationale="Target lock test"
    )
    grid_frame = engine.mission_grid_frame

    packet = LoRaTargetPacket.from_directive(
        directive, grid_frame, probability=0.935, respiration_locked=True
    )
    raw_bytes = packet.pack()

    # Exact size check
    assert len(raw_bytes) == LORA_PACKET_SIZE
    assert len(raw_bytes) == 16

    # Roundtrip Unpack & CRC verification
    unpacked = LoRaTargetPacket.unpack(raw_bytes)
    assert unpacked.msg_type == 0x01
    assert unpacked.cell_x == 45
    assert unpacked.cell_y == 35
    assert abs(unpacked.probability - 0.935) < 0.01
    assert unpacked.depth_m == 1.30
    assert unpacked.radius_m == 0.7
    assert unpacked.approach_azimuth_deg == 135.0
    assert unpacked.marker_deployed is True
    assert unpacked.respiration_locked is True
    assert unpacked.is_p1 is True

    # Reconstructed MGRS must match the true conversion of the directive's
    # lat/lon within the +/-0.5 m rounding of uint16 meter offsets.
    from backend.engine.geo import geodetic_to_mgrs

    reconstructed = unpacked.to_mgrs_string(grid_frame)
    expected = geodetic_to_mgrs(directive.lat, directive.lon, precision_digits=5)
    rec_parts, exp_parts = reconstructed.split(), expected.split()
    assert rec_parts[:2] == exp_parts[:2]
    for rec_suffix, exp_suffix in zip(rec_parts[2:], exp_parts[2:]):
        assert abs(int(rec_suffix) - int(exp_suffix)) <= 1

    # Offsets outside uint16 must fail loudly instead of silently wrapping.
    bad = LoRaTargetPacket(
        msg_type=0x01, cell_x=0, cell_y=0, probability=0.5,
        depth_m=1.0, radius_m=0.7, approach_azimuth_deg=90.0,
        marker_deployed=False, respiration_locked=False, is_p1=False,
        void_detected=False, east_offset_m=-1, north_offset_m=0
    )
    with pytest.raises(ValueError):
        bad.pack()


def test_5_phase_mission_progression():
    """TEST 11: Validates that the TelemetrySimulator advances through all 5 SAR operational phases."""
    sim = TelemetrySimulator()
    stream = sim.generate_flight_stream()
    phases_seen = set()

    for _ in range(220):
        frame = next(stream)
        phases_seen.add(frame["mission_phase"])

    assert MissionPhaseEnum.ALERT_PREFLIGHT.value in phases_seen
    assert MissionPhaseEnum.LAWNMOWER_SURFACE_SCAN.value in phases_seen
    assert MissionPhaseEnum.DEEP_RADAR_SCAN.value in phases_seen
    assert MissionPhaseEnum.TARGET_VERIFICATION_MARKER_DROP.value in phases_seen
    assert MissionPhaseEnum.SAR_VECTORING.value in phases_seen