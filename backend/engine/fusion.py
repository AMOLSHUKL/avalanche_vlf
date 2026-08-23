"""
Cumulative Recursive Bayesian Log-Odds Fusion Engine with time-based leaky
accumulation, dynamic survival parameter binding, monotonic rescuer hazard,
true MGRS geotagging, and contour-parallel safe approach azimuths.

Numerical invariants enforced here:
    - Probabilities are clamped to [0.001, 0.999] before any odds conversion.
    - Log-odds states are clamped to +/- thresholds.llr_clamp (default 15).
    - Group accumulators are clamped to their configured saturation caps.
    - All interval arithmetic uses time.monotonic(); wall-clock time is used
      only for mission-elapsed (survival) time anchored to the incident.
"""
import asyncio
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any

from backend.config.loader import ConfigLoader
from backend.engine.geo import geodetic_to_mgrs, mission_grid_frame_from_latlon
from backend.engine.logger import TelemetryFineTuneLogger
from backend.engine.ports import MissionEventSink
from backend.engine.terrain import TerrainEngine
from backend.schemas.sensors import BaseSensorPayload, GPRPayload
from backend.schemas.domain import (
    GridZoneState,
    PriorityZoneEnum,
    ZoneStatusEnum,
    TacticalDirective,
    DirectiveTypeEnum
)

# Fallback only; config "grid.lkp_cell" is the authoritative source.
DEFAULT_LKP_CELL = (50, 40)

GROUP_A = "GROUP_A_ELECTRONIC"
GROUP_B = "GROUP_B_SUBSURFACE"
GROUP_C = "GROUP_C_SURFACE"


def latlon_to_mgrs(lat: float, lon: float) -> str:
    """10-digit (1 m resolution) MGRS grid reference from WGS84 lat/lon."""
    return geodetic_to_mgrs(lat, lon, precision_digits=5)


