"""ClaudeSubsService — surfaces Claude Code subscription usage in the dashboard.

Thin wrapper around the standalone ``cc-accounts/cc-acct`` CLI: it loads that
script as a module (it has no ``.py`` extension) and reuses its OAuth + rate
limit probing logic so there's a single source of truth.

Responsibilities:
  - report each saved account's rate-limit windows + reset timestamps
    (so the frontend can render a live countdown and a green/red indicator),
  - keep every subscription's tokens alive so they NEVER run out,
  - switch the active Claude Code account on demand.

Token model (from the cc-acct script):
  - Access token lives ~8h; the refresh token is long-lived but SINGLE-USE —
    each refresh rotates it and invalidates the previous one. Whoever holds the
    latest rotated token owns the chain, so it must always be persisted back.

The "never run out" strategy, split by account role:
  * NON-ACTIVE accounts — we own their refresh chain. We proactively refresh
    them well BEFORE expiry (default: 45 min of headroom) and persist the
    rotated token. Safe because nothing else touches these tokens.
  * The ACTIVE account — Claude Code normally refreshes this one while it's
    making API calls. We never *race* it: we re-sync our stored snapshot FROM
    Claude Code's live ~/.claude/.credentials.json so our copy tracks its
    rotations. BUT an idle active account (e.g. one auto-switch parked here)
    gets no API calls, so Claude Code never refreshes it and it would lapse.
    As a safety net, when the active token is near expiry AND its live refresh
    token still matches our snapshot (proof Claude Code hasn't rotated it), we
    refresh it ourselves and write the rotation back into Claude Code's live
    credentials — closing the only window in which a sub could expire.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("cc")

_CC_ACCT_PATH = Path(__file__).resolve().parent.parent / "cc-accounts" / "cc-acct"


def _load_cc_acct():
    """Import the extensionless cc-acct script as a module."""
    loader = importlib.machinery.SourceFileLoader("cc_acct", str(_CC_ACCT_PATH))
    spec = importlib.util.spec_from_loader("cc_acct", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class ClaudeSubsService:
    # Refresh a non-active token once it has less than this much life left.
    # Access tokens last ~8h, so 45 min of headroom means we rotate them long
    # before Anthropic would ever reject them — they can't lapse between passes.
    REFRESH_HEADROOM_SECONDS = 45 * 60

    # Auto-switch tuning.
    AUTOSWITCH_THRESHOLD = 0.95   # switch when active 5h utilization >= this
    AUTOSWITCH_COOLDOWN = 60      # min seconds between auto-switches (anti-flap)

    def __init__(self):
        self._mod = None
        self._lock = threading.Lock()
        # Last good payload, served instantly on connect without a network probe.
        self._cache = {"available": False, "reason": "not scanned yet", "accounts": []}
        # Auto-switch state machine (see evaluate_autoswitch).
        self._auto = {
            "last_switch": 0.0,       # epoch of last auto-switch (cooldown)
            "waiting": False,         # True when limited but no candidate free
            "prev_available": set(),  # account names that were 'ok' last cycle
        }
        try:
            if _CC_ACCT_PATH.exists():
                self._mod = _load_cc_acct()
        except Exception as exc:  # malformed script / import error
            self._cache = {"available": False, "reason": f"cc-acct load failed: {exc}", "accounts": []}

    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        return self._mod is not None

    def get_cached(self) -> dict:
        return self._cache

    # ------------------------------------------------------------------ #
    def _is_active(self, m, profile: dict) -> bool:
        """Is this saved profile the account currently live in Claude Code?

        Prefer a stable identity match over the token match the CLI uses,
        because tokens rotate — a freshly rotated active token would otherwise
        momentarily look "not active" and tempt us into refreshing it.

        Identity = (accountUuid, organizationUuid). Both are needed: the same
        login can belong to several orgs (e.g. two saved profiles with one
        email), and only the org pins down which subscription is active.
        """
        try:
            cur = m.read_current_account() or {}
            cur_id = (cur.get("accountUuid"), cur.get("organizationUuid"))
            oa = profile.get("oauthAccount", {}) or {}
            mine = (
                profile.get("accountUuid") or oa.get("accountUuid"),
                profile.get("organizationUuid") or oa.get("organizationUuid"),
            )
            if all(cur_id) and all(mine):
                return cur_id == mine
        except Exception:
            pass
        # Fall back to the CLI's token-based check.
        return bool(m.is_active(profile))

    def _sync_active_from_claude(self, m, name: str, profile: dict) -> dict:
        """Pull Claude Code's live tokens into our stored snapshot.

        Claude Code owns the active account's refresh chain; we just mirror its
        latest rotation so our copy never goes stale. We never POST a refresh
        for this account, so we can't clash with Claude Code.

        Defence in depth: re-verify the live account identity matches THIS
        profile before overwriting. A mis-detection must never clobber the
        wrong profile's tokens (this exact bug corrupted a profile once).
        """
        try:
            cur_acct = m.read_current_account() or {}
            cur_id = (cur_acct.get("accountUuid"), cur_acct.get("organizationUuid"))
            oa = profile.get("oauthAccount", {}) or {}
            mine = (
                profile.get("accountUuid") or oa.get("accountUuid"),
                profile.get("organizationUuid") or oa.get("organizationUuid"),
            )
            if all(cur_id) and all(mine) and cur_id != mine:
                logger.warning(f"claude-subs: refusing to sync '{name}' — live "
                               f"account identity does not match this profile")
                return profile
        except Exception:
            return profile

        try:
            oauth = m.read_current_oauth()
        except SystemExit:
            return profile  # credentials file missing — leave snapshot as-is
        except Exception:
            return profile

        cur_access = oauth.get("accessToken")
        if cur_access and cur_access != profile.get("accessToken"):
            profile["accessToken"] = cur_access
            profile["refreshToken"] = oauth.get("refreshToken", profile.get("refreshToken"))
            profile["expiresAt"] = oauth.get("expiresAt", profile.get("expiresAt"))
            if oauth.get("scopes"):
                profile["scopes"] = oauth["scopes"]
            profile["syncedAt"] = datetime.now(timezone.utc).isoformat()
            try:
                m.write_json_secure(m.profile_path(name), profile)
                logger.info(f"claude-subs: synced active account '{name}' from Claude Code")
            except Exception as exc:
                logger.warning(f"claude-subs: could not persist sync for '{name}': {exc}")
        return profile

    def _keep_alive(self, m, name: str, profile: dict, active: bool) -> tuple[dict, str | None]:
        """Ensure this account's token stays valid. Returns (profile, error).

        Active  -> mirror Claude Code's tokens; if it's about to expire and
                   Claude Code has NOT rotated it (it's idle), refresh it
                   ourselves as a fallback so an idle active account can't lapse.
        Others  -> proactively refresh while there's still plenty of headroom,
                   persisting the rotated single-use refresh token.
        """
        if active:
            profile = self._sync_active_from_claude(m, name, profile)

            # Safety net for an IDLE active account. Claude Code only rotates a
            # token while it's making API calls; if the active account just sits
            # there (e.g. parked here by auto-switch) nobody refreshes it and it
            # expires — exactly the lapse that forces a re-login. So if it's
            # near expiry AND the live refresh token still matches our snapshot
            # (proof Claude Code hasn't rotated it out from under us), we refresh
            # it ourselves and write the rotation straight back into Claude
            # Code's live credentials so the two never diverge.
            expires_at_ms = profile.get("expiresAt") or 0
            seconds_left = expires_at_ms / 1000 - time.time()
            if seconds_left > self.REFRESH_HEADROOM_SECONDS:
                return profile, None  # plenty of life left, leave it to CC

            try:
                live = m.read_current_oauth()
            except Exception:
                return profile, None  # can't verify — stay hands-off
            live_refresh = live.get("refreshToken")
            if not live_refresh or live_refresh != profile.get("refreshToken"):
                # Claude Code already rotated it; our sync above tracks that.
                return profile, None

            try:
                tok = m.oauth_refresh(profile["refreshToken"])
                profile["accessToken"] = tok["access_token"]
                profile["refreshToken"] = tok.get("refresh_token", profile["refreshToken"])
                profile["expiresAt"] = int((time.time() + tok.get("expires_in", 28800)) * 1000)
                if "scope" in tok:
                    profile["scopes"] = tok["scope"].split()
                profile["refreshedAt"] = datetime.now(timezone.utc).isoformat()
                m.write_json_secure(m.profile_path(name), profile)
                # Push the rotation into Claude Code's live creds so it keeps
                # using the same (now-valid) chain instead of the dead token.
                m.write_current_oauth(m.profile_to_oauth(profile))
                logger.info(f"claude-subs: refreshed IDLE active account '{name}' "
                            f"({int(seconds_left/60)}m of life remained)")
            except Exception as exc:
                logger.warning(f"claude-subs: idle-active refresh failed for '{name}': {exc}")
                return profile, f"token refresh failed: {exc}"
            return profile, None

        # Safety: never refresh a non-active profile whose refresh token is the
        # SAME as the live Claude Code account's. That means this profile points
        # at the active account (e.g. a duplicate or a corrupted file), and
        # rotating it would invalidate the active account → forced re-login.
        try:
            live = m.read_current_oauth()
            if live.get("refreshToken") and live["refreshToken"] == profile.get("refreshToken"):
                logger.warning(f"claude-subs: skipping refresh of '{name}' — its token "
                               f"matches the active account (profile needs re-saving)")
                return profile, "shares the active account's token — re-login and re-save"
        except Exception:
            pass

        expires_at_ms = profile.get("expiresAt") or 0
        seconds_left = expires_at_ms / 1000 - time.time()
        if seconds_left > self.REFRESH_HEADROOM_SECONDS:
            return profile, None  # still fresh enough, nothing to do

        try:
            tok = m.oauth_refresh(profile["refreshToken"])
            profile["accessToken"] = tok["access_token"]
            profile["refreshToken"] = tok.get("refresh_token", profile["refreshToken"])
            profile["expiresAt"] = int((time.time() + tok.get("expires_in", 28800)) * 1000)
            if "scope" in tok:
                profile["scopes"] = tok["scope"].split()
            profile["refreshedAt"] = datetime.now(timezone.utc).isoformat()
            m.write_json_secure(m.profile_path(name), profile)
            logger.info(f"claude-subs: proactively refreshed '{name}' "
                        f"({int(seconds_left/60)}m of life remained)")
            return profile, None
        except Exception as exc:
            logger.warning(f"claude-subs: refresh failed for '{name}': {exc}")
            return profile, f"token refresh failed: {exc}"

    # ------------------------------------------------------------------ #
    def keep_alive_all(self) -> int:
        """Token maintenance only — no usage-consuming API probe.

        Cheap and safe to call often: refreshes non-active tokens that are
        nearing expiry (OAuth token endpoint, not a usage call) and mirrors the
        active account from Claude Code. Returns how many accounts were touched.
        """
        m = self._mod
        if m is None:
            return 0
        touched = 0
        with self._lock:
            try:
                names = m.list_profiles()
            except Exception as exc:
                logger.warning(f"claude-subs keep_alive_all: {exc}")
                return 0
            for name in names:
                try:
                    p = m.load_profile(name)
                except SystemExit:
                    continue
                active = self._is_active(m, p)
                before = p.get("accessToken")
                p, _err = self._keep_alive(m, name, p, active)
                if p.get("accessToken") != before:
                    touched += 1
        return touched

    # ------------------------------------------------------------------ #
    def probe_active(self) -> dict:
        """Probe ONLY the currently-active account and merge it into the cache.

        Cheap, frequent refresh for the one account whose usage is actually
        moving (the live Claude Code account). Leaves the other accounts'
        last-known data untouched so the UI keeps their colours/countdowns.
        Returns the full (merged) cached payload.
        """
        m = self._mod
        if m is None:
            return self._cache
        with self._lock:
            try:
                names = m.list_profiles()
            except Exception as exc:
                logger.warning(f"claude-subs probe_active: {exc}")
                return self._cache

            # Find the active profile by stable identity.
            active_name = None
            for name in names:
                try:
                    p = m.load_profile(name)
                except SystemExit:
                    continue
                if self._is_active(m, p):
                    active_name = name
                    break
            if active_name is None:
                return self._cache

            fresh = self._status_for(m, active_name, probe=True)

            # Merge into cache: replace just the active account's entry. If the
            # cache has no accounts yet, build the full list once (inline, since
            # we already hold the lock — don't re-enter get_status).
            accounts = (self._cache.get("accounts") or [])
            if not accounts:
                accounts = [
                    fresh if n == active_name else self._status_for(m, n, probe=True)
                    for n in names
                ]
                payload = {"available": True, "reason": None, "accounts": accounts}
                self._cache = payload
                return payload
            merged = [fresh if a.get("name") == active_name else a for a in accounts]
            payload = {"available": True, "reason": None, "accounts": merged}
            self._cache = payload
            return payload

    # ------------------------------------------------------------------ #
    def get_status(self, probe: bool = True) -> dict:
        """Full status for every saved account.

        When ``probe`` is True we hit Anthropic's API (1 tiny token request per
        account) to read live rate-limit headers; otherwise we report identity
        + token expiry only. Tokens near expiry are refreshed regardless.
        """
        m = self._mod
        if m is None:
            return {"available": False, "reason": "cc-acct not found", "accounts": []}

        with self._lock:
            try:
                names = m.list_profiles()
            except Exception as exc:
                payload = {"available": False, "reason": str(exc), "accounts": []}
                self._cache = payload
                return payload

            if not names:
                payload = {"available": True, "reason": "no saved accounts", "accounts": []}
                self._cache = payload
                return payload

            accounts = [self._status_for(m, name, probe=probe) for name in names]
            payload = {"available": True, "reason": None, "accounts": accounts}
            self._cache = payload
            return payload

    # ------------------------------------------------------------------ #
    def _status_for(self, m, name: str, probe: bool) -> dict:
        try:
            p = m.load_profile(name)
        except SystemExit as exc:
            return {"name": name, "state": "error", "error": str(exc), "windows": {}}

        active = self._is_active(m, p)
        email = p.get("emailAddress") or "(unknown)"
        org = m.org_name(p)
        plan = p.get("subscriptionType") or "?"

        base = {
            "name": name,
            "email": email,
            "org": org,
            "plan": plan,
            "active": active,
            "token_expires": (p.get("expiresAt") or 0) / 1000 or None,
            "windows": {},
            "ok_again": None,
            "error": None,
        }

        # Smart keep-alive: refresh non-active tokens early, mirror the active
        # one from Claude Code. This is what stops subs from ever expiring.
        p, keep_err = self._keep_alive(m, name, p, active)
        base["token_expires"] = (p.get("expiresAt") or 0) / 1000 or None
        if keep_err:
            base["state"] = "error"
            base["error"] = keep_err
            return base

        if not probe:
            base["state"] = "unknown"
            return base

        rl = m.probe_rate_limit(p["accessToken"])

        # A 401 on a not-yet-expired token → it was invalidated server-side.
        # Only self-heal via a forced refresh for NON-active accounts; doing so
        # for the active one risks clashing with Claude Code's own refresh.
        if isinstance(rl, dict) and str(rl.get("error", "")).startswith("HTTP 401"):
            if active:
                p = self._sync_active_from_claude(m, name, p)
                base["token_expires"] = (p.get("expiresAt") or 0) / 1000 or None
                rl = m.probe_rate_limit(p["accessToken"])
            else:
                try:
                    tok = m.oauth_refresh(p["refreshToken"])
                    p["accessToken"] = tok["access_token"]
                    p["refreshToken"] = tok.get("refresh_token", p["refreshToken"])
                    p["expiresAt"] = int((time.time() + tok.get("expires_in", 28800)) * 1000)
                    if "scope" in tok:
                        p["scopes"] = tok["scope"].split()
                    m.write_json_secure(m.profile_path(name), p)
                    base["token_expires"] = (p.get("expiresAt") or 0) / 1000 or None
                    rl = m.probe_rate_limit(p["accessToken"])
                except Exception as exc:
                    rl = {"error": f"401 then refresh failed: {exc}"}

        if "error" in rl:
            base["state"] = "error"
            base["error"] = rl["error"]
            return base

        windows = {}
        for win, label in (("5h", "5-hour"), ("7d", "weekly")):
            d = rl.get(win, {}) or {}
            windows[win] = {
                "label": label,
                "status": d.get("status") or "?",
                "utilization": d.get("utilization"),
                "reset": d.get("reset"),
            }
        base["windows"] = windows

        overall = rl.get("overall")
        # A card is only truly LIMITED when a window is actually `rejected`
        # (or the overall status is an explicit rejection). Anthropic also emits
        # `allowed_warning` — that's a "you're getting close" heads-up, NOT a
        # block: the account is fully usable. Treating anything != "allowed" as
        # limited (the old check) wrongly turned warned-but-usable accounts red.
        # `overage_reason` is a persistent header that is present even while
        # allowed (e.g. a healthy account can still report org_level_disabled),
        # so it must NOT be used to decide limited state.
        rejected_windows = [
            w for w in ("5h", "7d")
            if windows.get(w, {}).get("status") == "rejected"
        ]
        limited = bool(rejected_windows) or overall == "rejected"
        warning = (not limited) and overall == "allowed_warning"
        if limited:
            blocking = [
                windows[w]["reset"]
                for w in rejected_windows
                if windows[w].get("reset")
            ]
            base["ok_again"] = min(blocking) if blocking else None
            base["overage_reason"] = rl.get("overage_reason")
        if limited:
            base["state"] = "limited"
        elif warning:
            # Usable, but near a window limit — surface as a soft warning so the
            # UI can show amber instead of green/red. Carry the reason for info.
            base["state"] = "warning"
            base["overage_reason"] = rl.get("overage_reason")
        else:
            base["state"] = "ok"
        return base

    # ------------------------------------------------------------------ #
    def refresh_active_flags(self) -> dict:
        """Recompute only the ``active`` flag on the cached payload.

        Used right after a switch: we want the UI to move the "active" marker
        immediately WITHOUT wiping the last-known usage colours/windows (a bare
        probe=False refresh would blank every card to grey until the next probe).
        """
        m = self._mod
        cache = self._cache
        if m is None or not cache.get("accounts"):
            return cache
        try:
            for acct in cache["accounts"]:
                try:
                    p = m.load_profile(acct["name"])
                except SystemExit:
                    continue
                acct["active"] = self._is_active(m, p)
        except Exception as exc:
            logger.warning(f"claude-subs refresh_active_flags: {exc}")
        return cache

    # ------------------------------------------------------------------ #
    @staticmethod
    def _account_ready(acct: dict) -> bool:
        """True if an account is usable right now (not rate-limited / errored).

        Usable = state 'ok' or 'warning' (a warning is just "near a limit", the
        account still works), and its 5h window isn't rejected.
        """
        if acct.get("state") not in ("ok", "warning"):
            return False
        win = (acct.get("windows") or {}).get("5h") or {}
        return win.get("status") != "rejected"

    @staticmethod
    def _util_5h(acct: dict) -> float:
        win = (acct.get("windows") or {}).get("5h") or {}
        u = win.get("utilization")
        return u if u is not None else 0.0

    def evaluate_autoswitch(self, enabled: bool) -> dict | None:
        """Decide whether to auto-switch, based on the current cached status.

        Returns an event dict to broadcast, or None if nothing happened:
          {"action": "switched", "from", "to", "reason"}
          {"action": "waiting", "from"}      — limited, no candidate available
          {"action": "ready", "names": [...]} — a sub became usable while waiting

        Caller (the polling thread) should run this once per cycle after the
        status cache is fresh, and emit the returned event over socket.io.
        """
        m = self._mod
        if m is None:
            return None

        accounts = (self._cache.get("accounts") or [])
        if not accounts:
            return None

        active = next((a for a in accounts if a.get("active")), None)
        others = [a for a in accounts if not a.get("active")]
        ready_others = [a for a in others if self._account_ready(a)]

        # ---- "ready" notification: a sub became usable while we were waiting,
        # or the active one is exhausted and something else is free. We surface
        # this regardless of the enabled flag so the user gets notified to start
        # manually, but only when it's actionable (active is low/limited).
        active_low = bool(active) and (
            active.get("state") == "limited"
            or self._util_5h(active) >= self.AUTOSWITCH_THRESHOLD
        )

        now = time.time()
        prev_ready = self._auto["prev_available"]
        cur_ready = {a["name"] for a in ready_others}
        newly_ready = cur_ready - prev_ready
        self._auto["prev_available"] = cur_ready

        # ---- AUTO ENABLED: try to switch when the active account is low/limited.
        if enabled and active_low and ready_others:
            if now - self._auto["last_switch"] < self.AUTOSWITCH_COOLDOWN:
                return None  # within cooldown, hold
            # Pick the candidate with the most headroom (lowest 5h utilization).
            target = min(ready_others, key=self._util_5h)
            res = self.switch(target["name"])
            if res.get("ok"):
                self._auto["last_switch"] = now
                self._auto["waiting"] = False
                reason = ("limit reached" if active.get("state") == "limited"
                          else f"usage {int(self._util_5h(active)*100)}%")
                return {
                    "action": "switched",
                    "from": active.get("name"),
                    "to": target["name"],
                    "reason": reason,
                }
            # switch failed → fall through to waiting/none handling.

        # ---- No candidate available while the active one is spent.
        if active_low and not ready_others:
            already_waiting = self._auto["waiting"]
            self._auto["waiting"] = True
            if not already_waiting:
                return {"action": "waiting", "from": active.get("name")}
            return None

        # ---- We were waiting and now something is free → notify (manual start).
        if self._auto["waiting"] and newly_ready:
            self._auto["waiting"] = False
            return {"action": "ready", "names": sorted(newly_ready)}

        # ---- Active is healthy again; clear waiting silently.
        if not active_low:
            self._auto["waiting"] = False

        # ---- Even when not formally "waiting": if active is low and a sub just
        # became ready (e.g. its reset passed), tell the user it's available.
        if active_low and newly_ready and not enabled:
            return {"action": "ready", "names": sorted(newly_ready)}

        return None

    # ------------------------------------------------------------------ #
    def _capture_outgoing(self, m) -> None:
        """Before switching away, persist the live tokens into whichever saved
        profile is currently active.

        This closes the chain-corruption bug that forced a re-login: a switch
        overwrites the live credentials, but if we never captured Claude Code's
        latest rotation of the OUTGOING account, that profile keeps a stale,
        already-rotated refresh token. The next switch back writes that dead
        token into the live creds → invalid_grant → forced re-login. Capturing
        here keeps every profile's chain head current no matter how we switch.
        """
        try:
            live = m.read_current_oauth()
        except Exception:
            return  # no live creds to capture (nothing active yet)
        live_access = live.get("accessToken")
        if not live_access:
            return
        try:
            names = m.list_profiles()
        except Exception:
            return
        for name in names:
            try:
                p = m.load_profile(name)
            except SystemExit:
                continue
            # The active profile is the one whose tokens equal the live creds.
            if not self._is_active(m, p):
                continue
            if p.get("accessToken") == live_access:
                return  # already current, nothing to persist
            p["accessToken"] = live_access
            p["refreshToken"] = live.get("refreshToken", p.get("refreshToken"))
            p["expiresAt"] = live.get("expiresAt", p.get("expiresAt"))
            if live.get("scopes"):
                p["scopes"] = live["scopes"]
            p["syncedAt"] = datetime.now(timezone.utc).isoformat()
            try:
                m.write_json_secure(m.profile_path(name), p)
                logger.info(f"claude-subs: captured outgoing account '{name}' "
                            f"before switch (chain kept current)")
            except Exception as exc:
                logger.warning(f"claude-subs: could not capture outgoing '{name}': {exc}")
            return

    def switch(self, name: str) -> dict:
        """Make ``name`` the active Claude Code account (backs up current first).

        Hardened against credential-chain corruption:
          1. Capture the OUTGOING account's live token into its profile first,
             so its single-use refresh chain head never goes stale.
          2. Refresh + validate the INCOMING token before committing — never
             write a token we can't prove is fresh into the live credentials.
          3. If the live write half-fails, restore the backup so Claude Code is
             never left wedged with partial credentials.
        """
        m = self._mod
        if m is None:
            return {"ok": False, "error": "cc-acct not found"}

        with self._lock:
            try:
                p = m.load_profile(name)
            except SystemExit as exc:
                return {"ok": False, "error": str(exc)}

            if self._is_active(m, p):
                return {"ok": True, "already_active": True, "name": name,
                        "email": p.get("emailAddress")}

            # (1) Preserve the outgoing account's latest rotation before we
            # clobber the live credentials. This is what stops a later
            # switch-back from replaying a dead token.
            self._capture_outgoing(m)

            # (2) Ensure the incoming token is fresh AND valid. ensure_fresh
            # refreshes if near expiry and persists the rotation back to the
            # profile, so we never hand Claude Code an expired/expiring token.
            try:
                p = m.ensure_fresh(name, p)
            except Exception as exc:
                return {"ok": False, "error": f"cannot switch: {exc}",
                        "hint": f"re-login to '{name}' in Claude Code then: cc-acct save {name}"}

            if not p.get("accessToken"):
                return {"ok": False, "error": "profile has no access token",
                        "hint": f"re-login to '{name}' in Claude Code then: cc-acct save {name}"}

            # (3) Commit, with rollback if the write half-fails.
            backup = None
            try:
                backup = m.backup_credentials()
                m.write_current_oauth(m.profile_to_oauth(p))
                if p.get("oauthAccount"):
                    m.write_current_account(p["oauthAccount"])
            except Exception as exc:
                # Restore the pre-switch credentials so Claude Code isn't left
                # with a half-written / inconsistent token.
                restored = False
                try:
                    if backup and Path(str(backup)).exists():
                        data = m.read_json(Path(str(backup)))
                        if data.get("claudeAiOauth"):
                            m.write_current_oauth(data["claudeAiOauth"])
                            restored = True
                except Exception as rexc:
                    logger.error(f"claude-subs: switch rollback FAILED for '{name}': {rexc}")
                return {"ok": False,
                        "error": f"switch failed: {exc}"
                                 + ("" if restored else " (and rollback failed — check ~/.claude)"),
                        "rolled_back": restored}

            return {
                "ok": True,
                "name": name,
                "email": p.get("emailAddress"),
                "backup": str(backup),
                "note": "restart Claude Code (or open a new session) to pick up the new account",
            }
