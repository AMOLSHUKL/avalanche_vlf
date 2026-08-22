# AVALANCHE-VLF: Mission Fit & Expansion Strategy
**Problem Statement:** SIH260104 — "Devise the method for identification of victims buried under avalanches" (Theme: Disaster Management; MoD / DRDO / DGRE).
**Audience:** DGRE systems engineers, team roadmap planning.
**Status of evidence:** PS objective space confirmed against published avalanche-UAV solutions and 2015–2025 UAV-avalanche literature (Silvagni 2017, Azzollini 2020, Toson 2021, Janovec 2022, Sky Savers 2025); DGRE technology-foresight areas from drdo.gov.in.

---

## 1. The objective, from first principles

SIH260104 asks for one outcome: **cut the time between burial and a rescuer standing on the right 10 m patch of debris.** Everything else is constraint. Decomposed:

1. **Search fast.** A debris field of ~0.25 km² must be swept in minutes, not the 50+ minutes a probe line needs.
2. **Detect everyone.** Equipped victims (457 kHz beacon), semi-equipped (RECCO, phone), and passive victims (nothing). Passive detection is the differentiator — no commercial system does it well.
3. **Localize precisely.** The output must land a probe strike within ~1 m; every meter of error costs dig time from a shrinking survival budget.
4. **Deliver to humans.** Coordinates, depth, and a safe approach must reach rescuers over links that work in a deep mountain valley with no cellular coverage.
5. **Never mislead.** A false positive costs wasted minutes; a false negative costs a life. The system must be honest about both and biased against the second.

### Where the current build stands against each

| Objective | Status | Evidence |
| :--- | :--- | :--- |
| Fast search | Architecture ready, flight unproven | Dual-UAV lawn-mower planner simulated at realistic speeds; no real airframe yet |
| Detect everyone | Fusion design covers all three classes | Group A/B/C partitioning; GPR εr + micro-Doppler + seismic for passive victims |
| Precise localization | Cell-level (5 m) today | Grid MAP gives sector ranking; sub-cell refinement is Phase 6 work (see §6) |
| Delivery to humans | Implemented end-to-end | 16-byte LoRa frames + JSON HUD + directives with true MGRS |
| Never mislead | Enforced by construction | Deterministic log-odds, saturation caps, JSONL audit trail; no ML in triage path |

The honest gap: **every sensor byte is currently simulated.** The value shipped today is a verified decision core plus wire formats — the part that is hardest to get right and hardest to test in the field.

---

## 2. Physics reality check (what the literature says will kill this system)

Three field failure modes dominate published attempts:

1. **EMI from electric motors.** Brushless motor noise limits drone-mounted 457 kHz receiver sensitivity to roughly **6 m radius**, vs 30–50 m handheld (Janovec 2022; Ricciardi 2017). Shielded or turbine platforms recover most of it; suspending the receiver 2 m below the airframe helps more.
   - *Our answer already modeled:* `emi_noise_floor_dbm` enters `q_emi` per payload, so an EMI-degraded pass contributes less evidence instead of false confidence.
   - *Deployment rule:* mount the 457 kHz front-end on a mast/tow below the airframe; calibrate `environmental_attenuation.emi_noise_penalty_factor` per airframe before missions.
2. **Snow wetness kills radar penetration.** Free water in the snowpack absorbs UWB GPR energy exponentially; wet spring snow can cut usable depth to <1 m. Our `q_gpr = exp(-κ·ρ·d)` models exactly this; κ needs field calibration against DGRE snow-pit data.
3. **GNSS denial in valleys.** Deep gullies multipath GPS. The command node must tolerate degraded absolute position: RTK base station on the command vehicle + visual-inertial odometry on the UAV are the Phase 7 answers.

Survival math anchor (why speed matters): extraction within 15 min ≈ 90% survival; past 35 min < 30%. A UAV sweep that saves even 20 minutes of search time moves dozens of percentage points of survival probability per mission.

---

## 3. Reference hardware bill of materials

Indicative, INR, prototype quantities. India-available options preferred.

| Modality | Candidate device | Mount | ~Cost (₹) |
| :--- | :--- | :--- | ---: |
| 457 kHz transceiver RX | Barryvox/Mammut Pulse with UART tap (proven PoC) or custom ferrite-coil SDR front-end | 2 m tow/mast below airframe | 35k / 15k |
| UWB GPR | Radar Systems Zond Aero LF (airborne 100–750 MHz) or LRDE partnership pod | Belly gimbal, EMI-shielded | 25–40 L |
| Micro-Doppler respiration | TI IWR6843 60 GHz FMCW EVM (0.1–1 Hz chest wall proven in lab) | Nadir hard-mount | 60k |
| LWIR thermal | FLIR Boson 640 (8–14 µm) | Gimbal | 4–6 L |
| RGB visual | Standard 4K gimbal camera | Gimbal | included |
| RECCO | Licensed detector technology — partnership required, else drop modality | Belly | TBD |
| Seismic/acoustic | Geophone SM-24 array + MEMS mics | Suspended contact probe on landing | 40k |
| Cellular IMSI | Legal restriction: LEA-only in India — keep as optional government-partner module, off by default | Airframe | n/a |
| Edge compute | NVIDIA Jetson Orin NX 16 GB (command node) + Orin Nano per UAV | Airframe/command | 90k each |
| Swarm link | RFD900x / Herelink 900 MHz HDR telemetry | Both ends | 25k |
| SAR downlink | Semtech SX1262 LoRa, 865–867 MHz (India SRD band) | Command → responders | 3k |
| BLOS backup | RockBLOCK 9603 Iridium SBD (aligns with DGRE NATSAT/IAWNS-S intent) | Command node | 80k |
| Positioning | u-blox F9P RTK (base + rovers) | All nodes | 70k/set |

