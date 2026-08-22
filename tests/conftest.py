"""
Shared test fixtures: a lifespan-correct TestClient and a deterministic
WebSocket drain helper (no fixed sleeps).
"""
import pytest
from fastapi.testclient import TestClient

from backend.config.loader import ConfigLoader
from backend.main import app


@pytest.fixture()
def client():
    """TestClient with lifespan active, bound to a fresh config singleton."""
    ConfigLoader.reset_instance()
    with TestClient(app=app) as test_client:
        yield test_client
    ConfigLoader.reset_instance()


def drain_until(ws, predicate, timeout_s: float = 30.0):
    """
    Pull WebSocket frames until predicate(frame) is truthy. Fails loudly on
    timeout instead of sleeping through fixed delays.
    """
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = ws.receive_json()
        if predicate(frame):
            return frame
    raise AssertionError(f"predicate not satisfied within {timeout_s}s")
