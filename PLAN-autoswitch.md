# Task: Auto-switch Claude sub on low usage + resume the chat

Status: DONE (shipped 2026-06-04) — verified working
Owner: thjo
Created: 2026-06-03

## Outcome
Built and confirmed working:
- AUTO toggle on the CLAUDE SUBS card (persisted via /api/claude-subs/autoswitch).
- When ON and the active account hits >=95% (or is limited), the server
  auto-switches to the healthiest free sub; the live chat continues by itself
  (no resume/restart needed — verified by user test).
- When no sub is available: a persistent red notice in the card ("none
  available, start manually") + a browser/OS notification.
- When a sub becomes ready again: green notice + browser notification. With AUTO
  on it switches immediately; with AUTO off it just notifies you to start.
- 10s active-account probe, 60s full sweep, 5min token keep-alive (unchanged).
- Anti-flap cooldown (60s) between auto-switches.

Files: services/claude_subs.py (evaluate_autoswitch + state machine),
server.py (/api/claude-subs/autoswitch, thread wiring + claude_subs_auto emit),
templates/index.html (AUTO button, notice banner, browser notifications).

## Original research notes (kept for reference)


## Goal
When the active Claude subscription runs low on usage, automatically switch the
active account to a healthy sub, and resume/reload the conversation that was
using it so work continues uninterrupted.

## Two halves
- **A) Auto-switch** — detect low usage on the active account, pick a healthy
  candidate, switch credentials safely.
- **B) Resume the chat** — restart the affected panel's Claude process under the
  new account, resuming the same conversation (`--resume <id>` / `--continue`).

## Design sketch (from discussion)
- Trigger: threshold-based on active account's 5h utilization (e.g. 90%) with
  hysteresis + cooldown. Reactive-on-`limited` is the fallback but worse UX.
- Candidate: lowest-utilization `state: "ok"` profile, not rate-limited.
  Tiebreak by reset headroom or a user priority order.
- Guardrails: cooldown, never switch if no healthy candidate, hard toggle
  defaulting OFF (touches live creds + restarts agents).
- CRITICAL ordering (ties to the token-corruption bug): quiesce the running
  agent FIRST → switch credentials → respawn with `--resume`. Never switch
  while a Claude process is mid-flight (token rotation clash).

## Open questions to settle before building
1. Can a conversation created under account A be `--resume`d under account B?
   (Local history vs per-account/org server state.) Needs manual experiment.
2. Do/can we capture the Claude session ID when a panel spawns Claude?
3. Scope: v1 = auto-switch + loud notify (no resume); v2 = add resume once proven.

## Research findings (2026-06-03)

### BREAKTHROUGH (user-verified by live test)
A running Claude Code session **picks up swapped credentials mid-chat and
continues automatically** — NO `--resume`, NO process restart, NO kill/respawn.
User tested: hit low/limit, swapped the active account via our switch(), and the
in-progress chat just continued on the new sub.

=> Part B ("resume the chat") is ELIMINATED. The feature collapses to:
   **detect low usage on active account → call switch() to a healthy sub → done.**
   The conversation continues itself.

This means we do NOT need any of:
   - session-ID capture per panel
   - the quiesce → switch → respawn-with-resume ordering
   - the "can a conversation resume under a different account?" experiment

### How Claude Code stores sessions (for reference, no longer on critical path)
- `~/.claude/sessions/<pid>.json` maps a running Claude **pid → sessionId, cwd,
  status, version**. (Useful later if we ever want per-panel awareness.)
- `~/.claude/projects/<slug>/<sessionId>.jsonl` is the full conversation log per
  project, named by session id. `claude --resume <id>` / `--continue` use these.
- Credentials live in `~/.claude/.credentials.json` (claudeAiOauth block); the
  identity is in `~/.claude.json` (oauthAccount). Our switch() writes both.

### Corroborating prior art (others doing account-swap on limit)
- claude-revolver (Rust): stores named credential sets, monitors usage via the
  OAuth API, swaps accounts when thresholds reached. Same model as ours.
