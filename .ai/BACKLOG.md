# AVALANCHE-VLF Backlog (mechanizable improvements)

Filed from reflect session 2026-08-22. Skill-description tunes were declined;
their substance is preserved here as project-level mechanisms instead.

## Test infrastructure
- [x] `tests/conftest.py`: shared fixture yielding a context-managed `TestClient`
      (lifespan only runs under `with`) + a `drain_until(ws, predicate)` helper so
      no test sleeps fixed amounts waiting for WebSocket frames.
      (Closed: both exist in tests/conftest.py.)
- [ ] `pyproject.toml`: `filterwarnings` entry for the known-noise pytest-asyncio
      deprecation (`asyncio.get_event_loop_policy`) under Python 3.14.
- [x] Parametrized known-answer vectors transcribed from published references
      (NGA TM 8358.1 worked examples) into `test_geo.py`, beyond null-island +
      round-trip closure.
      (Closed 2026-08-22: `_LIBMGRS_ANCHORS` + exhaustive zone/row sweeps in
      test_geo.py, cross-checked against reference libmgrs; see audit #1.)
- [x] Unit tests pinning the east-over-north bearing convention
      (`atan2(dz_dx, dz_dy)`) and LoRa offset raise-not-wrap boundaries (raise
      case covered; add positive boundary 0 and 65535).
      (Closed 2026-08-22: boundary-bearing test + full uint16 offset range in
      test_fusion.py / test_lora_packet.py.)

## Consumer-boundary reliability
- [x] HUD staleness indicator: telemetry frames carry server timestamps; the HUD
      must show an explicit STALE/OFFLINE banner when frames stop arriving beyond
      a cutoff (e.g. > 3 s), never present a frozen clock as current.
      (Closed 2026-08-23: rule extracted to frontend/link_state.js, consumed by
      the app.js watchdog; tests/test_hud_staleness.py executes the shipped file
      under Node incl. a stalled-stream transition sweep.)
- [x] Test simulating a stalled stream asserting the indicator fires.
      (Closed 2026-08-23: test_stalled_stream_transitions_live_stale_offline.)

## Security / runtime invariants as executable checks
- [ ] Startup test asserting CORS is not credentials+wildcard.
- [ ] Central task-spawn helper (strong-ref set + done-callback) reused by any
      future fire-and-forget `asyncio.create_task` call sites.
- [x] Copy-on-read check for `ConfigLoader.config` consumers (or typed snapshot
      getters everywhere).
      (Closed 2026-08-22: all accessors return deep copies; mutation-isolation
      tests in test_config_validation.py. See audit #10.)

## Project knowledge capture
- [ ] CONTEXT.md / domain glossary: server-owns-time rule (incident_epoch_s,
      monotonic intervals, streamed snapshots), MGRS anchor semantics
      (31N AA 66021 00000 + round-trip <1mm), MissionGridFrame origin-relative
      offset encoding, east-over-north bearing convention.

## Repo hygiene
- [ ] Initialize git BEFORE next multi-file change session (unit zero commit).
- [ ] AGENTS.md: record `venv/bin/python -m pytest tests/` invocation,
      heredoc verification pattern, no-bare-python rule for this Termux env.
