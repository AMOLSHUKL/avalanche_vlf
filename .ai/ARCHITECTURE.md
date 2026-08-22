# AVALANCHE-VLF: Architectural & Mathematical Specification
**Document Classification:** Technical Source of Truth  
**Target Organization:** Defence Research & Development Organisation (DRDO / DGRE)  
**Problem Statement:** SIH260104 — Devise the method for identification of victims buried under avalanches

---

## 1. System Topology & Module Architecture

```
avalanche_vlf/
├── config/
│   └── fusion_parameters.yaml          # Master configuration: thresholds, priors, group caps, survival parameters
├── backend/
│   ├── main.py                         # FastAPI gateway, ConnectionManager, lifespan worker, REST & WebSocket routes
│   ├── config/
│   │   └── loader.py                   # Validated singleton ConfigLoader with atomic persistence and hot-swap rejection
│   ├── engine/
│   │   ├── fusion.py                   # Recursive Bayesian Log-Odds Fusion Engine and Tactical Directive issuer
│   │   ├── geo.py                      # Dependency-free WGS84 <-> UTM <-> MGRS (USGS PP 1395 / NGA TM 8358.1)
│   │   ├── logger.py                   # Non-blocking async JSONL verification and fine-tuning telemetry logger
│   │   ├── terrain.py                  # Digital Elevation Model (DEM) generator, spatial priors, rescuer hazard
│   │   └── adapters/
│   │       ├── base.py                 # Abstract BaseSensorAdapter with reliability-mixture LLR formulation
│   │       ├── rf.py                   # Group A: 457 kHz beacon, RECCO harmonic radar, cellular IMSI adapters
│   │       ├── gpr.py                  # Group B: Subsurface UWB GPR adapter with snow density attenuation
│   │       ├── seismic.py              # Group B: Micro-acoustic and seismic geophone pulse adapter
│   │       ├── thermal.py              # Group C: Long-Wave Infrared (LWIR) thermal skin-depth adapter
│   │       ├── optical.py              # Group C: High-resolution RGB visual and shadow anomaly adapter
│   │       └── registry.py             # Polymorphic adapter registry bound to ConfigLoader
│   ├── schemas/
│   │   ├── domain.py                   # Tactical directives, grid states, UAV kinematics, WebSocket envelopes
│   │   └── sensors.py                  # Typed Pydantic v2 sensor payloads, permittivity bounds, UTC validators
│   └── telemetry/
│       ├── lora_packet.py              # 16-byte packed binary C-struct LoRaWAN encoder/decoder with CRC-16
│       └── simulator.py                # Dual UAV flight generator, 5-phase SAR state machine, fault injector
├── frontend/
│   ├── index.html                      # Tactical Operations HUD, 15-min timer, 2D Canvas, DSP modal UI
│   └── app.js                          # Canvas Y-axis inversion, WebSocket consumer, server-anchored mission clock
├── scripts/
│   └── calibrate_parameters.py         # Post-mission Maximum A Posteriori (MAP) prior optimization pipeline
└── tests/
    ├── test_fusion.py                  # Fusion math, temporal filter, azimuth frame, LoRa roundtrip, concurrency
    ├── test_geo.py                     # MGRS anchors, central-meridian exactness, global round-trip closure
    ├── test_config_validation.py       # Config boundary rejections and hot-swap atomicity
    └── test_api.py                     # API boundary smoke tests
```

---

## 2. Sensor Evidence Hierarchy & Anti-Correlation Grouping

To prevent multi-sensor correlation bias (e.g., three co-located RF detectors tripling confidence without independent confirmation), modalities are strictly partitioned into three mutually exclusive evidence groups. Each group is subject to an independent **Evidence Group Saturation Cap ($\Gamma_g$)** and a static **Group Confidence Weight ($w_g$)**:

