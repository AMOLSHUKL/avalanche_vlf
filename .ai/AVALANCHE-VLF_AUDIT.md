# AVALANCHE-VLF — Architectural & Algorithmic Audit
**Scope:** `backend/` (engine, adapters, schemas, telemetry, config, main), `tests/`, cross-checked against `.ai/PROJECT_STATE.md` and `.ai/BACKLOG.md`.
**Method:** Full extraction of all 48 files from `codebase.xml` (Repomix dump) to disk; line-by-line static review; empirical verification of every geodesy/numeric claim by executing the actual extracted modules (not hand-derivation) against regression anchors and exhaustive sweeps. Diffs below are proposed, not applied.

> **Amendment (2026-08-23):** the fix originally proposed for [CRITICAL-1] was itself wrong (it preserved a truncated column-letter alphabet instead of correcting it). Verified against GeographicLib and movable-type.co.uk reference implementations and corrected in place below — see that section for the specific error and the corrected diff. All other findings are unaffected.
>
> **Independently verified against the actual shipped fix (2026-08-23):** ran the real `pytest` suite and a from-scratch exhaustive sweep directly against the updated repository (not the change summary) — `361 passed`, `0/9,600` zone×column×row failures, column blocks match the reference sequence exactly, and the FastAPI app boots and serves end-to-end through the full grid-initialization path. All CRITICAL/HIGH items and every MEDIUM item spot-checked (5,7–11) are present in the code exactly as specced. One imprecision in the coder's own change summary, not the code: Norway/Svalbard zone overrides are documented as an explicit, unimplemented limitation ("not implemented... resolve via their regular UTM zone instead"), not "handled" — `PROJECT_STATE.md`'s own status row states this correctly ("out of operational envelope"); the chat summary's wording just blurred it.

**Correction to a stated premise:** the brief asks about "matrix singularity during covariance updates" and "multi-sensor fusion matrices." There is no matrix algebra anywhere in this codebase — `requirements.txt`/`pyproject.toml` carry no `scipy`/`sklearn`/`filterpy`, and fusion is pure scalar log-odds arithmetic (confirmed by grep across `backend/`). The real numerical risk surface is scalar (log/exp domain errors, division-by-zero, degenerate config), which is what's audited below. This is not a gap — it's a legitimate architectural choice that changes what "numerical stability" means for this system.

---

## Executive Summary