- coding_agent_account_manager / caam (Go): "sub-100ms auth switching", swap on
  limit. Confirms credential-file swap is the accepted technique.
- claude-swap, ccs: more of the same.
- These validate the approach AND that swapping creds is safe/expected.

### Important caveats found in Claude Code issues (keep in mind)
- Config files (settings.json, CLAUDE.md) need a restart to take effect, but
  CREDENTIALS are re-read live — consistent with the user's successful test.
- Issue #12786: rate limits can be incorrectly cross-applied between two Max
  accounts on the same device. Watch for: after swap, the new account might
  still briefly report the old one's limit. May need a short grace period.
- Issue #24317 / #9903: OAuth refresh-token RACE when multiple sessions refresh
  the same account (this is exactly the bug that corrupted borsen-d3). Our
  identity-pair + duplicate-token guards already address this; keep them.

## Revised design (much simpler)
1. In claude_subs_thread, on each active probe (10s) check the active account's
   utilization/status.
2. If active >= threshold (e.g. 90%) OR state == limited:
   - pick healthiest candidate (lowest 5h util, state ok, not limited),
   - call claude_subs_service.switch(candidate),
   - emit a loud event-log line + UI toast.
3. Guardrails: on/off toggle (default off), cooldown between switches (avoid
   flap), do nothing if no healthy candidate, respect a possible post-switch
   grace period for the cross-account-limit quirk (#12786).
4. No resume logic needed — the live session continues on the new creds.

## How the limit / reset window works (researched + confirmed against our data)

**The 5-hour window is a ROLLING window that starts with your FIRST message,
and resets exactly 5 hours after that first message** — NOT when you hit 100%,
and NOT on a fixed wall clock.

Sequence:
1. Account is idle, no active window.
2. You send the first message -> the 5h clock STARTS now. Reset = now + 5h.
3. You use it through that window. The % (utilization) climbs toward 100%.
4. If you hit 100% before the 5h is up -> you're rejected/limited until the
   reset (which was fixed at first-message-time; it does NOT extend).
5. At reset, the window clears and the NEXT message starts a fresh 5h clock.

So the countdown to reset is anchored to first use, independent of when (or
whether) you hit 100%. Hitting 100% just means "blocked early"; reset doesn't move.

Proof from our own probe (captured 08:32 CEST, all three at ~100%+):
   borsen    5h reset 08:40  (first msg ~03:40)
   borsen-d3 5h reset 09:20  (first msg ~04:20)
   roel      5h reset 12:10  (first msg ~07:10)
Three different reset times -> confirms per-account rolling window from first
use, not a shared/fixed clock.

The weekly (7d) window is the same idea over 7 days, across all models.

Sources (rephrased for compliance):
- allthings.how "Claude Code usage limits explained": the 5-hour session limit
  is a rolling window that starts with your first message and resets five hours
  later; the weekly limit spans seven days across all models.
- Anthropic support "Understanding usage and length limits": usage limits are a
  time-boxed "conversation budget" you spend down until reset.

### What this means for auto-switch
- The `reset` epoch we already read per window = the moment that account becomes
  usable again. Trust it directly.
- "Healthiest candidate" = an account whose 5h window is NOT rejected. Among
  those, prefer lowest utilization (most headroom).
- NUANCE: switching TO an idle account STARTS its 5h clock on the first message.
  So switching early/often lights up fresh windows on multiple accounts. Choice:
    * conservative: only switch when active is actually rejected; pick an account
      already open or past its reset.
    * aggressive: switch at ~90% to a fresh account for uninterrupted flow,
      accepting we start its 5h clock.
- Reset times don't extend, so once an account passes its `reset` epoch it's
  fully back -> we can rotate back to it.

## Still worth a quick check before building
- Confirm swap-continue holds MID-RESPONSE vs idle at the prompt (user verified
  one; verify the other).
- Decide threshold + cooldown defaults + conservative vs aggressive strategy.
- Where the toggle lives (subs card header) + persistence.
