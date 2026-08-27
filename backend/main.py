"""
FastAPI Tactical Command Gateway.
Calibrated for 10 Hz telemetry streaming, non-blocking sensor dispatch,
full modality fault injection, and backpressure-protected WebSockets.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config.loader import ConfigLoader
from backend.engine.adapters.registry import AdapterRegistry
from backend.engine.fusion import FusionEngine
from backend.engine.logger import TelemetryFineTuneLogger
from backend.schemas.sensors import SensorTypeEnum
from backend.telemetry.simulator import TelemetrySimulator

logger = logging.getLogger("avalanche_vlf.gateway")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

# CORS origins for the tactical HUD. Air-gapped deployments serve everything
# same-origin; extend via ALLOWED_CORS_ORIGINS (comma-separated) if needed.
_DEFAULT_ORIGINS = ["*"]


class ConnectionManager:
    """Manages active WebSocket subscribers with frame-drop backpressure buffers."""
    def __init__(self, max_buffer_size: int = 5):
        self.active_connections: set[WebSocket] = set()
        self.client_queues: dict[WebSocket, asyncio.Queue] = {}
        self.max_buffer_size = max_buffer_size

    async def connect(self, websocket: WebSocket) -> asyncio.Queue:
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=self.max_buffer_size)
        self.active_connections.add(websocket)
        self.client_queues[websocket] = q
        return q

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self.client_queues.pop(websocket, None)

    async def broadcast(self, message: dict[str, Any]):
        for ws, q in list(self.client_queues.items()):
            try:
                if q.full():
                    with suppress(asyncio.QueueEmpty):
                        q.get_nowait()
                q.put_nowait(message)
            except Exception:
                logger.exception("Dropping unresponsive WebSocket client")
                self.disconnect(ws)


# Global singletons; concrete adapters wired at the composition root.
config_loader = ConfigLoader()
adapter_registry = AdapterRegistry(config_loader)
_grid_cfg = config_loader.config["grid"]
fusion_engine = FusionEngine(config_loader, logger=TelemetryFineTuneLogger())
simulator = TelemetrySimulator(
    origin_lat=float(_grid_cfg["origin_lat"]),
    origin_lon=float(_grid_cfg["origin_lon"]),
    width_m=float(_grid_cfg["width_m"]),
    height_m=float(_grid_cfg["height_m"]),
    cell_size_m=float(_grid_cfg["cell_size_m"]),
)
manager = ConnectionManager(max_buffer_size=5)
background_task: asyncio.Task | None = None


async def telemetry_ingestion_loop():
    """Background task streaming multi-modal drone telemetry at 10 Hz."""
    consecutive_failures = 0
    stream = simulator.generate_flight_stream()
    while True:
        try:
            # Pull frame from computational generator without thread sleep
            frame = next(stream)
            updated_zones = []
            for event in frame["sensor_events"]:
                cx, cy = event["target_cell"]
                payload = event["payload"]
                llr, quality = adapter_registry.process_payload(payload)
                state = await fusion_engine.update_cell_evidence(cx, cy, payload, llr, quality)
                updated_zones.append(state.model_dump(mode="json"))

            mission_clock = fusion_engine.get_survival_clock_snapshot()
            broadcast_envelope = {
                "type": "telemetry_frame",
                "incident_id": "INCIDENT_HIMALAYA_2026_01",
                "mission_phase": frame["mission_phase"],
                "mission_clock": mission_clock,
                "uav_telemetry": frame["uav_telemetry"],
                "updated_zones": updated_zones,
                "directives": [d.model_dump(mode="json") for d in fusion_engine.active_directives]
            }
            await manager.broadcast(broadcast_envelope)
            consecutive_failures = 0
            # Calibrate loop rate to 10 Hz (100 ms)
            await asyncio.sleep(0.10)
        except asyncio.CancelledError:
            break
        except Exception:
            consecutive_failures += 1
            logger.exception("Telemetry loop iteration failed", extra={
                "consecutive_failures": consecutive_failures
            })
            await asyncio.sleep(min(0.5 * 2 ** min(consecutive_failures, 4), 8.0))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task
    background_task = asyncio.create_task(telemetry_ingestion_loop())
    yield
    if background_task:
        background_task.cancel()


app = FastAPI(
    title="AVALANCHE-VLF Tactical Fusion API",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEFAULT_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount static UI assets. Browsers heuristic-cache responses without explicit
# Cache-Control, which served stale JS after deploys (the "my fixes are not
# showing" incident). no-cache forces a cheap ETag revalidation every load.
frontend_path = Path(__file__).parent.parent / "frontend"


@app.middleware("http")
async def static_no_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/frontend"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/frontend", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


class FailureInjectionRequest(BaseModel):
    sensor_type: SensorTypeEnum
    is_disabled: bool


class ParameterUpdateRequest(BaseModel):
    parameters: dict[str, Any]
    activated_by: str = Field(default="COMMANDER_OVERRIDE")


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Automatic root redirect to Tactical Operations Command Dashboard."""
    return RedirectResponse(url="/frontend/index.html")


@app.get("/api/healthz")
async def healthz():
    loop_alive = not (background_task and background_task.done())
    return {
        "status": "HEALTHY" if loop_alive else "DEGRADED_TELEMETRY_LOOP_DOWN",
        "grid_cells": len(fusion_engine.grid),
        "active_clients": len(manager.active_connections),
        "config_version": config_loader.config.get("version"),
        "telemetry_loop_alive": loop_alive
    }


@app.get("/api/search-map")
async def get_search_map():
    return await fusion_engine.get_search_map_summary()


@app.post("/api/inject-failure")
async def inject_failure(req: FailureInjectionRequest):
    simulator.set_sensor_fault(req.sensor_type.value, req.is_disabled)
    return {"status": "SUCCESS", "sensor_type": req.sensor_type.value, "is_disabled": req.is_disabled}


@app.put("/api/config/fusion-parameters")
async def update_fusion_parameters(req: ParameterUpdateRequest):
    try:
        new_ver = await asyncio.to_thread(
            config_loader.update_parameters_in_memory, req.parameters, req.activated_by
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "SUCCESS", "new_version": new_ver}


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    q = await manager.connect(websocket)
    try:
        while True:
            msg = await q.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket telemetry session terminated unexpectedly")
        manager.disconnect(websocket)