```
+---------------------------------------------------------------------------------------------------+
| GROUP A: PERSON-SPECIFIC ELECTRONIC SENSORS (Cap Gamma_A = 4.5 | Weight w_A = 1.00)               |
| Modalities: 457 kHz Avalanche Transceiver, RECCO Harmonic Radar, Cellular / Mobile IMSI Sniffer   |
| Characteristics: High specificity, zero biological confirmation, direct subject hardware required|
+---------------------------------------------------------------------------------------------------+
| GROUP B: SUBSURFACE STRUCTURAL & LIFE-SIGN SENSORS (Cap Gamma_B = 4.2 | Weight w_B = 0.95)        |
| Modalities: Ultra-Wideband GPR (Dielectric Er ~ 50-55), Micro-Doppler Respiration (0.2-0.4 Hz),   |
|             Micro-Seismic Geophone Acoustic Pulse (Tapping / Impulse Detection)                  |
| Characteristics: Detects non-cooperative/passive targets, penetrates dense snowpack (0-15m)       |
+---------------------------------------------------------------------------------------------------+
| GROUP C: SURFACE OPTICAL & THERMAL SENSORS (Cap Gamma_C = 2.5 | Weight w_C = 0.65)                |
| Modalities: Long-Wave Infrared (LWIR) Radiometric Thermal, High-Resolution RGB Visual Camera      |
| Characteristics: Shallow / surface exposure only (<0.20m), subject to solar & wind degradation   |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Mathematical Decision Engine

### 3.1 Contextual Spatial Prior Probability ($P_0$)
The initial spatial prior for search cell $i = (x, y)$ is derived from the Last Known Position (LKP) Gaussian dispersion and the Digital Elevation Model (DEM) slope inclination:
$$P_0(i) = \max\left(0.01, \min\left(0.95, P_{\text{LKP}}(i) \cdot P_{\text{slope}}(\theta_i)\right)\right)$$

Where:
$$P_{\text{LKP}}(i) = \exp\left(-\frac{\|\mathbf{x}_i - \mathbf{x}_{\text{LKP}}\|^2}{2\sigma_{\text{LKP}}^2}\right) \quad (\sigma_{\text{LKP}} = 85.0\,\text{m})$$

Slope probability $P_{\text{slope}}(\theta)$ models avalanche deposition dynamics:
$$P_{\text{slope}}(\theta) = \begin{cases} 
0.65 & \theta < 15^\circ \quad (\text{Runout Deposition Plain}) \\
0.95 & 15^\circ \le \theta \le 32^\circ \quad (\text{Primary Avalanche Catchment Basin}) \\
0.35 & 32^\circ < \theta \le 45^\circ \quad (\text{Track / Slab Zone}) \\
0.05 & \theta > 45^\circ \quad (\text{Extreme Cliff Face / No Snow Accumulation})
\end{cases}$$

The base log-odds prior is:
$$L_0(i) = \ln\left(\frac{P_0(i)}{1 - P_0(i)}\right)$$

### 3.2 Sensor Log-Likelihood Ratio (Reliability Mixture)
For a sensor measurement with confidence score $c \in [0.0, 1.0]$ and validated sensor priors $P(z \mid H)$, $P(z \mid \neg H)$ (clamped to $[0.001, 0.999]$), the effective LLR is the expected log-likelihood ratio under a reliability mixture — $c$ is the probability that the reading reflects the true cell state:
$$\text{LLR}_{\text{detect}} = \ln\left(\frac{P(z \mid H)}{P(z \mid \neg H)}\right), \quad \text{LLR}_{\text{null}} = \ln\left(\frac{1 - P(z \mid H)}{1 - P(z \mid \neg H)}\right)$$
$$\text{LLR}_{\text{eff}} = c \cdot \text{LLR}_{\text{detect}} + (1 - c) \cdot \text{LLR}_{\text{null}}$$

* If $c \approx 1.0$, $\text{LLR}_{\text{eff}} > 0$ (Confirmatory evidence).
* If $c \approx 0.0$, $\text{LLR}_{\text{eff}} < 0$ (Negative evidence / Area clear).
* The neutral point $c^*$ where $\text{LLR}_{\text{eff}} = 0$ is **not** 0.5; it depends on modality discriminability: a sharper sensor (larger $\ln\frac{P(z|H)}{P(z|\neg H)}$) pushes $c^*$ lower. This asymmetry is intentional.
* Sensors that never observe a cell contribute exactly zero: no scan, no update.

### 3.3 Environmental Quality Attenuation ($q_k$)
Each sensor payload is attenuated by physical environmental factors ($q_k \in [0.05, 1.0]$):
* **457 kHz / Mobile RF:** $q_{\text{RF}} = \frac{1}{1 + \kappa_{\text{EMI}} \cdot \max(0, \text{Noise}_{\text{EMI}} - (-105.0))}$
* **UWB GPR:** $q_{\text{GPR}} = \exp\left(-\kappa_{\text{SWE}} \cdot \frac{\rho_{\text{snow}}}{100.0} \cdot d\right) \cdot \text{Eccentricity}$
* **Thermal IR:** $q_{\text{Thermal}} = \exp(-3.5 \cdot d_{\text{snow}}) \cdot \frac{1}{1 + v_{\text{wind}} \cdot \kappa_{\text{wind}}} \cdot \min\left(1.0, \frac{|\Delta T|}{8.0}\right)$
* **Micro-Seismic:** $q_{\text{Seismic}} = \frac{1}{1 + \exp(-0.1 \cdot (\text{SNR} - 5.0))} \cdot \frac{1}{1 + \max(0, \text{Noise}_{\text{ambient}} - 40.0) \cdot \kappa_{\text{acoustic}}}$

### 3.4 Leaky Intra-Group Evidence Accumulation (Time-Based)
Group accumulators decay by factor $\gamma = 0.96$ **per second of elapsed wall time**, so staleness depends on real time, not on how often a cell happens to be scanned. With $\Delta t_i$ seconds since cell $i$'s previous update:
$$D_i(t) = \gamma^{\Delta t_i}, \qquad S_g(i, t) = \operatorname{clip}_{\pm\Gamma_g}\!\left(D_i \cdot S_g(i, t-1) + \mathbb{1}[g = g_{\text{obs}}] \cdot \text{LLR}(i,t) \cdot q_k(i,t)\right)$$
$$\Lambda_g(i, t) = \operatorname{sign}\left(S_g(i, t)\right) \cdot \min\left(\Gamma_g, |S_g(i, t)|\right) \cdot w_g$$

All interval arithmetic uses `time.monotonic()`; NTP wall-clock steps cannot corrupt leak or pass-gating intervals.

### 3.5 Spatiotemporal Multi-Pass Persistence Filter ($C_{\text{temporal}}$)
Search passes over cell $i$ separated by $\Delta t \ge 5.0\,\text{s}$ are tracked in a 4-pass FIFO history window. A pass average counts as positive when it exceeds `positive_pass_threshold` (default $+0.30$):
$$C_{\text{temporal}} = \begin{cases} 
+0.75 & \text{if } N_{\text{passes}} \ge 2 \text{ and } (\text{PositivePasses} / N_{\text{passes}}) \ge 0.60 \\
-0.40 & \text{if } N_{\text{passes}} \ge 2 \text{ and } \text{PositivePasses} = 0 \\
0.0 & \text{otherwise}
\end{cases}$$

### 3.6 Posterior Probability Formulation
$$L_t(i) = \operatorname{clip}_{\pm L_{\max}}\!\left(L_0(i) + \sum_{g \in \{A, B, C\}} \Lambda_g(i, t) + C_{\text{temporal}}(i, t)\right), \quad L_{\max} = 15.0 \text{ (configurable)}$$
$$P(H_i \mid \mathbf{Z}_{1:t}) = \frac{1}{1 + \exp(-L_t(i))}$$

### 3.7 Tri-Phase Biophysical Decision Utility
Operational ranking maximizes survival probability per unit search effort and rescuer hazard:
$$U(i, t) = \frac{P(H_i \mid \mathbf{Z}_{1:t}) \cdot S(t_{\text{elapsed}}, \rho_{\text{snow}})}{E_{\text{search}}(d_i) + R_{\text{hazard}}(\theta_i)}$$

Where:
* **Tri-Phase Survival Curve $S(t, \rho)$** (all constants configurable under `survival_model`):
  $$S(t, \rho) = \begin{cases} 
  0.92 & t \le 15\,\text{min} \quad (\text{Phase 1: Clear Airway Plateau}) \\
  \max\left(0.27, 0.92 - 0.65 \cdot \left(\frac{t - 15}{20}\right) \cdot \left(1 + \frac{\rho}{500} \cdot 0.2\right)\right) & 15 < t \le 35\,\text{min} \quad (\text{Phase 2: Asphyxiation Cliff}) \\
  \max\left(0.03, 0.27 \cdot \exp\left(-\frac{\ln 2}{45.0} (t - 35)\right)\right) & t > 35\,\text{min} \quad (\text{Phase 3: Hypothermia Plateau})
  \end{cases}$$
  $t$ is measured from the **incident epoch** (`mission.incident_epoch_s`), not from server start; the HUD consumes this clock from the backend rather than re-implementing it.
* **Monotonic Rescuer Slope Hazard $R_{\text{hazard}}(\theta)$:**
  $$R_{\text{hazard}}(\theta) = \begin{cases} 
  1.0 & \theta < 25^\circ \\
  1.0 + 3.5 \cdot \sin^2\left(\frac{\pi}{2} \frac{\theta - 25}{20}\right) & 25^\circ \le \theta \le 45^\circ \quad (\text{Primary Avalanche Slab Hazard}) \\
  4.5 + 0.15 \cdot (\theta - 45^\circ) & \theta > 45^\circ \quad (\text{Extreme Precipice})
  \end{cases}$$
* **Search Effort:** $E_{\text{search}}(d) = 1.0 + 0.5 \cdot d_{\text{burial}}$

### 3.8 Safe Contour-Parallel Approach Azimuth
To prevent rescue teams from triggering secondary slab releases by traversing directly up or down the fall-line, the approach heading is computed perpendicular to the terrain gradient **in compass frame** (degrees clockwise from North). The gradient components $(z_x, z_y)$ point eastward and northward up-slope; a compass bearing converts to a unit vector $(\sin\theta_{az}, \cos\theta_{az})$ in that same (East, North) frame:
$$\frac{\partial z}{\partial x} \approx \frac{z_{x+1, y} - z_{x-1, y}}{2 \cdot \Delta x}, \quad \frac{\partial z}{\partial y} \approx \frac{z_{x, y+1} - z_{x, y-1}}{2 \cdot \Delta y}$$
$$\theta_{\text{fall-line}} = \operatorname{atan2}\left(\frac{\partial z}{\partial x}, \frac{\partial z}{\partial y}\right) \pmod{360^\circ} \qquad \text{(compass bearing of up-slope direction)}$$
$$\theta_{\text{approach}} = \left(\theta_{\text{fall-line}} + 90.0^\circ\right) \pmod{360^\circ}$$

A surface rising due North ($z_x = 0$, $z_y > 0$) therefore yields $\theta_{\text{approach}} = 90^\circ$ (due East), i.e., along the contour — verified by a perpendicularity property test (`dot(grad, approach_unit) = 0`).

---

## 4. State & Schema Data Reference

### 4.1 Grid Zone State (`GridZoneState`)
Represents an individual $5\text{m} \times 5\text{m}$ discrete search cell within the $100 \times 100$ operational grid:
```python
class GridZoneState(BaseModel):
    zone_id: str                          # e.g., "cell_45_35"
    cell_x: int                           # [0..99]
    cell_y: int                           # [0..99]
    lat: float                            # WGS84 Decimal Degrees
    lon: float                            # WGS84 Decimal Degrees
    mgrs_coord: str                       # True WGS84->MGRS conversion (e.g., "43S GT 36343 85694")
    elevation_m: float                    # DEM Surface Elevation AMSL (m)
    slope_deg: float                      # Local Terrain Inclination (0.0..90.0 deg)
    current_llr: float                    # Bayesian Log-Odds [-50.0..50.0]
    probability: float                    # Posterior Probability [0.0..1.0]
    priority_score: float                 # Decision Utility Score U
    priority_zone: PriorityZoneEnum       # P1 (>=0.85), P2 (>=0.45), P3 (>=0.15), P4 (<0.15)
    status: ZoneStatusEnum                # UNSEEN, CANDIDATE, ACTIVE_SEARCH, PROBING, CONFIRMED
    burial_depth_estimate_m: Optional[float] # Radar Two-Way Travel Time Depth Estimate Z (m)
    confidence_radius_m: Optional[float]     # Spatial Uncertainty Radius (m)
    contributing_evidence_groups: List[str]  # ["GROUP_A_ELECTRONIC", "GROUP_B_SUBSURFACE"]
    temporal_consistency_score: float    # Multi-pass bonus/penalty [-10.0..10.0]
    last_updated_at: datetime             # Enforced UTC Timestamp
