#!/usr/bin/env python3
"""Unit tests for ClaudeSubsService status classification + switch hardening.

These run fully offline: a fake cc-acct module stands in for the real one so we
never hit Anthropic's API. They lock in the rules that caused real incidents:

  * `allowed_warning` is USABLE (state 'warning'), never red/limited.
  * `overage_reason` (out_of_credits / org_level_disabled) does NOT, on its own,
    mark an account limited — it's a persistent header present even when allowed.
  * Only an actual `rejected` window (or overall 'rejected') is 'limited'.
"""
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.claude_subs import ClaudeSubsService


def _fake_module(rate_limit):
    """Build a stand-in cc-acct module returning a fixed rate-limit dict."""
    m = types.SimpleNamespace()
    far_future_ms = int((time.time() + 7 * 3600) * 1000)  # well past headroom
    profile = {
        "name": "acct",
        "accessToken": "tok",
        "refreshToken": "ref",
        "expiresAt": far_future_ms,
        "emailAddress": "x@example.com",
        "subscriptionType": "pro",
        "accountUuid": "A",
        "organizationUuid": "O",
        "oauthAccount": {"accountUuid": "A", "organizationUuid": "O"},
    }
    m.load_profile = lambda name: dict(profile)
    m.list_profiles = lambda: ["acct"]
    # Non-active: live identity differs, so _keep_alive/_is_active treat it as
    # a non-active account whose token is fresh (returns early, no network).
    m.read_current_account = lambda: {"accountUuid": "B", "organizationUuid": "Z"}
    m.is_active = lambda p: False
    m.read_current_oauth = lambda: {"refreshToken": "different", "accessToken": "diff"}
    m.org_name = lambda p: "Org"
    m.probe_rate_limit = lambda token: rate_limit
    m.write_json_secure = lambda path, data: None
    m.profile_path = lambda name: Path("/tmp/none")
    return m


def _classify(rate_limit):
    svc = ClaudeSubsService.__new__(ClaudeSubsService)  # skip __init__/import
    import threading
    svc._lock = threading.Lock()
    m = _fake_module(rate_limit)
    return svc._status_for(m, "acct", probe=True)


def _win(status, util, reset=None):
    return {"status": status, "utilization": util, "reset": reset}


def test_allowed_is_ok():
    rl = {"5h": _win("allowed", 0.01), "7d": _win("allowed", 0.01), "overall": "allowed"}
    out = _classify(rl)
    assert out["state"] == "ok", out
    print("  ✓ allowed -> ok")


def test_allowed_warning_is_usable_not_limited():
    # The exact bug: 75% weekly + out_of_credits header was shown as RATE LIMITED.
    rl = {
        "5h": _win("allowed", 0.01),
        "7d": _win("allowed_warning", 0.75),
        "overall": "allowed_warning",
        "overage_reason": "out_of_credits",
    }
    out = _classify(rl)
    assert out["state"] == "warning", out
    assert ClaudeSubsService._account_ready(out) is True, "warning must be usable"
    print("  ✓ allowed_warning -> warning (usable, not limited)")


def test_overage_reason_alone_does_not_limit():
    # roel reported org_level_disabled while fully allowed — must stay ok.
    rl = {
        "5h": _win("allowed", 0.01),
        "7d": _win("allowed", 0.01),
        "overall": "allowed",
        "overage_reason": "org_level_disabled",
    }
    out = _classify(rl)
    assert out["state"] == "ok", out
    assert ClaudeSubsService._account_ready(out) is True
    print("  ✓ overage_reason on an allowed account -> still ok")


def test_rejected_window_is_limited():
    reset = int(time.time() + 3600)
    rl = {
        "5h": _win("rejected", 1.0, reset),
        "7d": _win("allowed", 0.5),
        "overall": "rejected",
        "overage_reason": "out_of_credits",
    }
    out = _classify(rl)
    assert out["state"] == "limited", out
    assert out["ok_again"] == reset, out
    assert ClaudeSubsService._account_ready(out) is False
    print("  ✓ rejected window -> limited with ok_again")


def run():
    tests = [
        test_allowed_is_ok,
        test_allowed_warning_is_usable_not_limited,
        test_overage_reason_alone_does_not_limit,
        test_rejected_window_is_limited,
    ]
    print("TEST: ClaudeSubsService status classification")
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed} test(s) FAILED")
        return 1
    print("\nAll classification tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