Total sensor+compute prototype cost excluding airframes: roughly ₹35–55 lakh. Airframe options: ideaForge Switch/Q6 or Garuda Aerospace quad (indigenous, DGCA-type-listed) carrying 2–4 kg payload.

---

## 4. Connectivity architecture (three tiers, graceful degradation)

```
Tier 1  UAV <-> UAV / UAV <-> command     MAVLink over 900 MHz HDR (RFD/Herelink)
        Payload: full-rate sensor metadata, UAV kinematics      ~50-200 kbps, LOS ~20 km
Tier 2  Command -> responder teams        LoRa SX1262 mesh, 865-867 MHz
        Payload: our 16-byte target vectors                     ~1 kbps, NLOS 5-15 km
Tier 3  Command -> higher HQ (optional)   Iridium SBD / DGRE SATCOM (IAWNS-S aligned)
        Payload: compressed situation report                    340 bytes/msg, global
```

Bandwidth sanity check: a P1 directive frame is 16 bytes; even 100 targets/min is trivially inside LoRa duty-cycle limits. The JSON WebSocket HUD runs only on Tier 1 Wi-Fi/LAN inside the command post — it never crosses Tier 2/3, which carry only binary vectors. If Tier 1 dies, UAVs buffer and burst on re-link; if all tiers die, the last issued directives still live in responders' LoRa handsets.

---

## 5. Integration into Indian institutional infrastructure

- **DGRE (DRDO)** — primary customer and data partner: winter avalanche advisories, AWS station network, snow-meteorological data to calibrate priors and attenuation constants; alignment with their stated programs IAWNS-S (warning + navigation via SATCOM) and infrasound/seismic detection research.
- **Army / ITBP (Siachen, AGPL, Ladakh sectors)** — forward-post deployment model: command node at battalion HQ, UAV section organic to the post; directive handoff to unit rescue teams over existing radios.
- **NDRF / SDRF** — civilian mass-casualty role after highway/rail avalanches (e.g., NH-44 Sonamarg–Leh corridor); NDRF's CSSR doctrine maps directly onto our PROBE_EXCAVATE directives.
- **BRO** — road-opening operations benefit from the same engine run as "clearance confirmation" over known slide zones.
- **Regulatory checklist:** DGCA Drone Rules 2021 (BVLOS via conditional exemption for government UAS; digital sky zones); WPC license-exempt SRD band 865–867 MHz for our LoRa and marker (marker default set to 866.0 MHz accordingly); IMSI-catcher functionality restricted to authorized agencies — module ships disabled.

---

## 6. Expansion roadmap (value ÷ effort ranked)

**Phase 6 — hardware truth (the gate to everything):**
1. Single-modality bench rig first: 457 kHz receiver + UART → adapter → fusion on a sled. Prove the adapter contract with real bytes before flying anything.
2. Two-stage localization upgrade, literature-standard: grid MAP finds the sector; then an EKF refines a point estimate from successive bearing/distance samples (magnetic-dipole 1/r³ signal model). Output: cm-class aim point instead of a 5 m cell centroid.
3. GeoTIFF DEM ingestion replacing the synthetic gully; slope priors computed from real terrain.
4. Field calibration harness: scripts to fit `sensor_priors` and attenuation constants from ground-truth probing sessions (extends existing `calibrate_parameters.py`).

**Phase 7 — operational integration:**
5. Infrasound/seismic release-detection feed (DGRE research area) as an automatic mission trigger: detect the avalanche, task the sweep.
6. Multi-victim deconfliction: data association across overlapping beacon pulses and multiple grid locks (schema already carries `is_multi_victim_signal`).
7. Swarm area-partition tasking and GPS-denied visual-inertial odometry.
8. Ground-robot handoff for probe confirmation under secondary-slide risk (aerial-ground collaboration pattern validated by EU CROSS project).

**Explicit non-goal:** ML classifiers in the triage path. They may assist upstream clutter labeling later, but directive issuance stays closed-form and auditable — that guarantee is a selling point, not a limitation.

---

## 7. Risk register

| Risk | Likelihood | Mitigation |
| :--- | :--- | --- |
| Motor EMI blinds 457 kHz search | High on electric airframes | Mast/tow mounting; per-airframe EMI calibration; turbine option documented |
| Wet-snow GPR blindness | Seasonal, high in spring | q_gpr attenuation model; thermal/optical groups carry shallow victims |
| BVLOS clearance delays | Medium | Fly within VLOS corridors first; DGCA exemption path for gov demos |
| False-positive erosion of operator trust | Medium | Asymmetric thresholds (τ_P1 high); audit log lets reviewers reconstruct every lock |
| Cold-soak battery collapse at −30 °C | Certain without mitigation | Self-heating Li-ion packs; Orin conformal coating; warm-soak procedures |
| Single-node software fault mid-mission | Low but nonzero | Watchdog healthz + systemd restart; directives persist to disk; stateless UAVs |

---

## 8. The one-sentence thesis

Every minute of search time removed is worth several percentage points of survival probability; this engine removes the two slowest parts of the pipeline — human sweeping and human prioritization — while keeping every decision reproducible enough to defend in a court-martial.
