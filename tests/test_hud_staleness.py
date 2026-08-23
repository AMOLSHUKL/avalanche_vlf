"""HUD telemetry-link staleness indicator.

The HUD must never present a frozen telemetry stream as current: frames arrive
at 10 Hz, so silence beyond 3 s flips the link pill to STALE and beyond 10 s
(or no frame ever) to OFFLINE. The decision rule lives in
frontend/link_state.js as a pure function; these tests execute the real file
under Node so the shipped artifact is what gets verified.
"""

import json
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
LINK_STATE_JS = FRONTEND / "link_state.js"


def _run_node(payload):
    script = (
        "const { LinkHealth } = require(process.argv[1]);\n"
        "console.log(JSON.stringify(LinkHealth.classify(...process.argv.slice(2))));\n"
    )
    result = subprocess.run(
        ["node", "-e", script, str(LINK_STATE_JS), str(payload[0]), str(payload[1])],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(
    not LINK_STATE_JS.exists(), reason="frontend/link_state.js missing"
)
def test_fresh_frame_within_cutoff_is_live():
    assert _run_node((100_000, 102_500)) == "live"
    assert _run_node((100_000, 103_000)) == "live"  # exactly at cutoff is not yet stale


def test_silence_beyond_three_seconds_is_stale():
    assert _run_node((100_000, 103_001)) == "stale"
    assert _run_node((100_000, 110_000)) == "stale"


def test_silence_beyond_ten_seconds_is_offline():
    assert _run_node((100_000, 110_001)) == "offline"
    assert _run_node((100_000, 300_000)) == "offline"


def test_never_received_frame_is_offline():
    assert _run_node((0, 500_000)) == "offline"


def test_clock_skew_backwards_is_treated_as_live():
    assert _run_node((100_000, 99_999)) == "live"


def test_stalled_stream_transitions_live_stale_offline():
    """Simulate a stream that stops at t=10.000s after flowing at 10 Hz."""
    last_frame_ms = 10_000
    observations = [
        (t_ms, _run_node((last_frame_ms, t_ms)))
        for t_ms in (9_800, 10_400, 12_900, 13_200, 19_900, 20_100)
    ]
    assert observations == [
        (9_800, "live"),
        (10_400, "live"),
        (12_900, "live"),    # 2.9 s silent: still inside cutoff
        (13_200, "stale"),   # >3 s silent: frozen picture flagged
        (19_900, "stale"),
        (20_100, "offline"), # >10 s silent: link declared down
    ]