| # | Severity | File | Defect |
|---|---|---|---|
| 1 | **CRITICAL** | `backend/engine/geo.py` | MGRS 100km-square letter alphabets are mis-sized vs. their indexing modulus → reproducible `IndexError` for ~1/3 of UTM zones, silently wrong grid letters for the rest |
| 2 | **HIGH** | `backend/engine/fusion.py` | Boundary-cell finite-difference in `_calculate_safe_approach_azimuth` corrupts the rescuer approach bearing, not just its magnitude |
| 3 | **HIGH** | `backend/engine/logger.py`, `fusion.py` | Engine performs direct filesystem I/O and imports the telemetry adapter layer — both violate the mandated hex-architecture boundary |
| 4 | **HIGH** | `backend/main.py` | Config hot-swap runs synchronous, `fsync`-ing disk I/O directly on the event loop that also drives the 10Hz broadcast |
| 5 | MEDIUM | `backend/config/loader.py` | `origin_lat` validation range doesn't exclude the `cos(lat)=0` singularity it feeds |
| 6 | MEDIUM | `backend/engine/geo.py` | `utm_to_geodetic` has no output-latitude sanity check (forward direction validates on the way in; inverse doesn't validate on the way out) |
| 7 | MEDIUM | `backend/telemetry/simulator.py` | Grid dimensions hardcoded, not sourced from `ConfigLoader` — silent partial-coverage risk on grid resize |
| 8 | MEDIUM | `backend/telemetry/lora_packet.py` | `from_directive` silently defaults to cell `(0,0)` on a malformed zone ID instead of failing loudly (inconsistent with the codebase's own stated philosophy) |
| 9 | MEDIUM | `backend/main.py` | WebSocket handler's generic `except Exception` swallows errors with no logging |
| 10 | MEDIUM | `backend/config/loader.py` | `.config` property returns the live dict by reference despite a "read-only" docstring (already tracked in `.ai/BACKLOG.md`) |
| 11 | MEDIUM | `backend/engine/adapters/rf.py` | Detection-quality curve uses an inverse-square-style heuristic, not the near-field dipole (~r⁻³) physics the problem statement invokes |
| 12 | OPTIMIZATION | `backend/engine/terrain.py` | `calculate_rescuer_hazard` is C0 but not C1 at the 45° seam — cosmetic only |
| 13 | OPTIMIZATION | `backend/engine/fusion.py` | Cross-group conditional-independence assumption is implicit/uncalibrated |
| 14 | OPTIMIZATION | `.ai/PROJECT_STATE.md` | MGRS subsystem marked "COMPLETE & VERIFIED" — contradicted by #1; status table needs correction |

---

## [CRITICAL-1] MGRS 100km-square letters: reproducible `IndexError` + silent wrong output

**File:** `backend/engine/geo.py`, function `_mgrs_100km_square_letters` (lines 222–236), constants at lines 50–51, 55.

### The defect

Two independent alphabet/modulus mismatches:

```python
_MGRS_COLUMN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWX"   # comment says 24 letters — actually 22
_MGRS_ROW_ALPHABET = "ABCDEFGHJKLMNPQRSTV"         # comment says 20 letters — actually 19 ('U' is missing)
_MGRS_SET_START_INDEX = {0: 0, 1: 8, 2: 18}        # comment says zone-set 2 starts at 'S' (index 16) — dict says 18
```

`len(_MGRS_COLUMN_ALPHABET) == 22`, indexed with `% 24`. `len(_MGRS_ROW_ALPHABET) == 19`, indexed with `% 20`. Both moduli are one alphabet-generation stale relative to the strings they index.

**Empirically verified** (executed the actual extracted module, not hand-derived):

```
zone=45 (zone_set=2), sweeping col_index 1..8 at fixed northing:
  col_index=1 -> ('U','T')   # should be 'S' — wrong, not crashed
  col_index=2 -> ('V','T')   # should be 'T' — wrong
  col_index=5 -> RAISED IndexError: string index out of range
  col_index=6 -> RAISED IndexError: string index out of range
  col_index=7 -> ('A','T')   # should be 'A' — coincidentally right
  col_index=8 -> ('B','T')   # should be 'B' — coincidentally right

Row-letter sweep, zone=43 (zone_set=0, otherwise "safe"), northing 0..9,400,000 m:
  4 independent IndexError crashes, every 2,000,000 m of northing
  (northing blocks 19, 39, 59, 79 — i.e. wherever row_index+offset ≡ 19 mod 20)
```

So this bug has two manifestations, not one: an outright crash for `col_index ∈ {5,6}` in any zone_set-2 zone (zones 3,6,9,…,60 — 20 of 60 UTM zones), *and* a silently wrong 100km-square letter for every other `col_index` in that same zone set even when it doesn't crash. The row-letter bug is independent of zone/zone_set entirely and recurs every 2,000 km of northing in *any* zone.

**Reachability:** both `FusionEngine._initialize_grid` (once per grid cell, at construction) and `FusionEngine.__init__`'s `mission_grid_frame_from_latlon` call hit this function at **application startup**, before `uvicorn` finishes bringing up the ASGI app — a trigger here is not a degraded request, it's a failed boot.

**Does today's demo config trigger it?** No — verified by sweeping all 10,000 cells of the actual configured 500m×500m grid at `origin_lat=34.1839, origin_lon=77.5621`: **0 crashes**. This origin sits in UTM zone 43 (zone_set=0, the one working start-index), and the grid's northing range never leaves `row_index=17`. This is coincidence, not correctness — it depends on both the specific zone and a specific 100km northing band never being crossed. Any future origin change (a different Himalayan sector, a judge asking "what if this were Uttarakhand"), or simply widening the grid past a 100km northing boundary, can hit it.

**Test-coverage root cause:** `tests/test_geo.py` has 8 tests. The one designed for global sweep (`test_round_trip_closure_global_grid`) exercises `geodetic_to_utm`/`utm_to_geodetic` only — it never calls `geodetic_to_mgrs`, so it never touches the buggy function at all. Every other test that *does* call `geodetic_to_mgrs` uses the one demo origin, which structurally cannot reach zone_set 1/2 or the row-letter boundary. `.ai/BACKLOG.md` already senses this ("parametrized known-answer vectors… beyond null-island + round-trip closure") but has it filed as a hygiene nice-to-have, not a demonstrated defect.

### Fix — CORRECTED 2026-08-23 (see amendment note below; do not use the version originally published here)

**The fix as first published in this report was itself wrong**, and should not be applied. It kept the codebase's existing (truncated, 22-character) `_MGRS_COLUMN_ALPHABET` string and matched the modulus to it, which produces the wrapped sequence `S,T,U,V,W,X,A,B` for zone_set 2. Checked post-hoc against two independent reference implementations — GeographicLib (Karney's `MGRS.cpp`, `utmcols[3] = {"ABCDEFGH","JKLMNPQR","STUVWXYZ"}`) and the movable-type.co.uk geodesy library (`e100kLetters = ['ABCDEFGH','JKLMNPQR','STUVWXYZ']`) — the correct sequence is `S,T,U,V,W,X,Y,Z`: a clean, non-overlapping 24-letter alphabet split into three 8-letter blocks, no wraparound. The 22-character string in the codebase wasn't just indexed with the wrong modulus — it was two letters short of the real alphabet (missing Y, Z). Matching the modulus to a truncated string was the wrong repair target.

Both reference implementations also confirm the row alphabet fix below (`ABCDEFGHJKLMNPQRSTUV`, 20 letters) was correct as originally published — only the column alphabet had a residual error.

Corrected fix, matching the reference libraries' own approach of three discrete blocks rather than one cycling string + offset (this shape is also harder to get wrong the same way again, since there's no modulus to drift out of sync with the alphabet):

