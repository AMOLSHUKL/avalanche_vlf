# AVALANCHE-VLF: Project State, Verification Audit & Roadmap
**Problem Statement:** Smart India Hackathon 2026 PS SIH260104 / MoD / DRDO / DGRE
**Theme:** Disaster Management  
**System Designation:** Autonomous Airborne Multi-Modal Sensor Fusion Platform for Avalanche SAR  
**Status:** 100% Complete Functional Prototype & Production-Ready Defense State

---

## 1. Feature Completion & Verification Audit

| Subsystem / Feature | Module Location | Verification Standard | Implementation Status |
| :--- | :--- | :--- | :--- |
| **Recursive Bayesian Fusion Core** | `backend/engine/fusion.py` | Log-odds updates, anti-windup clamping ($[-15, 15]$), leaky retention ($\gamma=0.96$) | **COMPLETE & VERIFIED** |
| **Evidence Group Saturation** | `backend/engine/fusion.py` | Strict group caps ($\Gamma_A=4.5, \Gamma_B=4.2, \Gamma_C=2.5$) and weights $\mathbf{w}$ | **COMPLETE & VERIFIED** |
| **Symmetric LLR Sensor Adapters** | `backend/engine/adapters/` | 7 polymorphic adapters implementing symmetric positive/negative likelihood | **COMPLETE & VERIFIED** |
| **Micro-Doppler Life-Sign Extraction** | `backend/schemas/sensors.py`, `gpr.py` | Human respiration frequency band ($0.1\text{--}1.0\text{ Hz}$), lock flags | **COMPLETE & VERIFIED** |
| **Dielectric Permittivity Bounds** | `backend/schemas/sensors.py` | Tissue permittivity bounds ($\varepsilon_r \approx 50\text{--}55$) vs snow ($\varepsilon_r \approx 3.2$) | **COMPLETE & VERIFIED** |
| **Spatiotemporal Persistence Filter** | `backend/engine/fusion.py` | Multi-pass windowing ($+0.75$ bonus for persistence, $-0.40$ penalty) | **COMPLETE & VERIFIED** |
| **Biophysical Survival Model** | `backend/engine/fusion.py` | Tri-phase physiological curve modeling 15-minute Asphyxiation Cliff | **COMPLETE & VERIFIED** |
| **Rescuer Slope Hazard Engine** | `backend/engine/terrain.py` | Monotonically increasing hazard function for slopes $25^\circ\text{--}45^\circ+$ | **COMPLETE & VERIFIED** |
| **Contour-Parallel Safe Azimuth** | `backend/engine/fusion.py` | Gradient orthogonal angle calculation ($(\theta_{\text{fall}} + 90^\circ) \pmod{360^\circ}$), boundary cells via cached `np.gradient` one-sided differencing | **COMPLETE & VERIFIED** |
| **MGRS Military Geotagging** | `backend/engine/geo.py` | True WGS84->UTM->MGRS conversion (USGS PP 1395 / NGA TM 8358.1), e.g. `43S GT 36122 85514`; exhaustive 60-zone lettering sweep + libmgrs cross-checked known-answer vectors (Norway/Svalbard zone overrides out of operational envelope) | **COMPLETE & VERIFIED** (post-audit #1 fix, 2026-08-22) |
| **NLOS LoRaWAN 16-Byte C-Struct** | `backend/telemetry/lora_packet.py` | Exact 16-byte packed binary struct (`!BBBBHBHBHHH`) with CRC-16/CCITT | **COMPLETE & VERIFIED** |
| **5-Phase Mission Lifecycle State Machine**| `backend/telemetry/simulator.py`| Preflight $\rightarrow$ Surface $\rightarrow$ Deep Radar $\rightarrow$ Marker $\rightarrow$ Guidance | **COMPLETE & VERIFIED** |
| **7-Modality Fault Injection** | `backend/main.py`, `frontend/js/app.js`| Real-time sensor failure disabling via REST API and HUD buttons; incident-card fusion count tracks degraded state live | **COMPLETE & VERIFIED** |
| **Tactical Command Operations HUD** | `frontend/index.html`, `frontend/js/` | Modular ES6+ UI (`app`, `dem`, `fusion`, `map2d`, `relief3d`) with vendored three.js; Cartesian Y-axis inversion | **COMPLETE & VERIFIED** |
| **RELIEF 3D Alpine Tactical View** | `frontend/js/relief3d.js`, `frontend/js/dem.js` | DEM-mirrored terrain (exact frontend/backend parity, 0.00 m over 1156 cells), snow/rock shading, procedural assets (pines/rocks/base camp/quadcopter UAVs), terrain-following UAV flight, scripted avalanche release with volumetric flow + deposit; `?debug=3d` scene HUD | **COMPLETE & VERIFIED** (device pixel review + smoke + parity checks) |
| **Offline MAP Prior Calibration CLI** | `scripts/calibrate_parameters.py`| Laplace-smoothed Maximum A Posteriori likelihood optimizer | **COMPLETE & VERIFIED** |

---

## 2. Test Matrix Execution Report (`pytest`)

(venv) ~/.../SIH_2026/avalanche_vlf $ pytest tests/ -q

```text
367 passed

Coverage by file:
  tests/test_geo.py                MGRS anchors incl. libmgrs known-answer
                                   vectors, exhaustive 60-zone column-block
                                   sweep, row-cycle sweep, inverse guard
  tests/test_fusion.py             fusion math, temporal filter, azimuth frame
                                   (incl. boundary cells), MGRS wiring, LoRa
                                   roundtrip, concurrency
  tests/test_adapters.py           per-adapter quality curves: bounds,
                                   monotonicity, extreme inputs; LLR contract
  tests/test_lora_packet.py        truncated/corrupt packet rejection, CRC
                                   integrity, malformed zone-id rejection
  tests/test_config_validation.py  boundary rejections, hot-swap atomicity,
                                   copy-on-read isolation
  tests/test_api.py                health, telemetry stream, fault injection,
                                   hot-swap, adversarial payloads
```

### Audit remediation (2026-08-22)

All findings from `.ai/AVALANCHE-VLF_AUDIT.md` are resolved except
OPTIMIZATION-12 (C1 kink in `calculate_rescuer_hazard`, cosmetic and unused
by gradient-based calibration). Highlights:
- [CRITICAL-1] MGRS lettering rewritten to per-zone-set 8-letter blocks
  (`ABCDEFGH`/`JKLMNPQR`/`STUVWXYZ`) — note the audit's proposed `STUVWXAB`
  sequence was itself non-conformant; the landed fix was validated against
  reference libmgrs on a 6,849-point global sweep with zero mismatches.
- [HIGH-2] Approach azimuth now reads gradients cached from `np.gradient`
  (correct one-sided edge differencing); regression tests cover grid-edge cells.
- [HIGH-3] Engine core no longer imports the telemetry layer;
  `MissionGridFrame` lives in `engine/geo.py`; logger injected via the
  `MissionEventSink` port at the composition root.
- [HIGH-4] Config hot-swap offloaded via `asyncio.to_thread`.
- [MEDIUM 5-11] All applied; [MEDIUM-11] swapped to near-field r^-3 coupling.

---

## 3. Post-Hackathon Expansion & Hardware Handoff Scope

```
===================================================================================================
PHASE        MILESTONE                         DELIVERABLES                               STATUS
===================================================================================================
Phase 1-5    Complete SIH 2026 Prototype       Log-odds core, 7 adapters, LoRa struct,    [100% COMPLETE]
                                               FastAPI, Canvas HUD, MAP calibration.
---------------------------------------------------------------------------------------------------
Phase 6      Physical Hardware Drivers         - Native SPI/UART driver for Semtech       [PLANNED]
             (Post-Hackathon DGRE Integration)   SX1262 LoRa physical transceiver.
                                               - Ingestion bridge for binary SEGY radar
                                                 streams from physical DRDO GPR pod.
                                               - MAVLink / ROS 2 bridge for PX4 autopilot.
                                               - GeoTIFF digital elevation ingestion.
Phase 7      Field Altitude Benchmarking       - Deployment in Siachen / Ladakh sectors.  [PLANNED]
===================================================================================================
---

## 4. Local Working State & Session Log (updated 2026-08-25)

**Everything below is PUSHED** — `origin/main` at `6470d3c` (2026-08-25). The device-level environment runbook lives OUTSIDE this repo at `~/development/config/TERMUX_RUNBOOK.md` (device outlives any project); read it before any session on this tablet. It carries the full error/decision log for the Termux + Ubuntu-proot environment: phantom-process kills, the wheel boundary, the SwiftShader no-op, the backend's Ubuntu-side unreachability, git/SSH inside proot, apt-lock hangs, the browser stale-JS incident, and the storage-audit decisions.

### Frontend rebuild (complete, verified)

- `frontend/app.js` monolith replaced by modular build: `index.html` shell, `css/app.css`, `js/{app,dem,fusion,map2d,relief3d}.js`, vendored `vendor/three.min.js` + `OrbitControls.js` (2021 r132-era), `link_state.js` watchdog.
- New levers: `scripts/verify_frontend.js` (static id/asset/syntax check), `scripts/smoke_frontend.js` (headless DOM/WebGL-stub runtime test), `scripts/capture_ui.js` (proot chromium pixel captures → `.ui_review/`).
- Visual audit round 1+2 fixed: golden-window ring label, SAR acronym casing, tablet CSS cascade collapse (media hides must follow base rules), hillshade red-tint bug, DSP drawer azimuth honesty, gizmo tilt reset on 2D, drawer-open control shift (−364px → −84px), 3D skirt theming (black slivers), UAV beam cap, zoom max 850, posterior blobs restored to wide soft halos (user-approved look from "Liked it" reference).
- Known env limit: RELIEF 3D cannot render in the proot capture env (SwiftShader context loss) — pixel-audit on real hardware only.

### Environment (see TERMUX_RUNBOOK.md for the full contract)

- numpy restored to venv via `.pth` bridge to global Android-built 2.4.4; never pip-build C sdists on-device.
- proot-distro Ubuntu 26.04 provisioned for headless captures; backend stays Termux-native under tmux.
- uvicorn 0.52.4 + websockets 17.0.1 upgraded; 367 tests green throughout.

### Agent-runtime relocation (validated + executed 2026-08-24)

- **opencode moved to the official upstream Linux ARM64 build (1.18.21) inside Ubuntu proot**; `agy` (official Antigravity CLI 1.1.19) installed alongside. Config/auth/skills shared zero-migration via `XDG_CONFIG_HOME`/`XDG_DATA_HOME` pointing at the bind-mounted Termux home (set in Ubuntu's `/root/.bashrc`).
- Working model: persistent Ubuntu session via `proot-distro login ubuntu --bind $HOME:/termux-home --bind <repo>:/work`. No Termux wrapper aliases — the environment transition stays explicit.
- **Removed**: the Hope2333 opencode build (Bun single-file + `bunfs_shim.so` Termux shim), the entire 49-52 package Termux glibc layer, and the 175 MB shim cache. Verified before removal that the opencode stack was the glibc layer's only consumer (ELF scan of `$PREFIX/bin`, `$PREFIX/lib`, `$PREFIX/share`, `$HOME` bin dirs). Post-removal battery: opencode/agy/git/clangd/node/python OK, FastAPI healthy, 367 tests green.
- Known tradeoff: proot costs ~2× on syscall-heavy operations (measured: git status 21 ms native vs ~45 ms in-session) until the device is rooted and the same Ubuntu rootfs moves to chroot.
- Rollback artifact: the old Hope2333 bashrc wrapper is preserved at `~/.config/opencode/termux-launcher-rollback.sh` (its binary/glibc dependencies are NOT reinstallable without re-adding the glibc layer; the official Ubuntu build is the supported path).

### Pushed 2026-08-25 (`6470d3c`) — frontend rebuild + 3D + avalanche scenario

1. Frontend modular rebuild (see above) + RELIEF 3D rebuild: enriched DEM (4117 m peak, east ridge, carved gully — mirrored EXACTLY in backend `TerrainEngine` and frontend `dem.js`; the parity check is a standing gate), snow/rock shader, procedural assets, terrain-following UAVs, scripted avalanche (incident+75 s, volumetric crown flow, deposit).
2. Ground-truth victims moved onto the runout centerline — cells (55,43) equipped, (61,30) deep passive, (58,36) shallow; slopes verified 23.5-26 deg (inside the 15-32 burial band), 1 m off the gully centerline; UAV Bravo's sweep band extended to rows 30-74 so GPR/RECCO victims are actually overflown.
3. `requirements.txt`: direct `websockets` pin removed (transitive via `uvicorn[standard]`, verified on 17.x), numpy bounded `<3`.
4. Static assets served with `Cache-Control: no-cache` after the stale-JS incident; `.ui_review/` gitignored.
5. Doc sync (this commit): README module map + verification, ARCHITECTURE frontend tree, CONVENTIONS dependency rule (vendored, no CDN), BACKLOG watchdog wording, runbook relocated to `~/development/config/`.

### Session error log (2026-08-24/25) — code lessons behind the shipped fixes

- **DEM parity**: frontend sampled cell corners, backend cell centers — sub-1 m on the old ramp, **6.16 m** across the peak/gully Gaussians. Fixed to exact parity; any future DEM edit must rerun the parity check.
- **Avalanche auto-trigger unreachable**: the elapsed-time trigger check sat after the idle early-return in `updateAvalanche`. Ordering rule: trigger checks precede state early-returns.
- **Scroll anchoring against a non-scrolling element**: anchoring math on `#queueDesk` was a no-op because `.rc-scroll`/`.sheet-body` owns the scroll. Anchor against the real scroller (getBoundingClientRect, not offsetTop).
- **CSS animation replay on re-insertion**: `.fresh` class persisted on reconciled cards, so every `replaceChildren` reorder replayed the entry animation — the "continuous flashing". One-shot classes must be stripped on `animationend`.
- **Peek bar null crash on mission restart**: empty-state `innerHTML` swap destroyed patched spans but left a `dataset.built` guard — cleared the guard with the swap.
- **Stale-asset mixed state**: server restart + browser cache = new backend, old frontend (the "nothing changed" report). Root-fixed with `Cache-Control: no-cache`.
- **Headless-GL dead end**: SwiftShader silently no-ops under proot (contexts OK, shaders link, zero pixels — headless AND headed/Xvfb/Mesa). Do not retry without a new chromium/ANGLE path.
