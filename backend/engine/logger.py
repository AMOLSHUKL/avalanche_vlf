"""
Non-Blocking Asynchronous Structured JSONL Inference and Verification Logger.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class TelemetryFineTuneLogger:
    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = Path(log_dir or (Path(__file__).parent.parent.parent / "logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.session_file = self.log_dir / f"sar_mission_{session_id}.jsonl"

    def _write_line_sync(self, line: str) -> None:
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    async def log_inference_event(
        self,
        zone_id: str,
        cell_coords: Tuple[int, int],
        sensor_payload: Dict[str, Any],
        group_llr_snapshot: Dict[str, float],
        posterior_p: float,
        directive_issued: Optional[str] = None
    ) -> None:
        event = {
            "record_type": "INFERENCE_STEP",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": zone_id,
            "cell_x": cell_coords[0],
            "cell_y": cell_coords[1],
            "sensor_payload": sensor_payload,
            "group_llr_snapshot": group_llr_snapshot,
            "posterior_probability": posterior_p,
            "directive_issued": directive_issued
        }
        line = json.dumps(event)
        # Execute disk I/O in thread pool to prevent event-loop blocking
        await asyncio.to_thread(self._write_line_sync, line)

    async def log_ground_truth_outcome(
        self,
        directive_id: str,
        zone_id: str,
        outcome: str,
        actual_depth_m: Optional[float] = None,
        notes: str = ""
    ) -> None:
        record = {
            "record_type": "GROUND_TRUTH_VERIFICATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "directive_id": directive_id,
            "zone_id": zone_id,
            "outcome": outcome,
            "actual_depth_m": actual_depth_m,
            "notes": notes
        }
        line = json.dumps(record)
        await asyncio.to_thread(self._write_line_sync, line)