```diff
--- a/backend/engine/geo.py
+++ b/backend/engine/geo.py
@@
-_MGRS_ROW_ALPHABET = "ABCDEFGHJKLMNPQRSTV"         # 20 letters, cycles every 2000 km
+_MGRS_ROW_ALPHABET = "ABCDEFGHJKLMNPQRSTUV"        # 20 letters, cycles every 2000 km
@@
-_MGRS_COLUMN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWX"   # 24 letters, cycles every 3 zones
-_MGRS_SET_START_INDEX = {0: 0, 1: 8, 2: 18}
+_MGRS_COLUMN_BLOCKS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")   # one 8-letter block per zone_set, no wraparound
@@
-    col_letter = _MGRS_COLUMN_ALPHABET[(start + col_index - 1) % 24]
+    col_letter = _MGRS_COLUMN_BLOCKS[zone_set][col_index - 1]
@@
-    row_letter = _MGRS_ROW_ALPHABET[(row_index + row_offset) % 20]
+    row_letter = _MGRS_ROW_ALPHABET[(row_index + row_offset) % len(_MGRS_ROW_ALPHABET)]
```
(`zone_set = (zone - 1) % 3` already exists earlier in the function; `_MGRS_SET_START_INDEX` is no longer needed and can be deleted.)

### Required regression test (add to `tests/test_geo.py`)

```python
@pytest.mark.parametrize("zone", range(1, 61))
def test_mgrs_square_letters_exhaustive_no_crash_and_known_sequence(zone):
    from backend.engine.geo import _mgrs_100km_square_letters
    letters_by_col = [
        _mgrs_100km_square_letters(zone, col * 100000.0 + 50000.0, 3_000_050.0)[0]
        for col in range(1, 9)
    ]
    zone_set = (zone - 1) % 3
    expected_start = {0: "ABCDEFGH", 1: "JKLMNPQR", 2: "STUVWXYZ"}[zone_set]
    assert letters_by_col == list(expected_start)

@pytest.mark.parametrize("row_block", range(0, 94))
def test_mgrs_row_letters_exhaustive_no_crash(row_block):
    from backend.engine.geo import _mgrs_100km_square_letters
    _mgrs_100km_square_letters(zone=43, easting_m=450000.0, northing_m=row_block * 100000.0 + 50000.0)
```

---

## [HIGH-2] Safe-approach-azimuth boundary gradient corrupts bearing, not just magnitude

**File:** `backend/engine/fusion.py`, `_calculate_safe_approach_azimuth`, lines 348–360.

### The defect

```python
cy_min = max(0, cell_y - 1)
cy_max = min(self.rows - 1, cell_y + 1)
...
dz_dy = (elev[cy_max, x] - elev[cy_min, x]) / (2.0 * self.terrain.cell_size_m)
dz_dx = (elev[y, cx_max] - elev[y, cx_min]) / (2.0 * self.terrain.cell_size_m)
```

At an interior cell, `cy_max - cy_min == 2` — the `2.0 * cell_size_m` divisor is correct for a centered difference. At a boundary cell (`cy == 0` or `cy == rows-1`), `cy_max - cy_min == 1`, but the code still divides by `2.0 * cell_size_m` — a one-sided, single-cell-span difference gets divided as if it spanned two cells.

**This is not a benign magnitude error.** `atan2(dz_dx, dz_dy)` is scale-invariant *only* if both components are scaled by the same factor. At a cell that's a boundary in `y` but interior in `x` (the entire first/last row, excluding corners), `dz_dy` is halved while `dz_dx` is not — the ratio between them changes, which changes the angle `atan2` returns, not just its magnitude. Every cell on the outer ring of the grid gets a **wrong compass bearing**, and `approach_azimuth_deg` is exactly the value handed to a rescuer as "avoid the fall line, approach from here" — this is safety-relevant output, not cosmetic.

`terrain.py`'s own slope computation uses `np.gradient(elevation, cell_size_m, cell_size_m)` for the identical operation and gets the boundary case right for free (`np.gradient` applies proper one-sided differencing at edges). Fusion re-derives the same gradient by hand and gets it wrong — an internal inconsistency between two implementations of the same math in the same codebase.

**Test-coverage root cause — three independent reasons this test cannot catch this bug, all present simultaneously:**

`tests/test_fusion.py::test_safe_approach_azimuth_is_contour_perpendicular` (lines 186–213):
1. Parametrizes `[(10,10),(25,25),(45,35),(70,60),(90,90)]` — on a 100×100 grid, **none of these are boundary cells** (boundary = index 0 or 99).
2. Its own "expected gradient" computation (lines 195–204) is a byte-for-byte copy of the buggy `max(0,cy-1)/min(rows-1,cy+1)/÷2.0*cell_size` logic — it doesn't independently verify the source, it mirrors it, so the two can only ever agree.
3. Even setting aside (1) and (2): the assertion checks *perpendicularity* (`dot ≈ 0`) between the azimuth and the gradient. A 90°-rotated vector is perpendicular to its source vector under *any* uniform mis-scaling — perpendicularity is structurally blind to exactly this class of bug. Catching it requires comparing the *actual angle value* against an independently-correct gradient, not checking orthogonality against the same (possibly wrong) one.

