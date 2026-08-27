"""
Hexagonal-architecture ports for the fusion engine core.

The engine depends only on the structural interfaces below; concrete
adapters (filesystem JSONL logging, future LoRa bridges) satisfy them
from outside the core and are wired at the composition root.
"""
from typing import Any, Protocol


class MissionEventSink(Protocol):
    """Sink for per-inference telemetry events emitted by FusionEngine."""

    async def log_inference_event(
        self,
        zone_id: str,
        cell_coords: tuple[int, int],
        sensor_payload: dict[str, Any],
        group_llr_snapshot: dict[str, float],
        posterior_p: float,
        directive_issued: str | None = None,
    ) -> None:
        ...
