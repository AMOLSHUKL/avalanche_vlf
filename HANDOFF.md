# AVALANCHE-VLF: Operational Handoff & Technical Manual
**Target Audience:** Defence Research & Development Organisation (DRDO / DGRE) Systems Engineers  
**System Designation:** Autonomous Airborne Sensor Fusion Platform for Avalanche SAR (PS SIH260104, Theme: Disaster Management)

---

## 1. Institutional Context & Purpose

This operational manual provides defence engineers at the **Defence Geoinformatics Research Establishment (DGRE)** and **DRDO** with complete procedures for integrating physical sensor hardware, modifying tactical parameters, calibrating likelihood priors, and deploying the complete software stack in air-gapped, high-altitude military environments (e.g., Siachen Base Camp, Leh Tactical Air Base).

---

## 2. Sensor Adapter Framework: Integrating Military Hardware

All sensor drivers in `AVALANCHE-VLF` inherit from `BaseSensorAdapter` located in `backend/engine/adapters/base.py`. To interface a physical military-grade sensor (e.g., DRDO Airborne 500 MHz Ground Penetrating Radar Pod or UAV-mounted LWIR Radiometer):

### Step 1: Subclass `BaseSensorAdapter`
Create your concrete adapter class implementing `parse_raw()` and `evaluate_quality()`:

```python
# File: backend/engine/adapters/drdo_gpr.py
import math
import struct
from typing import Any
from backend.config.loader import ConfigLoader
from backend.engine.adapters.base import BaseSensorAdapter
from backend.schemas.sensors import GPRPayload, GeospatialContext, SensorTypeEnum

class DRDOAirborneGPRAdapter(BaseSensorAdapter):
    """
    Hardware bridge for DRDO Airborne 500 MHz UWB Radar Pod streaming
    raw binary telemetry frames over UDP/Serial.
    """
    def __init__(self, config_loader: ConfigLoader):
        super().__init__(SensorTypeEnum.GPR.value, config_loader)

    def parse_raw(self, raw_input: Any) -> GPRPayload:
        if isinstance(raw_input, GPRPayload):
            return raw_input
        if isinstance(raw_input, bytes):
            # Example: Unpack 32-byte physical radar struct:
            # [lat(d), lon(d), alt(f), depth(f), ecc(f), er(f), resp_hz(f), conf(f)]
            lat, lon, alt, depth, ecc, er, resp_hz, conf = struct.unpack("!ddffffff", raw_input)
            return GPRPayload(
                sensor_id="DRDO_GPR_POD_01",
                geo=GeospatialContext(lat=lat, lon=lon, altitude_m=alt),
                confidence_score=max(0.0, min(1.0, conf)),
                estimated_depth_m=depth,
                hyperbola_eccentricity=ecc,
                dielectric_contrast=7.5,
                relative_permittivity=er,
                micro_doppler_frequency_hz=resp_hz if resp_hz > 0.1 else None,
                respiration_locked=(0.15 <= resp_hz <= 0.45),
                void_anomaly_flag=(depth > 1.0)
            )
        raise ValueError(f"Unsupported input format for DRDOAirborneGPRAdapter: {type(raw_input)}")

    def evaluate_quality(self, payload: GPRPayload) -> float:
        # Dielectric absorption through wet snowpack based on bulk snow density
        density = payload.geo.snow_density_kg_m3
        depth = payload.estimated_depth_m
        attenuation_params = self.config_loader.config.get("environmental_attenuation", {})
        kappa = attenuation_params.get("snow_water_equivalent_penalty_factor", 0.0028)
        
        q_env = math.exp(-kappa * (density / 100.0) * depth)
        q_eccentricity = payload.hyperbola_eccentricity
        return max(0.05, min(1.0, q_env * q_eccentricity))
```

### Step 2: Register in `AdapterRegistry`
Bind your concrete adapter inside `backend/engine/adapters/registry.py`:

```python
# File: backend/engine/adapters/registry.py
from backend.engine.adapters.drdo_gpr import DRDOAirborneGPRAdapter
# ...
self._adapters[SensorTypeEnum.GPR] = DRDOAirborneGPRAdapter(config_loader)
```

---

## 3. Dynamic Parameter Tuning & Offline MAP Calibration

### 3.1 Master Configuration (`config/fusion_parameters.yaml`)
Tactical thresholds and likelihood priors are defined in YAML and dynamically managed via `ConfigLoader`:

