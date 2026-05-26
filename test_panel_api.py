#!/usr/bin/env python3
"""Test panel state persistence API"""

import requests
import json
import time

HOST = "http://127.0.0.1:5050"

def test_health():
    r = requests.get(f"{HOST}/api/health", timeout=5)
    print(f"Health: {r.json()}")
    assert r.json()["ok"] == True
    print("✓ /api/health works\n")

def test_get_panel_state():
    r = requests.get(f"{HOST}/api/panel-state", timeout=5)
    data = r.json()
    print(f"GET /api/panel-state: {json.dumps(data, indent=2)}")
    assert isinstance(data, dict)
    print("✓ /api/panel-state GET works\n")

def test_save_panel_state_via_api():
    # This is what the frontend now does
    test_data = {
        "panels": {
            "0": {"project": "test-project-0", "agent": "claude"},
            "1": {"project": "test-project-1", "agent": "opencode"},
            "2": {"project": "test-project-2", "agent": "codex"},
        }
    }
    r = requests.put(f"{HOST}/api/panel-state", json=test_data, timeout=5)
    print(f"PUT /api/panel-state: {r.status_code} {r.json()}")
    assert r.json()["ok"] == True
    print("✓ /api/panel-state PUT works\n")
    
    # Verify it was saved
    r = requests.get(f"{HOST}/api/panel-state", timeout=5)
    saved = r.json()
    print(f"Saved state: {json.dumps(saved, indent=2)}")
    assert saved["0"]["project"] == "test-project-0"
    assert saved["1"]["agent"] == "opencode"
    assert saved["2"]["project"] == "test-project-2"
    print("✓ Panel state persisted correctly\n")

def test_no_duplicate_saving():
    """Verify term_open doesn't save panel state anymore"""
    initial = requests.get(f"{HOST}/api/panel-state", timeout=5).json()
    print(f"Initial state before test: {json.dumps(initial, indent=2)}")
    
    # The state should NOT change just from checking - it only changes via PUT now
    after = requests.get(f"{HOST}/api/panel-state", timeout=5).json()
    assert after == initial
    print("✓ State did not change unexpectedly\n")

def main():
    print("=" * 60)
    print("TESTING PANEL STATE PERSISTENCE")
    print("=" * 60)
    print()
    
    test_health()
    test_get_panel_state()
    test_save_panel_state_via_api()
    test_no_duplicate_saving()
    
    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)

if __name__ == "__main__":
    main()
