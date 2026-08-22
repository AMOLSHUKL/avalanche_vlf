# AVALANCHE-VLF: Engineering Conventions & Implementation Standards

---

## 1. Code Style & Formatting Standards

### 1.1 Python Backend & Fusion Engine
* **Target Version:** Python 3.12+ (Strict type-hinting: `X | None`, `list[T]`, `dict[K, V]`).
* **Typing Coverage:** 100% type annotation across all module boundaries, function signatures, class methods, and return statements.
* **Pydantic Standards:** Exclusively use Pydantic v2.
  * Use `model_config = ConfigDict(...)`.
  * Use `@field_validator("field_name")` class methods.
  * Deprecated Pydantic v1 patterns (`@validator`, `class Config:`) are strictly forbidden.
* **Datetime Policy:** All timestamps MUST be timezone-aware UTC (`datetime.now(timezone.utc)`). Naive datetime objects are invalid and will fail Pydantic model validation.
* **Numerical Clamping Guardrails:**
  * Probabilities: Bound to $[0.001, 0.999]$ prior to odds computation to prevent division by zero.
  * Log-Odds: Clamped to $[-15.0, 15.0]$ (or $[-50.0, 50.0]$ at domain boundaries) to prevent exponential float overflow (`math.exp(-new_llr)`).
  * Confidence Scores: Clamped to $[0.0, 1.0]$.
* **Naming Conventions:**
  * Classes / Types: `PascalCase` (e.g., `FusionEngine`, `BaseSensorAdapter`, `LoRaTargetPacket`).
  * Functions / Methods: `snake_case` (e.g., `update_cell_evidence`, `compute_llr`, `evaluate_quality`).
  * Constants / Enums: `UPPER_SNAKE_CASE` (e.g., `PriorityZoneEnum.P1`, `MSG_TYPE_TARGET_VECTOR`).
  * Private / Internal Attributes: Leading underscore `_` (e.g., `self._state_lock`, `self._group_cumulative_scores`).

### 1.2 JavaScript & Frontend Standards
* **Target Environment:** Vanilla ECMAScript 6+ running natively in modern browsers.
* **Zero Dependency Rule:** No external runtime dependencies (no React, Vue, jQuery, Tailwind, or CDN scripts). All styling, animations, and state handling must remain self-contained within `frontend/index.html` and `frontend/app.js`.
* **Coordinate System Transformation:**
  * Standard Web Canvas coordinates: Origin $(0, 0)$ is at Top-Left, with $+Y$ pointing Down.
  * SAR Tactical Grid coordinates: Origin $(0, 0)$ is at Bottom-Left (South-West), with $+Y$ pointing North.
  * **Mandatory Inversion Rule:** All canvas rendering routines must invert the Y-axis:
    $$\text{pixel\_y} = \text{canvas.height} - ((y + 1) \times \text{cell\_size\_px})$$
* **Naming Conventions:**
  * Variables / Functions: `camelCase` (e.g., `renderTriageQueue`, `toggleFault`, `openInspector`).
  * Global State: Managed in the centralized `state` dictionary.

---

## 2. Design Patterns & Architecture Rules

### 2.1 Concurrency & State Mutation
* **Centralized State Lock:** `FusionEngine` enforces thread and task safety via an internal `asyncio.Lock()` (`self._state_lock`). Every mutation of grid cells, pass history, accumulators, and active directives MUST occur inside `async with self._state_lock:`.
* **Non-Blocking I/O:** Disk writes and telemetry logging must NEVER block the event loop inside the critical lock section. Logging operations must be dispatched as asynchronous tasks (`asyncio.create_task()`) and executed in worker threads via `asyncio.to_thread()`.
* **WebSocket Backpressure Management:** `ConnectionManager` isolates subscribers with fixed-capacity buffers (`asyncio.Queue(maxsize=5)`). If a slow consumer fills its queue, the oldest unconsumed frame must be evicted via `q.get_nowait()` before enqueuing the new frame.

### 2.2 Polymorphic Adapter Pattern
* Every sensor model must inherit from `BaseSensorAdapter` in `backend/engine/adapters/base.py`.
* Adapters must strictly implement:
  1. `parse_raw(raw_input: Any) -> BaseSensorPayload`
  2. `evaluate_quality(payload: BaseSensorPayload) -> float` (returns $q_k \in [0.05, 1.0]$).
* Evidence computation must use the symmetric log-likelihood formulation:
  $$\text{LLR}_{\text{eff}} = c \cdot \ln\left(\frac{P(z \mid H)}{P(z \mid \neg H)}\right) + (1 - c) \cdot \ln\left(\frac{1 - P(z \mid H)}{1 - P(z \mid \neg H)}\right)$$

### 2.3 Dynamic Thread-Safe Configuration
* Configuration is managed via the `ConfigLoader` singleton in `backend/config/loader.py`, guarded by a re-entrant lock (`threading.RLock()`).
* Runtime updates made via `update_parameters_in_memory()` increment the configuration version and persist changes directly to disk without restarting the service.

---

## 3. Strict Constraints & Anti-Patterns

1. **NO Blocking Calls in Async Coroutines:** Never call `time.sleep()` within async pipelines. Use `await asyncio.sleep()` or non-blocking computational generators.
2. **NO Linear Score Averaging:** Probability updates must strictly follow Bayesian log-odds arithmetic. Averaging percentages across modalities is strictly forbidden.
3. **NO Uncapped Intra-Group Evidence:** Sensor evidence within the same group (**Group A**, **Group B**, **Group C**) must pass through leaky accumulators and be bounded by group saturation caps ($\Gamma_g$).
4. **NO Hardcoded Survival & Prior Parameters:** All threshold values, prior probabilities, group saturation caps, and survival parameters must be resolved dynamically from `ConfigLoader`.
5. **NO Naive Datetime Objects:** Never instantiate `datetime.now()` without passing `timezone.utc`.
6. **NO Omission of Truncated Code:** When generating code fixes or features, always provide the complete, copy-pasteable file or a clean unified diff. Never use placeholders like `// ... rest of code`.

---

## 4. Testing & Quality Verification Commands

### 4.1 Execute Pytest Verification Suite
```bash
# Run all unit and integration tests with short traceback
pytest tests/test_fusion.py -v --tb=short

# Run with stdout capture disabled (to inspect logs)
pytest tests/test_fusion.py -s -v
```

### 4.2 Start Local Development Server
```bash
# Launch FastAPI ASGI server with hot reloading enabled
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4.3 Container Build & Execution
```bash
# Build multi-stage Docker image
docker build -t avalanche-vlf:latest .

# Run container in background
docker run -d -p 8000:8000 --name sar-command-node avalanche-vlf:latest

# Verify live health probe inside container
docker exec -it sar-command-node python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/healthz').read().decode())"
```

### 4.4 Automated API Validation Snippets
```bash
# 1. Healthcheck verification
curl -s http://localhost:8000/api/healthz

# 2. Query active search map summary
curl -s http://localhost:8000/api/search-map

# 3. Inject hardware failure (disable 457 kHz Transceiver)
curl -s -X POST http://localhost:8000/api/inject-failure \
  -H "Content-Type: application/json" \
  -d '{"sensor_type": "TRANSCEIVER_457", "is_disabled": true}'

# 4. Dynamically update fusion parameters at runtime
curl -s -X PUT http://localhost:8000/api/config/fusion-parameters \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"thresholds": {"tau_p1": 0.88, "evidence_decay_factor": 0.95}}, "activated_by": "FIELD_OPERATOR"}'
```