#!/usr/bin/env python3
"""Test panel state persistence API.

Verifies the /api/panel-state contract used by the dashboard:
  - GET returns { "panels": {...}, "panel_count": <int|null> }
  - PUT persists both the per-panel project/agent map AND the chosen
    channel count (panel_count), so the layout survives a reload.

Override the target with CC_TEST_HOST, e.g.
    CC_TEST_HOST=http://127.0.0.1:5051 .venv/bin/python test_panel_api.py
"""

import os
import json

import requests

HOST = os.environ.get("CC_TEST_HOST", "http://127.0.0.1:5050")


def test_health():
    r = requests.get(f"{HOST}/api/health", timeout=5)
    print(f"Health: {r.json()}")
    assert r.json()["ok"] is True
    print("✓ /api/health works\n")


def test_get_panel_state():
    r = requests.get(f"{HOST}/api/panel-state", timeout=5)
    data = r.json()
    print(f"GET /api/panel-state: {json.dumps(data, indent=2)}")
    assert isinstance(data, dict)
    # New contract: top-level "panels" map + "panel_count".
    assert "panels" in data, "response missing 'panels' key"
    assert "panel_count" in data, "response missing 'panel_count' key"
    assert isinstance(data["panels"], dict)
    print("✓ /api/panel-state GET returns new shape\n")


def test_save_panel_state_via_api():
    # This is what the frontend now does: persist panels + panel_count.
    test_data = {
        "panels": {
            "0": {"project": "test-project-0", "agent": "claude"},
            "1": {"project": "test-project-1", "agent": "opencode"},
            "2": {"project": "test-project-2", "agent": "codex"},
        },
        "panel_count": 3,
    }
    r = requests.put(f"{HOST}/api/panel-state", json=test_data, timeout=5)
    print(f"PUT /api/panel-state: {r.status_code} {r.json()}")
    assert r.json()["ok"] is True
    print("✓ /api/panel-state PUT works\n")

    # Verify it was saved with the new shape.
    saved = requests.get(f"{HOST}/api/panel-state", timeout=5).json()
    print(f"Saved state: {json.dumps(saved, indent=2)}")
    panels = saved["panels"]
    assert panels["0"]["project"] == "test-project-0"
    assert panels["1"]["agent"] == "opencode"
    assert panels["2"]["project"] == "test-project-2"
    # The whole point of the fix: channel count round-trips.
    assert saved["panel_count"] == 3, f"panel_count not persisted: {saved['panel_count']}"
    print("✓ Panel state + panel_count persisted correctly\n")


def test_panel_count_round_trips():
    """Changing only the channel count should persist independently."""
    for count in (1, 2, 3):
        body = {"panels": {"0": {"project": "p", "agent": "claude"}}, "panel_count": count}
        requests.put(f"{HOST}/api/panel-state", json=body, timeout=5)
        saved = requests.get(f"{HOST}/api/panel-state", timeout=5).json()
        assert saved["panel_count"] == count, f"expected {count}, got {saved['panel_count']}"
        print(f"✓ panel_count={count} round-trips")
    print()


def test_invalid_panel_count_rejected():
    """Out-of-range counts are ignored, not stored."""
    # Seed a known-good value first.
    requests.put(
        f"{HOST}/api/panel-state",
        json={"panels": {}, "panel_count": 2},
        timeout=5,
    )
    # Now send a bogus count; server should keep the previous valid value.
    requests.put(
        f"{HOST}/api/panel-state",
        json={"panels": {}, "panel_count": 99},
        timeout=5,
    )
    saved = requests.get(f"{HOST}/api/panel-state", timeout=5).json()
    assert saved["panel_count"] == 2, f"invalid count leaked through: {saved['panel_count']}"
    print("✓ invalid panel_count rejected (kept previous value)\n")


def main():
    print("=" * 60)
    print(f"TESTING PANEL STATE PERSISTENCE  ->  {HOST}")
    print("=" * 60)
    print()

    test_health()
    test_get_panel_state()
    test_save_panel_state_via_api()
    test_panel_count_round_trips()
    test_invalid_panel_count_rejected()

    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
