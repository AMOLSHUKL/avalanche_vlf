"""
Dual Autonomous UAV SAR Telemetry Generator with 5-Phase Operational State Machine,
Micro-Doppler Life-Sign Injection (0.28 Hz Respiration), Biological Permittivity Modeling (Er ~ 52),
and Non-Blocking Computational Stream Execution.
"""
import math
import random
from collections.abc import Generator
from typing import Any

from backend.schemas.domain import MissionPhaseEnum, UAVAssetTelemetry
from backend.schemas.sensors import (
    GeospatialContext,
    GPRPayload,
    MobileRFPayload,
    RECCOPayload,
    RGBPayload,
    SeismicAcousticPayload,
    ThermalPayload,
    TransceiverPayload,
)


class TelemetrySimulator:
    def __init__(
        self,
        origin_lat: float = 34.183900,
        origin_lon: float = 77.562100,
        width_m: float = 500.0,
        height_m: float = 500.0,
        cell_size_m: float = 5.0,
    ):
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.width_m = width_m
        self.height_m = height_m
        self.cell_size_m = cell_size_m

        # Terrain mirror for terrain-following flight: UAVs hold a constant
        # height ABOVE GROUND so they never clip beneath the rising slope.
        from backend.engine.terrain import TerrainEngine
        self.terrain = TerrainEngine(width_m, height_m, cell_size_m)

        # Ground Truth Targets:
        # Target 1: Equipped victim (Transceiver + GPR + Micro-Doppler Respiration + Mobile RF)
        # Target 2: Passive/Civilian victim (GPR + Dielectric Er=49 + RECCO + Micro-Doppler)
        # Target 3: Shallow/Surface exposed victim (Transceiver + Thermal + RGB Visual + Respiration)
        # Ground-truth cells sit on the carved avalanche runout (gully
        # centerline, verified slopes 23.5-26 deg) so the demo narrative is
        # coherent: the release buries them, UAV passes expose them.
        self.true_victims = [
            {
                "cell_x": 55,
                "cell_y": 43,
                "depth_m": 1.3,
                "has_457": True,
                "has_recco": False,
                "has_mobile": True,
                "thermal_exposed": False,
                "respiration_rate_hz": 0.28,
                "relative_permittivity": 52.5
            },
            {
                "cell_x": 61,
                "cell_y": 30,
                "depth_m": 2.1,
                "has_457": False,
                "has_recco": True,
                "has_mobile": False,
                "thermal_exposed": False,
                "respiration_rate_hz": 0.22,
                "relative_permittivity": 49.0
            },
            {
                "cell_x": 58,
                "cell_y": 36,
                "depth_m": 0.1,
                "has_457": True,
                "has_recco": False,
                "has_mobile": False,
                "thermal_exposed": True,
                "respiration_rate_hz": 0.34,
                "relative_permittivity": 54.0
            },
        ]

        self.fault_states: dict[str, bool] = {
            "TRANSCEIVER_457": False,
            "RECCO": False,
            "MOBILE_RF": False,
            "GPR": False,
            "SEISMIC_ACOUSTIC": False,
            "THERMAL_IR": False,
            "RGB_VISUAL": False
        }
        self.step_count = 0

    def _agl_altitude(self, x_m: float, y_m: float, agl_m: float) -> float:
        """Terrain-following altitude: local DEM elevation + above-ground hold."""
        cx = min(self.terrain.cols - 1, max(0, int(x_m / self.cell_size_m)))
        cy = min(self.terrain.rows - 1, max(0, int(y_m / self.cell_size_m)))
        return float(self.terrain.elevation_grid[cy, cx]) + agl_m

    def set_sensor_fault(self, sensor_type: str, is_disabled: bool) -> None:
        if sensor_type in self.fault_states:
            self.fault_states[sensor_type] = is_disabled

    def _determine_mission_phase(self) -> MissionPhaseEnum:
        """
        Advance operational SAR lifecycle through 5 distinct tactical phases.
        """
        if self.step_count < 20:
            return MissionPhaseEnum.ALERT_PREFLIGHT
        elif self.step_count < 75:
            return MissionPhaseEnum.LAWNMOWER_SURFACE_SCAN
        elif self.step_count < 140:
            return MissionPhaseEnum.DEEP_RADAR_SCAN
        elif self.step_count < 200:
            return MissionPhaseEnum.TARGET_VERIFICATION_MARKER_DROP
        else:
            return MissionPhaseEnum.SAR_VECTORING

    def generate_flight_stream(self) -> Generator[dict[str, Any], None, None]:
        """Pure computational generator streaming UAV kinematics and multi-modal telemetry."""
        while True:
            self.step_count += 1
            t = self.step_count * 0.4
            mission_phase = self._determine_mission_phase()

            # UAV Alpha: South-to-Mid Sector Sweep (Carries 457kHz, Thermal, Optical, Mobile RF)
            uav1_x = (t * 8.0) % self.width_m
            uav1_y = (0.08 * self.height_m) + ((int(t * 8.0 / self.width_m) * 30.0) % (0.44 * self.height_m))
            uav1_lat = self.origin_lat + (uav1_y / 111111.0)
            uav1_lon = self.origin_lon + (uav1_x / (111111.0 * math.cos(math.radians(self.origin_lat))))

            # UAV Bravo: North-to-Mid Sector Sweep (Carries UWB GPR, Seismic, RECCO)
            uav2_x = self.width_m - ((t * 7.5) % self.width_m)
            uav2_y = (0.30 * self.height_m) + ((int(t * 7.5 / self.width_m) * 35.0) % (0.44 * self.height_m))
            uav2_lat = self.origin_lat + (uav2_y / 111111.0)
            uav2_lon = self.origin_lon + (uav2_x / (111111.0 * math.cos(math.radians(self.origin_lat))))

            uav1_alt = self._agl_altitude(uav1_x, uav1_y, 55.0)
            uav2_alt = self._agl_altitude(uav2_x, uav2_y, 52.0)

            uav_telemetry = [
                UAVAssetTelemetry(
                    asset_id="UAV_ALPHA",
                    label="Alpha (457kHz/Thermal/RGB/Mobile)",
                    current_lat=uav1_lat,
                    current_lon=uav1_lon,
                    current_alt_m=uav1_alt,
                    battery_pct=max(10.0, 100.0 - (self.step_count * 0.02)),
                    active_sensor_modalities=["TRANSCEIVER_457", "THERMAL_IR", "RGB_VISUAL", "MOBILE_RF"],
                    heading_deg=90.0 if (int(t * 8.0 / 500.0) % 2 == 0) else 270.0,
                    speed_mps=8.0
                ).model_dump(mode="json"),
                UAVAssetTelemetry(
                    asset_id="UAV_BRAVO",
                    label="Bravo (UWB GPR/Seismic/RECCO)",
                    current_lat=uav2_lat,
                    current_lon=uav2_lon,
                    current_alt_m=uav2_alt,
                    battery_pct=max(10.0, 98.0 - (self.step_count * 0.025)),
                    active_sensor_modalities=["GPR", "SEISMIC_ACOUSTIC", "RECCO"],
                    heading_deg=270.0 if (int(t * 7.5 / 500.0) % 2 == 0) else 90.0,
                    speed_mps=7.5
                ).model_dump(mode="json")
            ]

            sensor_events: list[dict[str, Any]] = []
            c1_x, c1_y = int(uav1_x / self.cell_size_m), int(uav1_y / self.cell_size_m)
            c2_x, c2_y = int(uav2_x / self.cell_size_m), int(uav2_y / self.cell_size_m)

            # --- UAV ALPHA SENSING (Group A & Group C) ---
            for v in self.true_victims:
                dist1 = math.hypot(c1_x - v["cell_x"], c1_y - v["cell_y"])

                # 457 kHz Transceiver (Flux-line induction)
                if dist1 <= 6.0 and v["has_457"] and not self.fault_states["TRANSCEIVER_457"]:
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": TransceiverPayload(
                            sensor_id="RF_SNIFFER_01",
                            geo=GeospatialContext(lat=uav1_lat, lon=uav1_lon, altitude_m=uav1_alt),
                            confidence_score=max(0.2, 0.94 - (dist1 * 0.12)),
                            flux_line_angle_deg=(dist1 * 18.0) % 360.0,
                            estimated_distance_m=dist1 * 5.0
                        )
                    })

                # Cellular / Mobile RF (IMSI sniffer)
                if dist1 <= 5.0 and v["has_mobile"] and not self.fault_states["MOBILE_RF"]:
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": MobileRFPayload(
                            sensor_id="IMSI_CATCHER_01",
                            geo=GeospatialContext(lat=uav1_lat, lon=uav1_lon, altitude_m=uav1_alt),
                            confidence_score=max(0.15, 0.88 - (dist1 * 0.14)),
                            channel_frequency_mhz=1800.0,
                            timing_advance_m=dist1 * 4.5
                        )
                    })

                # Thermal IR (Shallow / Surface heat anomalies)
                if dist1 <= 4.0 and v["thermal_exposed"] and not self.fault_states["THERMAL_IR"]:
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": ThermalPayload(
                            sensor_id="FLIR_BOSON_01",
                            geo=GeospatialContext(lat=uav1_lat, lon=uav1_lon, altitude_m=uav1_alt, snow_depth_est_m=v["depth_m"]),
                            confidence_score=max(0.3, 0.92 - (dist1 * 0.15)),
                            temperature_delta_c=4.2,
                            pixel_area_count=240,
                            surface_clue_detected=True
                        )
                    })

                # Optical RGB Visual
                if dist1 <= 3.0 and v["thermal_exposed"] and not self.fault_states["RGB_VISUAL"]:
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": RGBPayload(
                            sensor_id="RGB_CAM_01",
                            geo=GeospatialContext(lat=uav1_lat, lon=uav1_lon, altitude_m=uav1_alt),
                            confidence_score=max(0.2, 0.89 - (dist1 * 0.18)),
                            bounding_box_area_ratio=0.045,
                            equipment_color_match_score=0.91,
                            shadow_anomaly_detected=True
                        )
                    })

            # --- UAV BRAVO SENSING (Group B Subsurface Radar & Life-Signs) ---
            for v in self.true_victims:
                dist2 = math.hypot(c2_x - v["cell_x"], c2_y - v["cell_y"])

                # UWB GPR with Micro-Doppler Respiration and Biological Permittivity
                if dist2 <= 3.5 and not self.fault_states["GPR"]:
                    resp_lock = dist2 <= 2.2
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": GPRPayload(
                            sensor_id="GPR_RADAR_02",
                            geo=GeospatialContext(lat=uav2_lat, lon=uav2_lon, altitude_m=uav2_alt, snow_density_kg_m3=340.0),
                            confidence_score=max(0.3, 0.92 - (dist2 * 0.14)),
                            estimated_depth_m=v["depth_m"] + random.gauss(0, 0.04),
                            hyperbola_eccentricity=0.88,
                            dielectric_contrast=7.8,
                            relative_permittivity=v["relative_permittivity"] + random.gauss(0, 0.8),
                            micro_doppler_frequency_hz=v["respiration_rate_hz"] if resp_lock else None,
                            respiration_locked=resp_lock,
                            void_anomaly_flag=v["depth_m"] > 1.0
                        )
                    })

                # RECCO Harmonic Radar
                if dist2 <= 4.0 and v["has_recco"] and not self.fault_states["RECCO"]:
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": RECCOPayload(
                            sensor_id="RECCO_DETECTOR_02",
                            geo=GeospatialContext(lat=uav2_lat, lon=uav2_lon, altitude_m=uav2_alt),
                            confidence_score=max(0.2, 0.90 - (dist2 * 0.15)),
                            harmonic_return_amplitude=65.0,
                            radar_cross_section_m2=0.45
                        )
                    })

                # Seismic & Micro-Acoustic Life-Sign
                if dist2 <= 3.0 and not self.fault_states["SEISMIC_ACOUSTIC"]:
                    sensor_events.append({
                        "target_cell": (v["cell_x"], v["cell_y"]),
                        "payload": SeismicAcousticPayload(
                            sensor_id="SEISMIC_GEOPHONE_02",
                            geo=GeospatialContext(lat=uav2_lat, lon=uav2_lon, altitude_m=uav2_alt),
                            confidence_score=max(0.1, 0.78 - (dist2 * 0.16)),
                            dominant_frequency_hz=18.5,
                            signal_to_noise_ratio_db=14.0,
                            impulse_pattern_detected=True
                        )
                    })

            # Transient Low-Confidence Radar Clutter Pulse (Bedrock/Ice Void Clutter)
            if random.random() < 0.08:
                max_col = int(self.width_m / self.cell_size_m) - 1
                max_row = int(self.height_m / self.cell_size_m) - 1
                noise_x, noise_y = random.randint(0, max_col), random.randint(0, max_row)
                sensor_events.append({
                    "target_cell": (noise_x, noise_y),
                    "payload": GPRPayload(
                        sensor_id="GPR_RADAR_02",
                        geo=GeospatialContext(lat=self.origin_lat, lon=self.origin_lon, altitude_m=3850.0),
                        confidence_score=0.12,
                        estimated_depth_m=0.8,
                        hyperbola_eccentricity=0.25,
                        dielectric_contrast=2.0,
                        relative_permittivity=6.5,  # Granite rock signature (Er ~ 6-9)
                        micro_doppler_frequency_hz=None,
                        respiration_locked=False,
                        void_anomaly_flag=False
                    )
                })

            yield {
                "mission_phase": mission_phase.value,
                "uav_telemetry": uav_telemetry,
                "sensor_events": sensor_events
            }