class FusionEngine:
    def __init__(
        self,
        config_loader: Optional[ConfigLoader] = None,
        logger: Optional[MissionEventSink] = None,
    ):
        self.config_loader = config_loader or ConfigLoader()
        grid_cfg = self.config_loader.config["grid"]
        self.terrain = TerrainEngine(
            width_m=float(grid_cfg["width_m"]),
            height_m=float(grid_cfg["height_m"]),
            cell_size_m=float(grid_cfg["cell_size_m"]),
        )
        self.logger: MissionEventSink = logger or TelemetryFineTuneLogger()

        # Mission clock: survival time is measured from the avalanche incident,
        # not from server start. Config may pin the incident epoch for replay.
        mission_cfg = self.config_loader.config.get("mission", {})
        self.incident_epoch_s = float(
            mission_cfg.get("incident_epoch_s") or time.time()
        )

        self._state_lock = asyncio.Lock()
        self.cols = self.terrain.cols
        self.rows = self.terrain.rows
        self.grid: Dict[str, GridZoneState] = {}
        self.active_directives: List[TacticalDirective] = []
        # Strong references to fire-and-forget logging tasks; without these,
        # asyncio may garbage-collect mid-flight tasks and swallow errors.
        self._bg_tasks: set[asyncio.Task] = set()
        # Persistent group accumulators: zone_id -> { group_name -> float }
        self._group_cumulative_scores: Dict[str, Dict[str, float]] = {}
        # Monotonic timestamp of the last evidence update per zone (leak decay)
        self._last_update_monotonic: Dict[str, float] = {}
        # Spatial pass tracking: zone_id -> { last_pass_time, current_pass_score, sample_count }
        self._pass_tracker: Dict[str, Dict[str, float]] = {}
        # Multi-pass history deque for temporal persistence: zone_id -> deque of pass averages
        self._temporal_pass_history: Dict[str, deque] = {}
        lkp_cell = tuple(grid_cfg.get("lkp_cell", DEFAULT_LKP_CELL))
        self.lkp_cell: Tuple[int, int] = (int(lkp_cell[0]), int(lkp_cell[1]))
        # Shared georeference for LoRa target vectors and MGRS reconstruction
        self.mission_grid_frame = mission_grid_frame_from_latlon(
            float(grid_cfg["origin_lat"]), float(grid_cfg["origin_lon"])
        )
        self._initialize_grid(self.lkp_cell)

    def _initialize_grid(self, lkp_cell: Tuple[int, int]) -> None:
        origin_lat = float(self.config_loader.config["grid"]["origin_lat"])
        origin_lon = float(self.config_loader.config["grid"]["origin_lon"])
        cell_size = self.terrain.cell_size_m
        window_passes = int(self.config_loader.get_thresholds().get("temporal_window_passes", 4))

        for cy in range(self.rows):
            for cx in range(self.cols):
                zone_id = f"cell_{cx}_{cy}"
                lat = origin_lat + (cy * cell_size) / 111111.0
                lon = origin_lon + (cx * cell_size) / (111111.0 * math.cos(math.radians(origin_lat)))
                elevation = float(self.terrain.elevation_grid[cy, cx])
                slope = float(self.terrain.slope_grid[cy, cx])
                mgrs = latlon_to_mgrs(lat, lon)
                p0 = self._compute_prior_prob(cx, cy, lkp_cell)
                llr_0 = math.log(p0 / (1.0 - p0))

                self.grid[zone_id] = GridZoneState(
                    zone_id=zone_id,
                    cell_x=cx,
                    cell_y=cy,
                    lat=lat,
                    lon=lon,
                    mgrs_coord=mgrs,
                    elevation_m=elevation,
                    slope_deg=slope,
                    current_llr=llr_0,
                    probability=p0,
                    priority_score=0.0,
                    priority_zone=PriorityZoneEnum.P4,
                    status=ZoneStatusEnum.UNSEEN,
                    last_updated_at=datetime.now(timezone.utc)
                )
                self._group_cumulative_scores[zone_id] = {
                    GROUP_A: 0.0,
                    GROUP_B: 0.0,
                    GROUP_C: 0.0
                }
                self._last_update_monotonic[zone_id] = time.monotonic()
                self._pass_tracker[zone_id] = {
                    "last_pass_time": 0.0,
                    "current_pass_score": 0.0,
                    "sample_count": 0.0
                }
                self._temporal_pass_history[zone_id] = deque(maxlen=window_passes)

    def _compute_prior_prob(self, cell_x: int, cell_y: int, lkp_cell: Tuple[int, int]) -> float:
        """Contextual spatial prior delegated to the terrain model."""
        sigma_lkp_m = float(
            self.config_loader.config.get("grid", {}).get("lkp_sigma_m", 85.0)
        )
        p0 = self.terrain.compute_prior_prob(cell_x, cell_y, lkp_cell, sigma_lkp_m)
        return max(0.01, min(0.95, p0))

    def _group_decay_factor(self, now_monotonic: float, last_update: float) -> float:
        """
        Time-based leak: group scores retain gamma per second of elapsed wall
        time, independent of how often a cell happens to be scanned.
        """
        gamma = float(self.config_loader.get_thresholds().get("evidence_decay_factor", 0.96))
        gamma = min(1.0, max(0.0, gamma))
        dt = max(0.0, now_monotonic - last_update)
        return gamma ** dt

    async def update_cell_evidence(
        self,
        cell_x: int,
        cell_y: int,
        sensor_payload: BaseSensorPayload,
        raw_llr: float,
        quality_coef: float
    ) -> GridZoneState:
        """
        Concurrency-safe Bayesian atomic update with time-based leaky intra-group
        accumulation, anti-windup bounds, temporal consistency filtering, and
        physiological utility calculation.
        """
        async with self._state_lock:
            zone_id = f"cell_{cell_x}_{cell_y}"
            if zone_id not in self.grid:
                raise KeyError(f"Cell coordinates ({cell_x}, {cell_y}) out of grid boundaries.")

            state = self.grid[zone_id]
            group_name = sensor_payload.evidence_group.value
            group_caps = self.config_loader.get_group_caps()
            group_weights = self.config_loader.get_group_weights()
            thresholds = self.config_loader.get_thresholds()
            now_mono = time.monotonic()

            llr_clamp = float(thresholds.get("llr_clamp", 15.0))
            tau_p3 = float(thresholds.get("tau_p3", 0.15))
            positive_pass_threshold = float(thresholds.get("positive_pass_threshold", 0.30))

            effective_sample_llr = raw_llr * quality_coef

            # 1. Time-based leaky accumulation on every group, then inject the
            #    new sample into the observed group. Leak rate depends on
            #    elapsed time since the cell's previous update, not update count.
            decay = self._group_decay_factor(now_mono, self._last_update_monotonic[zone_id])
            scores = self._group_cumulative_scores[zone_id]
            for g_k in scores:
                cap_limit = float(group_caps.get(g_k, 4.5))
                scores[g_k] = max(-cap_limit, min(cap_limit, scores[g_k] * decay))
            cap_limit = float(group_caps.get(group_name, 4.5))
            scores[group_name] = max(
                -cap_limit,
                min(cap_limit, scores[group_name] + effective_sample_llr)
            )
            self._last_update_monotonic[zone_id] = now_mono

            # 2. Capped, weighted intra-group normalization.
            #    Cross-group aggregation assumes the three evidence groups
            #    (electronic, subsurface, surface) are conditionally
            #    independent given victim presence: physically distinct
            #    sensing channels (EM flux vs ground wave vs thermal/optical).
            #    Naive-Bayes log-odds fusion is exact only under that
            #    assumption; correlated modalities would overcount evidence.
            aggregate_group_llr_sum = 0.0
            group_llr_snapshot: Dict[str, float] = {}
            for g_name, raw_score in scores.items():
                cap = float(group_caps.get(g_name, 4.5))
                weight = float(group_weights.get(g_name, 1.0))
                capped_group_llr = math.copysign(min(cap, abs(raw_score)), raw_score) * weight
                aggregate_group_llr_sum += capped_group_llr
                group_llr_snapshot[g_name] = capped_group_llr

            # 3. Spatial pass time-gating for temporal consistency
            tracker = self._pass_tracker[zone_id]
            pass_interval = float(thresholds.get("pass_interval_seconds", 5.0))
            if tracker["last_pass_time"] == 0.0 or (now_mono - tracker["last_pass_time"]) >= pass_interval:
                if tracker["sample_count"] > 0:
                    avg_pass_score = tracker["current_pass_score"] / tracker["sample_count"]
                    self._temporal_pass_history[zone_id].append(avg_pass_score)
                tracker["last_pass_time"] = now_mono
                tracker["current_pass_score"] = effective_sample_llr
                tracker["sample_count"] = 1.0
            else:
                tracker["current_pass_score"] += effective_sample_llr
                tracker["sample_count"] += 1.0

            # Evaluate multi-pass persistence bonus / penalty
            pass_history = list(self._temporal_pass_history[zone_id])
            positive_passes = sum(1 for val in pass_history if val > positive_pass_threshold)
            if len(pass_history) >= 2 and (positive_passes / len(pass_history)) >= 0.60:
                c_temporal = float(thresholds.get("temporal_persistence_bonus", 0.75))
            elif len(pass_history) >= 2 and positive_passes == 0:
                c_temporal = -float(thresholds.get("temporal_decay_penalty", 0.40))
            else:
                c_temporal = 0.0

            # 4. Cumulative state log-odds integration
            prior_p0 = self._compute_prior_prob(cell_x, cell_y, self.lkp_cell)
            l0 = math.log(prior_p0 / (1.0 - prior_p0))
            new_llr = l0 + aggregate_group_llr_sum + c_temporal
            new_llr = max(-llr_clamp, min(llr_clamp, new_llr))
            new_probability = 1.0 / (1.0 + math.exp(-new_llr))

            # 5. Spatiotemporal utility optimization
            elapsed_min = (time.time() - self.incident_epoch_s) / 60.0
            snow_density = sensor_payload.geo.snow_density_kg_m3
            p_survival = self._calculate_survival_probability(elapsed_min, snow_density)
            rescuer_risk = self.terrain.calculate_rescuer_hazard(state.slope_deg)
            search_effort = 1.0 + (0.5 * (state.burial_depth_estimate_m or 1.2))
            priority_score = (new_probability * p_survival) / (search_effort + rescuer_risk)

            # 6. Triage classification
            tau_p1 = float(thresholds.get("tau_p1", 0.85))
            tau_p2 = float(thresholds.get("tau_p2", 0.45))
            if new_probability >= tau_p1:
                priority_zone = PriorityZoneEnum.P1
                state.status = ZoneStatusEnum.ACTIVE_SEARCH
            elif new_probability >= tau_p2:
                priority_zone = PriorityZoneEnum.P2
                state.status = ZoneStatusEnum.CANDIDATE
            elif new_probability >= tau_p3:
                priority_zone = PriorityZoneEnum.P3
            else:
                priority_zone = PriorityZoneEnum.P4

            if effective_sample_llr > 0 and group_name not in state.contributing_evidence_groups:
                state.contributing_evidence_groups.append(group_name)

            if isinstance(sensor_payload, GPRPayload):
                state.burial_depth_estimate_m = sensor_payload.estimated_depth_m
            elif state.burial_depth_estimate_m is None:
                state.burial_depth_estimate_m = 1.2

            state.confidence_radius_m = max(0.3, 3.0 * (1.0 - new_probability))
            state.current_llr = new_llr
            state.probability = new_probability
            state.priority_score = priority_score
            state.priority_zone = priority_zone
            state.temporal_consistency_score = c_temporal
            state.last_updated_at = datetime.now(timezone.utc)

            # Directive Generation Guard
            directive_issued_id = None
            if priority_zone == PriorityZoneEnum.P1:
                directive, is_new = self._issue_directive_internal(state)
                if is_new:
                    directive_issued_id = directive.directive_id

        # Asynchronous non-blocking file logging outside critical state lock
        task = asyncio.create_task(
            self.logger.log_inference_event(
                zone_id=zone_id,
                cell_coords=(cell_x, cell_y),
                sensor_payload=sensor_payload.model_dump(mode="json"),
                group_llr_snapshot=group_llr_snapshot,
                posterior_p=new_probability,
                directive_issued=directive_issued_id
            )
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return state

    def _calculate_survival_probability(self, elapsed_min: float, snow_density: float) -> float:
        cfg = self.config_loader.config.get("survival_model", {})
        p1_max = cfg.get("phase1_max_minutes", 15.0)
        p1_rate = cfg.get("phase1_survival_rate", 0.92)
        p2_max = cfg.get("phase2_max_minutes", 35.0)
        drop_rate = cfg.get("phase2_drop_rate", 0.65)
        phase2_floor = cfg.get("phase2_floor_survival", 0.27)
        halflife = cfg.get("phase3_hypo_halflife_minutes", 45.0)
        base_min = cfg.get("baseline_minimum_survival", 0.03)

        if elapsed_min <= p1_max:
            return p1_rate
        elif p1_max < elapsed_min <= p2_max:
            fraction = (elapsed_min - p1_max) / (p2_max - p1_max)
            density_mult = 1.0 + (snow_density / 500.0) * 0.2
            return max(phase2_floor, p1_rate - (drop_rate * fraction * density_mult))
        else:
            decay_constant = math.log(2.0) / max(1.0, halflife)
            hypo_decay = math.exp(-decay_constant * (elapsed_min - p2_max))
            return max(base_min, phase2_floor * hypo_decay)

    def get_survival_clock_snapshot(self) -> Dict[str, Any]:
        """
        Single authoritative survival-clock computation shared with the HUD so
        the frontend never re-implements the tri-phase formula.
        """
        reference_density = float(
            self.config_loader.config.get("survival_model", {}).get("reference_density_kg_m3", 350.0)
        )
        elapsed_min = max(0.0, (time.time() - self.incident_epoch_s) / 60.0)
        return {
            "incident_epoch_s": self.incident_epoch_s,
            "server_epoch_s": time.time(),
            "elapsed_min": elapsed_min,
            "survival_probability": self._calculate_survival_probability(elapsed_min, reference_density),
        }

    def _calculate_safe_approach_azimuth(self, cell_x: int, cell_y: int) -> float:
        """
        Compass bearing (degrees clockwise from geographic North) along the
        local elevation contour, i.e. perpendicular to the fall-line.

        The terrain gradient (dz/dx eastward, dz/dy northward) points up-slope.
        Its compass bearing is atan2(East component, North component); adding
        90 degrees yields the level-contour traverse direction.

        On flat cells (zero gradient) the result defaults to due East (90 deg).
        """
        dz_dx = float(self.terrain.grad_dx[cell_y, cell_x])
        dz_dy = float(self.terrain.grad_dy[cell_y, cell_x])

        # Compass bearing of the gradient (up-slope), clockwise from North.
        fall_line_bearing_deg = math.degrees(math.atan2(dz_dx, dz_dy)) % 360.0

        # Contour-parallel approach heading is perpendicular to the fall-line.
        return (fall_line_bearing_deg + 90.0) % 360.0

    def _issue_directive_internal(self, state: GridZoneState) -> Tuple[TacticalDirective, bool]:
        for d in self.active_directives:
            if d.target_zone_id == state.zone_id:
                return d, False

        safe_azimuth = self._calculate_safe_approach_azimuth(state.cell_x, state.cell_y)
        marker_mhz = float(
            self.config_loader.config.get("mission", {}).get("marker_frequency_mhz", 866.0)
        )
        directive = TacticalDirective(
            directive_id=f"DIR_{state.zone_id}_{int(time.time())}",
            target_zone_id=state.zone_id,
            directive_type=DirectiveTypeEnum.PROBE_EXCAVATE,
            priority_zone=PriorityZoneEnum.P1,
            lat=state.lat,
            lon=state.lon,
            mgrs_coord=state.mgrs_coord,
            depth_estimate_m=state.burial_depth_estimate_m or 1.2,
            confidence_radius_m=state.confidence_radius_m or 0.7,
            approach_azimuth_deg=round(safe_azimuth, 1),
            marker_deployed=True,
            marker_frequency_mhz=marker_mhz,
            recommended_equipment=[
                "320cm Carbon Avalanche Probe",
                "High-Volume Aluminium Snow Shovels x4",
                "Hypothermia Thermal Wrap Kit",
                "Oxygen Resuscitation Bag"
            ],
            rationale=f"P1 Triage Threshold Exceeded (P={state.probability*100:.1f}%) | MGRS: {state.mgrs_coord} | Standoff Lock Confirmed"
        )
        self.active_directives.append(directive)
        state.status = ZoneStatusEnum.PROBING
        return directive, True

    async def get_search_map_summary(self) -> Dict[str, Any]:
        async with self._state_lock:
            p1 = [z.model_dump(mode="json") for z in self.grid.values() if z.priority_zone == PriorityZoneEnum.P1]
            p2 = [z.model_dump(mode="json") for z in self.grid.values() if z.priority_zone == PriorityZoneEnum.P2]
            p3 = [z.model_dump(mode="json") for z in self.grid.values() if z.priority_zone == PriorityZoneEnum.P3]
            p4_count = len(self.grid) - len(p1) - len(p2) - len(p3)

            return {
                "incident_id": "INCIDENT_HIMALAYA_2026_01",
                "elapsed_seconds": int(time.time() - self.incident_epoch_s),
                "mission_clock": self.get_survival_clock_snapshot(),
                "summary": {
                    "p1_count": len(p1),
                    "p2_count": len(p2),
                    "p3_count": len(p3),
                    "p4_count": p4_count
                },
                "directives": [d.model_dump(mode="json") for d in self.active_directives],
                "high_priority_zones": p1 + p2
            }