```yaml
version: 1
activated_by: "DGRE_SYSTEM_INIT"
grid:
  width_m: 500.0
  height_m: 500.0
  cell_size_m: 5.0
  origin_lat: 34.183900
  origin_lon: 77.562100
thresholds:
  tau_p1: 0.85                      # Probability threshold for P1 PROBE_EXCAVATE
  tau_p2: 0.45                      # Probability threshold for P2 SECONDARY_SCAN
  evidence_decay_factor: 0.96       # Leaky accumulator retention factor (gamma)
  temporal_persistence_bonus: 0.75  # Bonus for multi-pass confirmed persistence
  temporal_decay_penalty: 0.40      # Penalty for transient clutter / ghost noise
group_caps:
  GROUP_A_ELECTRONIC: 4.5           # Max log-odds saturation for Group A
  GROUP_B_SUBSURFACE: 4.2           # Max log-odds saturation for Group B
  GROUP_C_SURFACE: 2.5              # Max log-odds saturation for Group C
group_weights:
  GROUP_A_ELECTRONIC: 1.00
  GROUP_B_SUBSURFACE: 0.95
  GROUP_C_SURFACE: 0.65
sensor_priors:
  GPR:
    p_z_given_h: 0.90
    p_z_given_not_h: 0.07
```

### 3.2 Dynamic Runtime Parameter Hot-Swapping
Update parameters on running nodes without interrupting ongoing mission threads:
```bash
curl -X PUT http://localhost:8000/api/config/fusion-parameters \
  -H "Content-Type: application/json" \
  -d '{
    "activated_by": "DGRE_FIELD_COMMANDER",
    "parameters": {
      "thresholds": {
        "tau_p1": 0.88,
        "evidence_decay_factor": 0.95
      }
    }
  }'
```

### 3.3 Post-Mission MAP Calibration Pipeline
Following physical ground verification (probing depth and confirmed victim status), execute the Maximum A Posteriori (MAP) script to optimize sensor priors against recorded mission telemetry:
```bash
python -m scripts.calibrate_parameters \
  --mission-logs logs/sar_mission_20260816_115100.jsonl \
  --ground-truth data/field_truth_verification.csv \
  --base-config config/fusion_parameters.yaml \
  --output config/fusion_parameters.yaml
```

---

## 4. Air-Gapped Edge Deployment Architecture

```
+---------------------------------------------------------------------------------------------------+
| AIR-GAPPED TACTICAL RUNTIME DEPLOYMENT                                                            |
|                                                                                                   |
| [ UAV Drone 1 (Alpha) ]           [ UAV Drone 2 (Bravo) ]                                         |
|  - Jetson Orin Nano (Edge DSP)     - Jetson Orin Nano (Radar DSP)                                 |
|  - Ingests 457kHz / Thermal / RGB  - Ingests UWB GPR / Respiration / Seismic                      |
|                  \                       /                                                        |
|                   \                     /  868/915 MHz LoRa Mesh / MANET Radio                    |
|                    v                   v                                                          |
|        +--------------------------------------------------+                                       |
|        | COMMAND POST EDGE SERVER (NVIDIA Jetson Orin AGX |                                       |
|        | or Rugged Field Laptop - Ubuntu 22.04 LTS)       |                                       |
|        |  - Docker Container: `avalanche-vlf:latest`      |                                       |
|        |  - Fully Offline FastAPI ASGI Service (Port 8000)|                                       |
|        |  - Non-blocking JSONL Telemetry Audit Logger     |                                       |
|        +-------------------------+------------------------+                                       |
|                                  |                                                                |
|                 Direct Ethernet / Local Wi-Fi AP                                                  |
|                                  v                                                                |
|        +--------------------------------------------------+                                       |
|        | TACTICAL HUD TERMINAL (Toughbook / Tablet)       |                                       |
|        |  - Zero-dependency ES6+ Single Page Interface    |                                       |
|        |  - 10 Hz Real-Time Canvas / Micro-Doppler Wave   |                                       |
|        +--------------------------------------------------+                                       |
+---------------------------------------------------------------------------------------------------+
```

### 4.1 Deployment Commands
```bash
# 1. Build Multi-Stage Docker Container
docker build -t avalanche-vlf:latest .

# 2. Run Container in Air-Gapped Mode
docker run -d \
  -p 8000:8000 \
  --restart unless-stopped \
  --name sar-command-node \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  avalanche-vlf:latest

# 3. Verify Health Probe
docker exec -it sar-command-node python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/healthz').read().decode())"