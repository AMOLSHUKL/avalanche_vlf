"""
API boundary smoke tests: request validation, fault injection, hot-swap
rejection, health probe behavior, and live telemetry delivery.
"""
from tests.conftest import drain_until


def test_healthz_reports_live_loop(client):
    response = client.get("/api/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HEALTHY"
    assert body["telemetry_loop_alive"] is True


def test_telemetry_stream_carries_mission_phase_and_clock(client):
    with client.websocket_connect("/ws/telemetry") as ws:
        frame = drain_until(ws, lambda f: f.get("type") == "telemetry_frame")
        assert frame["mission_phase"]
        clock = frame["mission_clock"]
        for key in ("incident_epoch_s", "server_epoch_s", "elapsed_min", "survival_probability"):
            assert key in clock


def test_inject_failure_accepts_known_sensor(client):
    response = client.post(
        "/api/inject-failure",
        json={"sensor_type": "TRANSCEIVER_457", "is_disabled": True},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"


def test_inject_failure_rejects_unknown_sensor(client):
    # Pydantic enum validation rejects unknown modalities at the boundary.
    response = client.post(
        "/api/inject-failure",
        json={"sensor_type": "TELEPATHY_ARRAY", "is_disabled": True},
    )
    assert response.status_code == 422


def test_invalid_parameter_hotswap_returns_422(client):
    response = client.put(
        "/api/config/fusion-parameters",
        json={
            "parameters": {"thresholds": {"tau_p1": 1.5}},
            "activated_by": "TEST",
        },
    )
    assert response.status_code == 422
    assert "rejected parameter update" in response.json()["detail"]


def test_search_map_exposes_mission_clock(client):
    response = client.get("/api/search-map")
    assert response.status_code == 200
    body = response.json()
    assert "mission_clock" in body
    clock = body["mission_clock"]
    for key in ("incident_epoch_s", "server_epoch_s", "elapsed_min", "survival_probability"):
        assert key in clock
    assert 0.0 <= clock["survival_probability"] <= 1.0