### Fix

Preferred: cache the already-correct `np.gradient` output on `TerrainEngine` once (it's static after DEM generation) and have fusion read it, eliminating the duplicate hand-rolled implementation entirely rather than patching it in two places:

```diff
--- a/backend/engine/terrain.py
+++ b/backend/engine/terrain.py
@@ def _generate_dem(self):
         elevation = 3800.0 + (yy * 0.42) + 25.0 * np.sin(xx / 70.0)
         dy, dx = np.gradient(elevation, self.cell_size_m, self.cell_size_m)
         slope_rad = np.arctan(np.hypot(dx, dy))
         slope_deg = np.degrees(slope_rad)
+        self.grad_dx, self.grad_dy = dx, dy  # cached for reuse — single source of gradient truth
         return elevation, slope_deg
```

```diff
--- a/backend/engine/fusion.py
+++ b/backend/engine/fusion.py
@@ def _calculate_safe_approach_azimuth(self, cell_x, cell_y):
-        cy_min = max(0, cell_y - 1)
-        cy_max = min(self.rows - 1, cell_y + 1)
-        cx_min = max(0, cell_x - 1)
-        cx_max = min(self.cols - 1, cell_x + 1)
-
-        dz_dy = (float(self.terrain.elevation_grid[cy_max, cell_x]) - float(self.terrain.elevation_grid[cy_min, cell_x])) / (2.0 * self.terrain.cell_size_m)
-        dz_dx = (float(self.terrain.elevation_grid[cell_y, cx_max]) - float(self.terrain.elevation_grid[cell_y, cx_min])) / (2.0 * self.terrain.cell_size_m)
+        dz_dx = float(self.terrain.grad_dx[cell_y, cell_x])
+        dz_dy = float(self.terrain.grad_dy[cell_y, cell_x])
```

If touching `terrain.py` is undesirable this close to demo, the minimal single-file fix is to use the *actual* span instead of a hardcoded 2, guarding the degenerate 1-row/1-col case:

```python
dy_span = max(1, cy_max - cy_min)
dx_span = max(1, cx_max - cx_min)
dz_dy = (elev[cy_max, x] - elev[cy_min, x]) / (dy_span * cell_size_m)
dz_dx = (elev[y, cx_max] - elev[y, cx_min]) / (dx_span * cell_size_m)
```

Either way, `tests/test_fusion.py`'s parametrize list must include an actual edge cell — e.g. add `(0, 0), (0, 50), (99, 50), (50, 99)` — and the test must assert against `np.gradient`'s own output (or the corrected span formula), not a copy of the code under test.

---

## [HIGH-3] Engine layer performs I/O and depends on the telemetry adapter layer

**Files:** `backend/engine/logger.py`, `backend/engine/fusion.py`.

Two separate hex-architecture violations, both against the audit's explicit mandate ("total decoupling of `backend/engine/` from… I/O operations… serial/LoRa telemetry adapters"). Confirmed clean on the FastAPI axis specifically — `grep -rn "fastapi"` across `backend/engine/` and `backend/schemas/` returns nothing. The violations are elsewhere:

**(a) Direct filesystem I/O inside `engine/`:**
```python
# backend/engine/logger.py
self.log_dir.mkdir(parents=True, exist_ok=True)
...
with open(self.session_file, "a", encoding="utf-8") as f:
```
`FusionEngine.__init__` (`fusion.py:56`) hard-instantiates `self.logger = TelemetryFineTuneLogger()` — a concrete, side-effecting dependency, not an injected port. `FusionEngine` cannot be constructed, let alone unit tested, without touching disk (the async-offload via `asyncio.to_thread` inside `log_inference_event` is good practice for *not blocking the loop*, but doesn't change the coupling problem — it's still a concrete adapter instantiated inside the domain core).

**(b) Reverse dependency, core → adapter layer:**
```python
# backend/engine/fusion.py:24
from backend.telemetry.lora_packet import mission_grid_frame_from_latlon
```
`MissionGridFrame`/`mission_grid_frame_from_latlon` are pure coordinate-frame concerns (they only call `geodetic_to_utm` and `_mgrs_100km_square_letters`) — they're housed in `telemetry/lora_packet.py` for no reason connected to LoRa itself, which is why importing them pulls the adapter layer into the core.

### Fix

```diff
--- a/backend/engine/geo.py
+++ b/backend/engine/geo.py
@@ (near the UTMCoordinate dataclass)
+from dataclasses import dataclass
+
+@dataclass(frozen=True)
+class MissionGridFrame:
+    """Shared georeference for one incident: origin + MGRS square identity."""
+    zone: int
+    band: str
+    square: str
+    origin_easting_m: float
+    origin_northing_m: float
+
+
+def mission_grid_frame_from_latlon(lat: float, lon: float) -> MissionGridFrame:
+    utm = geodetic_to_utm(lat, lon)
+    col_letter, row_letter = _mgrs_100km_square_letters(utm.zone, utm.easting_m, utm.northing_m)
+    return MissionGridFrame(
+        zone=utm.zone, band=mgrs_latitude_band(lat), square=f"{col_letter}{row_letter}",
+        origin_easting_m=utm.easting_m, origin_northing_m=utm.northing_m,
+    )
```

Also rename `_mgrs_100km_square_letters` → `mgrs_100km_square_letters` (drop the leading underscore) since it's now a genuine cross-module public API, not a module-private helper — `lora_packet.py` was already importing it across the underscore boundary, which was itself a smell.

```diff
--- a/backend/telemetry/lora_packet.py
+++ b/backend/telemetry/lora_packet.py
@@
-from backend.engine.geo import (
-    geodetic_to_utm,
-    mgrs_latitude_band,
-    _mgrs_100km_square_letters,
-)
+from backend.engine.geo import MissionGridFrame, mission_grid_frame_from_latlon
+# (remove the now-redundant local MissionGridFrame/mission_grid_frame_from_latlon
+#  class+function definitions — they now live in geo.py)
```

```diff
--- a/backend/engine/fusion.py
+++ b/backend/engine/fusion.py
@@
-from backend.telemetry.lora_packet import mission_grid_frame_from_latlon
+from backend.engine.geo import mission_grid_frame_from_latlon
```

For the logger, introduce a structural port and inject the adapter from the composition root (`main.py`) instead of constructing it inside the engine:

```python
# backend/engine/ports.py  (NEW FILE)
from typing import Any, Dict, Optional, Protocol, Tuple

class MissionEventSink(Protocol):
    async def log_inference_event(
        self, zone_id: str, cell_coords: Tuple[int, int], sensor_payload: Dict[str, Any],
        group_llr_snapshot: Dict[str, float], posterior_p: float,
        directive_issued: Optional[str] = None,
    ) -> None: ...
```

```diff
--- a/backend/engine/fusion.py
+++ b/backend/engine/fusion.py
@@ class FusionEngine:
-    def __init__(self, config_loader: Optional[ConfigLoader] = None):
+    def __init__(self, config_loader: Optional[ConfigLoader] = None, logger: Optional["MissionEventSink"] = None):
         self.config_loader = config_loader or ConfigLoader()
         ...
-        self.logger = TelemetryFineTuneLogger()
+        self.logger = logger or TelemetryFineTuneLogger()   # concrete default only for standalone/test convenience
```

`TelemetryFineTuneLogger` needs no code change — `Protocol` is structural, it already satisfies the shape. This is the minimal-diff path to a real port/adapter boundary without a full DI framework.

```diff
--- a/backend/main.py
+++ b/backend/main.py
@@
 config_loader = ConfigLoader()
 adapter_registry = AdapterRegistry(config_loader)
-fusion_engine = FusionEngine(config_loader)
+fusion_engine = FusionEngine(config_loader, logger=TelemetryFineTuneLogger())
```
(with `from backend.engine.logger import TelemetryFineTuneLogger` added to `main.py`'s imports — the concrete adapter is now wired at the composition root, which is where hex architecture says it belongs).

---

## [HIGH-4] Config hot-swap blocks the event loop that drives the 10Hz broadcast

**File:** `backend/main.py`, `update_fusion_parameters`, lines 184–190.

```python
@app.put("/api/config/fusion-parameters")
async def update_fusion_parameters(req: ParameterUpdateRequest):
    try:
        new_ver = config_loader.update_parameters_in_memory(req.parameters, req.activated_by)
```

`ConfigLoader.update_parameters_in_memory` (`config/loader.py:195-232`) is synchronous and does real, potentially slow blocking I/O: `tempfile.mkstemp`, `yaml.dump`, `f.flush()`, **`os.fsync(f.fileno())`**, `os.replace()` — against, per `README`/`HANDOFF`, a *mounted volume*. Calling this directly from an `async def` route handler blocks the single event loop that also runs `telemetry_ingestion_loop` (hard-coded to a 10Hz cadence) and every connected WebSocket's `broadcast()`. A commander hot-swapping a threshold mid-mission — the exact scenario this endpoint exists for — stalls the live tactical picture for every connected HUD simultaneously, directly contradicting the file's own docstring ("Calibrated for 10 Hz telemetry streaming, non-blocking sensor dispatch"). `logger.py`'s async file-write already uses `asyncio.to_thread` for exactly this reason; this call site doesn't follow the pattern it sits next to.

### Fix

```diff
--- a/backend/main.py
+++ b/backend/main.py
@@ async def update_fusion_parameters(req: ParameterUpdateRequest):
     try:
-        new_ver = config_loader.update_parameters_in_memory(req.parameters, req.activated_by)
+        new_ver = await asyncio.to_thread(
+            config_loader.update_parameters_in_memory, req.parameters, req.activated_by
+        )
```

`ConfigLoader`'s existing `threading.RLock` is compatible with this — it's already the correct primitive for a call now running in a worker thread; no other change needed.

---

## [MEDIUM] Findings

**5 — `grid.origin_lat` validation range doesn't match its own downstream constraint.**
`config/loader.py:64` validates `-90.0 <= origin_lat <= 90.0`. But `fusion.py:99` divides by `cos(radians(origin_lat))` when deriving each cell's longitude, and `geo.py` independently caps valid UTM latitude at `[-80.0, 84.0]` (`geodetic_to_utm` raises `ValueError` outside that). A config that passes validation (e.g. `origin_lat=87`) still fails deep inside grid construction instead of failing at the config boundary with a clear message — the whole point of `_validate_config`'s existence per its own docstring. Tighten to the same bound `geo.py` already enforces:
```diff
-    _require(-90.0 <= origin_lat <= 90.0, "grid.origin_lat out of range [-90, 90]")
+    _require(-80.0 <= origin_lat <= 84.0, "grid.origin_lat out of range [-80, 84] (UTM/MGRS operational limit)")
```

**6 — `utm_to_geodetic` doesn't validate its own output.**
`geodetic_to_utm` rejects out-of-band input on the way in (line 114). `utm_to_geodetic` (the inverse, lines 162–210) validates only `1 <= zone <= 60` — an arbitrary `(easting, northing)` pair that happens to back-project near `phi1 → 90°` drives `cos_phi1 → 0` in the `lon_rad` denominator (line 206) with no guard. Currently unreachable from the live demo (nothing calls this function today — `main.py` never imports it), but it's exactly the function a Phase-6 hardware LoRa bridge will call to reconstruct a fix from a real, possibly corrupted, radio payload. Add a symmetric check:
```python
lat_deg = math.degrees(lat_rad)
if not _LAT_MIN_DEG <= lat_deg <= _LAT_MAX_DEG:
    raise ValueError(f"Derived latitude {lat_deg} outside UTM coverage — corrupt or invalid input.")
```

**7 — `TelemetrySimulator` hardcodes grid geometry instead of reading it from config.**
`simulator.py:105,111,142-143` hardcode `500.0` (grid width) and `5.0` (cell size) as bare literals, duplicating `config/fusion_parameters.yaml`'s `grid.width_m`/`grid.cell_size_m` without deriving from them. `TerrainEngine` correctly reads these from config (`fusion.py:51-55`); the simulator doesn't. If the grid is ever resized (a near-certainty beyond a 500m×500m demo footprint), UAV flight paths and synthetic sensor events stay bounded to the old 500m extent — the rest of the grid goes permanently, silently unscanned, with no error signal.
```diff
-class TelemetrySimulator:
-    def __init__(self, origin_lat: float = 34.183900, origin_lon: float = 77.562100):
+class TelemetrySimulator:
+    def __init__(self, origin_lat: float, origin_lon: float, width_m: float, height_m: float, cell_size_m: float):
         self.origin_lat = origin_lat
         self.origin_lon = origin_lon
+        self.width_m, self.height_m, self.cell_size_m = width_m, height_m, cell_size_m
```
(then replace the `500.0`/`5.0` literals with `self.width_m`/`self.cell_size_m`, and update `main.py`'s construction call to pass `config_loader.config["grid"][...]` through.)

**8 — Silent `(0,0)` fallback in `LoRaTargetPacket.from_directive`.**
```python
cx, cy = 0, 0
parts = directive.target_zone_id.replace("cell_", "").split("_")
if len(parts) == 2:
    cx, cy = int(parts[0]), int(parts[1])
```
A malformed `target_zone_id` silently produces a *plausible-looking* packet pointing at grid cell (0,0) instead of raising. `base.py`'s own docstring states the project's philosophy plainly: "missing modalities fail loudly rather than fusing with silent defaults." This call site doesn't follow it.
```diff
-        cx, cy = 0, 0
-        parts = directive.target_zone_id.replace("cell_", "").split("_")
-        if len(parts) == 2:
-            cx, cy = int(parts[0]), int(parts[1])
+        parts = directive.target_zone_id.replace("cell_", "").split("_")
+        if len(parts) != 2:
+            raise ValueError(f"Malformed target_zone_id, cannot derive cell coordinates: {directive.target_zone_id!r}")
+        cx, cy = int(parts[0]), int(parts[1])
```

**9 — `websocket_telemetry`'s catch-all swallows errors silently.**
```python
except Exception:
    manager.disconnect(websocket)
```
No `logger.exception(...)`, unlike the structurally identical handler in `telemetry_ingestion_loop`. A `send_json` failure (bad serialization, transport error) vanishes with zero trace.
```diff
     except Exception:
+        logger.exception("WebSocket telemetry session terminated unexpectedly")
         manager.disconnect(websocket)
```

**10 — `ConfigLoader.config` returns a live reference, not a copy.**
Docstring says "treat as read-only"; nothing enforces it. Already tracked in `.ai/BACKLOG.md` ("Copy-on-read check for `ConfigLoader.config` consumers") — this audit reinforces it as a real, not hypothetical, risk given `fusion.py` holds `self.config_loader.config["grid"]` references throughout. Minimal fix: `return copy.deepcopy(self._config_data)` in the property, or add typed snapshot getters (matches the pattern `get_thresholds()`/`get_group_caps()` already use) for every remaining raw `.config[...]` access site.

**11 — RF adapter quality curve doesn't reflect near-field dipole physics.**
`adapters/rf.py:44`: `q_dist = 1.0 / (1.0 + (dist / (max_range * 0.5)) ** 2)` — a generic inverse-square-style saturating curve. A 457kHz avalanche transceiver operates in the magnetic near-field, where real flux-line signal strength falls off closer to `r⁻³`, not `r⁻²`. This doesn't produce a wrong *answer* here — it's a confidence *weight*, not a literal field-strength estimate, and it's bounded/monotonic either way — but the brief specifically asks to audit "VLF/RF dipole equations," and there are none in this codebase; what exists is a plausible-looking but physics-unlabeled heuristic. If the SIH submission's written materials claim dipole-equation fidelity, either cite this as a deliberate simplification or swap the exponent: `(dist / (max_range * 0.5)) ** 3`.

---

## [OPTIMIZATION] Findings

**12 — `calculate_rescuer_hazard` derivative discontinuity at 45°.** Value is continuous (`4.5` from both branches), first derivative jumps `0 → 0.15`. Doesn't affect correctness — `rescuer_risk` only ever feeds an additive denominator term — but if this function is ever used for gradient-based calibration (`scripts/calibrate_parameters.py`), the kink matters. Not urgent.

**13 — Cross-group conditional-independence assumption is implicit.** `fusion.py`'s `aggregate_group_llr_sum = Σ w_g · LLR_g` is textbook naive-Bayes log-odds fusion, valid under the assumption that Group A/B/C evidence is conditionally independent given victim presence. That's a reasonable modeling choice (electronic RF, subsurface radar/seismic, and surface thermal/optical are physically close to independent channels) but it's uncalibrated and undocumented as an assumption anywhere in the code. Worth one docstring line in `fusion.py` for anyone extending the model later.

**14 — `.ai/PROJECT_STATE.md` overstates verification status.** The status table marks "MGRS Military Geotagging… COMPLETE & VERIFIED" and "34 passed" as evidence, citing the exact `43S GT 36343 85694` example this audit also used — but for the one code path the demo's origin happens to exercise. Recommend downgrading that row to "VERIFIED FOR CURRENT DEMO ORIGIN ONLY — see AVALANCHE-VLF_AUDIT.md #1" until [CRITICAL-1]'s fix and its exhaustive regression test land.

---

## Answering the two direct questions from the brief

**"Are the weighting heuristics mathematically sound, or prone to bias under noisy feeds?"** Sound in design, unverified in isolation. `BaseSensorAdapter.compute_llr`'s confidence-interpolation formula is internally consistent — I re-derived its neutral-point algebra (`c* = llr_null / (llr_null - llr_detect)`) independently and it matches the docstring exactly. Traced through `simulator.py`'s injected low-confidence GPR clutter (`confidence_score=0.12`, 8% injection rate): at low `c`, `effective_llr` is pulled toward `llr_null`, which is itself negative (since priors require `P(z|H) > P(z|¬H)`) — noisy low-confidence readings are correctly pulled toward *mildly suppressive*, not naively amplified. Every adapter's `evaluate_quality()` is a bounded, monotonic saturating function with denominators safely bounded away from zero. The caveat is [OPTIMIZATION-13] (independence assumption) and the total absence of adapter-level unit tests (below) — the math holds up under manual/traced audit, but nothing in `tests/` checks it directly.

**"Matrix inversion failures, coordinate projection edge cases?"** No matrix inversion exists to fail (confirmed above). Coordinate-projection edge cases are real and enumerated: [CRITICAL-1] and [MEDIUM-6] are exactly this category; the UTM forward/inverse series math itself (Snyder 1987 eqs. 8-9 through 8-25) was checked term-by-term against the standard reference coefficients and is correct.

---

## Test Coverage Gap Analysis

| Module | Dedicated test file? | Gap |
|---|---|---|
| `engine/adapters/*.py` (5 sensors) | **None** | `evaluate_quality()` bounds/monotonicity/zero-input never unit tested in isolation — only indirectly via `test_fusion.py`'s end-to-end scenarios |
| `engine/terrain.py` | None (partial via `test_fusion.py`) | `compute_prior_prob`'s slope-band logic and DEM generation itself untested; `calculate_rescuer_hazard` monotonicity is tested |
| `telemetry/simulator.py` | None (partial via `test_api.py`, `test_5_phase_mission_progression`) | Victim placement, fault-injection interaction with UAV proximity logic untested directly |
| `engine/logger.py` | **None** | Async JSONL writer has zero test coverage |
| `engine/geo.py` `_mgrs_100km_square_letters` | Indirectly, always via the one safe origin | Root cause of [CRITICAL-1] going undetected — see the three-part analysis under [HIGH-2] and the coverage note under [CRITICAL-1] |
| `telemetry/lora_packet.py` unpack() resilience | Round-trip only | `unpack()`'s own size-check (`raw_bytes` len mismatch) and CRC-mismatch branches are implemented but never exercised by any test — exactly the "malformed binary payload" resilience the brief asks about |
| `main.py` route/WS error paths | Happy-path only | No test sends malformed JSON to `/ws/telemetry` or a deeply-nested adversarial payload to the config hot-swap endpoint |

Recommended new test, directly closing the LoRa gap called out above:
```python
def test_lora_unpack_rejects_corrupt_and_malformed_packets():
    good = LoRaTargetPacket(msg_type=0x01, cell_x=1, cell_y=1, probability=0.5,
        depth_m=1.0, radius_m=0.5, approach_azimuth_deg=90.0, marker_deployed=False,
        respiration_locked=False, is_p1=False, void_detected=False,
        east_offset_m=100, north_offset_m=100).pack()

    with pytest.raises(ValueError, match="Invalid packet size"):
        LoRaTargetPacket.unpack(good[:-1])          # truncated

    corrupt = bytearray(good); corrupt[0] ^= 0xFF     # flip a payload bit, CRC now stale
    with pytest.raises(ValueError, match="CRC-16"):
        LoRaTargetPacket.unpack(bytes(corrupt))
```

---

## Sequential Refactoring Plan (OpenCode Plan/Build mode)

Execute in this order — each step is independently buildable/testable; later steps depend on earlier ones only where noted.

1. **`backend/engine/geo.py`** — Apply the 4-line [CRITICAL-1] diff (row alphabet, set-start index, both moduli → `len(...)`). Run existing `tests/test_geo.py` as a regression gate before continuing.
2. **`tests/test_geo.py`** — Add the two exhaustive parametrized tests from [CRITICAL-1] (zone×column sequence check, row-block no-crash sweep). Confirm all pass against step 1.
3. **`backend/engine/geo.py`** — Add `MissionGridFrame` dataclass + `mission_grid_frame_from_latlon`, rename `_mgrs_100km_square_letters` → `mgrs_100km_square_letters`. Add the `utm_to_geodetic` output-latitude guard from [MEDIUM-6].
4. **`backend/telemetry/lora_packet.py`** — Remove the local `MissionGridFrame`/`mission_grid_frame_from_latlon` definitions; import both from `geo.py` instead. Fix `from_directive`'s silent `(0,0)` fallback per [MEDIUM-8].
5. **`backend/engine/fusion.py`** — Change the `mission_grid_frame_from_latlon` import source from `backend.telemetry.lora_packet` to `backend.engine.geo` (closes the reverse dependency in [HIGH-3]).
6. **`backend/engine/terrain.py`** — Cache `grad_dx`/`grad_dy` from the existing `np.gradient` call in `_generate_dem`.
7. **`backend/engine/fusion.py`** — Replace the hand-rolled boundary-buggy gradient in `_calculate_safe_approach_azimuth` with `self.terrain.grad_dx/grad_dy` lookups (closes [HIGH-2]).
8. **`tests/test_fusion.py`** — Rewrite `test_safe_approach_azimuth_is_contour_perpendicular` to (a) include actual edge cells `(0,0),(0,50),(99,50),(50,99)`, (b) assert against `np.gradient`'s independent output rather than a copy of the code under test.
9. **`backend/engine/ports.py`** (new file) — Add the `MissionEventSink` Protocol.
10. **`backend/engine/fusion.py`** — Accept injected `logger: Optional[MissionEventSink] = None` in `__init__`, defaulting to `TelemetryFineTuneLogger()` only for standalone/test convenience (closes the DI half of [HIGH-3]).
11. **`backend/main.py`** — Wire `TelemetryFineTuneLogger()` explicitly at the composition root into `FusionEngine(...)`; wrap the `update_fusion_parameters` call in `asyncio.to_thread` ([HIGH-4]); add `logger.exception(...)` to `websocket_telemetry`'s catch-all ([MEDIUM-9]).
12. **`backend/config/loader.py`** — Tighten `origin_lat` bound to `[-80, 84]` ([MEDIUM-5]); switch `.config` property to return a deep copy or add remaining typed snapshot getters ([MEDIUM-10]).
13. **`backend/telemetry/simulator.py`** + **`backend/main.py`** — Thread `width_m`/`height_m`/`cell_size_m` from config into `TelemetrySimulator.__init__` instead of hardcoded `500.0`/`5.0` ([MEDIUM-7]).
14. **`tests/test_adapters.py`** (new file) — Unit-test each of the 5 `evaluate_quality()` curves: bounds `[0,1]` (or documented floor), monotonicity in their primary variable, zero/extreme-input behavior.
15. **`tests/test_lora_packet.py`** (new file, or extend `test_fusion.py`) — Add the corrupt-CRC and truncated-size resilience test from the coverage section.
16. **`.ai/PROJECT_STATE.md`** — Correct the MGRS status-table row per [OPTIMIZATION-14] once steps 1–2 are merged.