```

### 4.2 LoRa Binary C-Struct Specification (`LoRaTargetPacket`)
Target vectors are encoded into an exact 16-byte binary C-struct for transmission over mountain mesh radios:

```
+--------+--------+--------+--------+---------+--------+---------+--------+----------+-----------+--------+
| Byte 0 | Byte 1 | Byte 2 | Byte 3 | Byte4-5 | Byte 6 | Byte7-8 | Byte 9 | Byte10-11| Byte12-13 | Byte14-15
+--------+--------+--------+--------+---------+--------+---------+--------+----------+-----------+--------+
| msg_typ| cell_x | cell_y | prob_sc| depth_cm| radius_| az_deci | flags  | east_off | north_off | crc16  |
| (uint8)| (uint8)| (uint8)| (uint8)| (uint16)| dm(u8) | (uint16)| (uint8)| m (uint16)| m (uint16)|(uint16)|
+--------+--------+--------+--------+---------+--------+---------+--------+----------+-----------+--------+
```
* **Struct String:** `!BBBBHBHBHHH` (Big-Endian, 16 Bytes Fixed).
* **Position fields:** `east_off_m` / `north_off_m` are meter offsets from the **mission grid origin** (`MissionGridFrame`: UTM zone, MGRS band + 100 km square, origin easting/northing). Absolute eastings (e.g. 736122 m) do not fit uint16, and modulo packing is lossy; offsets are unambiguous and reconstruct to a full 10-digit MGRS reference via `to_mgrs_string(frame)`. Every participant receives the frame in the mission briefing.
* **Flags Bitmask:** `Bit 0: marker_deployed`, `Bit 1: respiration_locked`, `Bit 2: is_p1`, `Bit 3: void_flag`.
* **Checksum:** CRC-16/CCITT-FALSE (`0x1021` polynomial, `0xFFFF` init, no reflection/xorout).
* **Range guards:** offsets outside `[0, 65535]` raise instead of silently wrapping.

---

## 5. Determinism & Defence Auditability Guarantee

1. **Zero Black-Box LLMs in Triage Path:** All log-odds updates, group capping, survival probabilities, and hazard scorings are computed via closed-form analytical equations.
2. **Strict Reproducibility:** Given identical sensor inputs and timestamps, the system generates identical log-odds and directives across runs.
3. **Structured JSONL Audit Trail:** Every inference step, sensor payload, intermediate group accumulator snapshot, and issued directive is recorded to `logs/sar_mission_*.jsonl` via non-blocking background workers (`asyncio.to_thread`) for post-mission accountability and MAP parameter fine-tuning.