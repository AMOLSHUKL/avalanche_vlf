# AVALANCHE-VLF

### Autonomous Multi-Modal Sensor Fusion & Decision-Support Engine for Avalanche SAR

**Smart India Hackathon 2026 | Ministry of Defence (MoD) / DRDO / DGRE | Problem Statement `SIH260104` — Identification of victims buried under avalanches (Theme: Disaster Management)**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?style=flat-square)](https://python.org)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square)](https://docs.pydantic.dev)
[![Tests](https://img.shields.io/badge/tests-367%20passing-brightgreen?style=flat-square)](#4-verification)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)

---

## 1. Why this exists

A buried avalanche victim has roughly **90% survival probability if extracted within 15 minutes**, falling below 30% past 35 minutes. In high-altitude sectors such as Siachen, Ladakh, and North Sikkim, manual Search and Rescue (SAR) mobilization alone consumes 30 to 60+ minutes. Passive victims — civilians, porters, unequipped personnel — carry no 457 kHz transceiver and no RECCO reflector.

AVALANCHE-VLF is an edge-native, time-aware sensor fusion and decision-support engine for rapid UAV SAR sweeps. It runs fully offline on a Jetson-class edge node or rugged laptop and:

1. Ingests 7 sensor modalities across 3 independent evidence groups (Electronic, Subsurface, Surface).
2. Detects non-cooperative victims through GPR dielectric anomalies (human tissue εr ≈ 50–55 vs snow εr ≈ 3.2) and micro-Doppler chest-wall respiration (0.2–0.4 Hz).
3. Fuses evidence with **recursive Bayesian log-odds**, leaky per-group accumulators (γ = 0.96/s), and strict saturation caps that stop co-located sensors from inflating confidence.
4. Ranks search sectors by coupling spatial occupancy with a tri-phase biophysical survival model S(t, ρ) and a monotonic rescuer slope hazard function.
5. Emits tactical directives with true 10-digit MGRS grid references, burial depth Z, and contour-parallel safe approach azimuths, packaged as 16-byte binary LoRa frames with CRC-16.

Every number in the triage path comes from closed-form equations documented in [`.ai/ARCHITECTURE.md`](.ai/ARCHITECTURE.md). No stochastic ML sits between a sensor reading and a rescue directive; every log-odds update is auditable from the JSONL mission log.

## 2. How the fusion core thinks

* **Anti-correlation group capping.** Modalities are partitioned into Group A (Electronic: 457 kHz, RECCO, cellular IMSI), Group B (Subsurface: UWB GPR, micro-Doppler, seismic), and Group C (Surface: LWIR thermal, RGB). Each group saturates at its own cap (Γ_A = 4.5, Γ_B = 4.2, Γ_C = 2.5 log-odds), so ten co-located RF receivers still cannot reach P1 without cross-group confirmation.
* **Zero-penalty missing modalities.** Sensors that never observe a cell contribute nothing; adapters produce negative evidence only when they actually scan and report absence.
* **Time-based evidence decay.** Group accumulators retain γ = 0.96 *per second*, so decay depends on elapsed wall time, not on how often a cell happens to be scanned.
* **Multi-pass persistence.** Transient clutter is suppressed by a temporal filter: repeated detections across passes ≥ 5 s apart earn +0.75 log-odds, consistent ghosts lose 0.40.
* **Deterministic directives.** P1 cells (P ≥ τ_P1 = 0.85) immediately produce a directive: true MGRS reference (WGS84 → UTM → MGRS, Snyder/NGA standard), depth estimate, and an approach heading perpendicular to the terrain fall-line so responders traverse contours instead of triggering slabs.

## 3. Architecture at a glance

```
UAV SENSING LAYER (simulated here; hardware bridges land in Phase 6)
  UAV-Alpha: 457 kHz RF, cellular IMSI, LWIR thermal, RGB
  UAV-Bravo: UWB GPR + micro-Doppler, RECCO, micro-seismic
        |  typed Pydantic payloads
        v
FUSION CORE (FastAPI, this repo)
  adapters -> symmetric LLR + environmental quality q_k
  leaky group accumulators -> caps -> weighted sum
  multi-pass persistence filter
  DEM priors + rescuer hazard + survival utility ranking
        |                                   |
        v                                   v
16-byte LoRa C-struct              WebSocket HUD (10 Hz)
(!BBBBHBHBHHH, CRC-16)             canvas map, triage queue,
                                   DSP inspector, fault injection
```

Module map:

```
backend/
├── main.py                 # FastAPI gateway: REST, WebSocket, telemetry loop
├── config/loader.py        # Validated, hot-swappable YAML configuration
├── engine/
│   ├── fusion.py           # Bayesian log-odds fusion engine + directives
│   ├── geo.py              # WGS84 <-> UTM <-> MGRS (dependency-free)
│   ├── terrain.py          # DEM, slope priors, rescuer hazard function
│   ├── logger.py           # Non-blocking JSONL audit trail
│   └── adapters/           # 7 polymorphic sensor adapters + registry
├── schemas/                # Pydantic v2 domain + sensor contracts
└── telemetry/
    ├── lora_packet.py      # 16-byte binary wire format with CRC-16
    └── simulator.py        # Dual-UAV flight generator, 5-phase state machine
frontend/                   # Zero-dependency ES6 tactical HUD
scripts/calibrate_parameters.py   # Post-mission MAP prior calibration
tests/                      # 367-test verification suite
```

## 4. Verification

```bash
# 1. Clone and set up
git clone https://github.com/<your-org>/avalanche-vlf.git
cd avalanche-vlf
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Run the full test suite (367 tests)
pytest tests/ -v --tb=short

# 3. Launch the tactical server
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 4. Open the command dashboard
xdg-open http://localhost:8000/frontend/index.html
```

The suite covers: Bayesian alignment to P1 lock, non-cooperative victim fallback, negative-evidence symmetry, leaky anti-windup retraction, hazard monotonicity, schema bounds, dynamic survival binding, concurrency lock safety under parallel workers, MGRS correctness against the published null-island anchor `31N AA 66021 00000` plus global sub-millimeter round-trip closure, contour-perpendicular approach azimuths, LoRa round-trip packaging, and API boundary validation.

## 5. API quick reference

```bash
# Liveness and grid stats
curl -s http://localhost:8000/api/healthz

# Triage state: zone counts, active directives, mission clock
curl -s http://localhost:8000/api/search-map

# Disable a modality live (fault injection)
curl -s -X POST http://localhost:8000/api/inject-failure \
  -H "Content-Type: application/json" \
  -d '{"sensor_type": "TRANSCEIVER_457", "is_disabled": true}'

# Hot-swap validated fusion parameters (bumps version, persists atomically)
curl -s -X PUT http://localhost:8000/api/config/fusion-parameters \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"thresholds": {"tau_p1": 0.88}}, "activated_by": "COMMANDER_HOTFIX"}'

# Live telemetry stream
websocat ws://localhost:8000/ws/telemetry
```

Invalid updates are rejected with HTTP 422 before touching engine state; unknown sensors fail loudly rather than fusing with silent defaults.

## 6. Honest limitations

Read this before deploying anything real.

* **All sensor data is simulated.** The adapters, payloads, and physics models are production-shaped, but no physical radar, radio, or camera is attached yet. Hardware bridges (SPI/UART LoRa, SEGY radar ingestion, MAVLink) are scoped in [`.ai/PROJECT_STATE.md`](.ai/PROJECT_STATE.md).
* **The DEM is synthetic.** `TerrainEngine` generates an analytical Himalayan gully profile; GeoTIFF elevation ingestion is planned. Slope priors are demo-grade until then.
* **Survival parameters are literature-informed defaults**, not clinical constants. The tri-phase curve is configurable in YAML and intended for calibration against DGRE field data via `scripts/calibrate_parameters.py`.
* **The REST API has no authentication.** It assumes an isolated, air-gapped operational network. Add auth before exposing it anywhere routable.
* **MGRS output is genuine** (WGS84 → UTM → MGRS per USGS PP 1395 / NGA TM 8358.1), verified against published anchors — but grid *priors* assume the incident origin and LKP configured in YAML match reality.

## 7. Deployment

A multi-stage Dockerfile ships the stack for air-gapped edge nodes:

```bash
docker build -t avalanche-vlf:latest .
docker run -d \
  -p 8000:8000 \
  --restart unless-stopped \
  --name sar-command-node \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  avalanche-vlf:latest

# Verify inside the container
docker exec sar-command-node python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/healthz').read().decode())"
```

Configuration hot-swaps persist atomically into the mounted `config/` volume; mission audit logs stream into `logs/sar_mission_*.jsonl`.

## 8. License

Apache 2.0 — see [LICENSE](LICENSE). Government agencies, defence laboratories, and SAR first responders are granted unrestricted evaluation and deployment rights for humanitarian and disaster-relief operations, per the notice appended there.
