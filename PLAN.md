# COMMANDCENTER - COMPREHENSIVE PLAN

## ALL ISSUES FOUND (Including Security!)

---

## 🔴 CRITICAL (Crashes/Data Loss)

### 1. active_projects ONLY TRACKS 2 PANELS
**File:** `server.py:44`
```python
active_projects = {0: None, 1: None}  # Panel 2 is NEVER tracked!
```
Git thread silently ignores panel 2 forever. If you open 3 panels, the 3rd one never gets git status updates.
**Fix:** Change to `{0: None, 1: None, 2: None}`

### 2. Git ahead/behind fails silently with no upstream
**File:** `server.py:220-224`
```python
rev_list = run(["git", "rev-list", "--left-right", "--count", f"{branch}...@{{u}}"])
if rev_list: ...  # Returns "" if no upstream
```
User sees "--" instead of "no upstream" message. Confusing state.
**Fix:** Check if upstream exists, show proper message

### 3. JSON.parse crash with no fallback
**File:** `templates/index.html:2213`
```javascript
return JSON.parse(raw);  # App crashes if localStorage corrupted
```
No try-catch around loadSettings. Malformed data = entire app dead.
**Fix:** Wrap in try-catch, return null on error

### 4. Session name has NO sanitization
**File:** `server.py:735-736`
```python
session = f"cc-{project_name or 'panel'}-{panel}-{agent_cmd}"
```
Project name "my project" creates invalid tmux session "cc-my project-0-claude". tmux will reject or behave unpredictably.
**Fix:** Sanitize to `re.sub(r'[^a-zA-Z0-9_-]', '', session)`

### 5. on_data silently swallows ALL exceptions
**File:** `server.py:771-780`
```python
try:
    scan_pty_signals(_sid, _panel, chunk)
except Exception:
    pass
```
Real errors vanish. Debugging impossible. User sees no feedback.
**Fix:** Log errors properly, don't silently swallow

---

## 🟠 MAJOR (Wrong Behavior/Broken Features)

### 6. NEVER_USED_FINGERPRINTS are wrong for Claude Code
**File:** `server.py:565-569`
```python
NEVER_USED_FINGERPRINTS = (
    "sign in with chatgpt",
    "sign in with device code",
    "welcome to codex",
)
```
Claude Code shows different text. Auto-close almost never triggers for Claude.
**Fix:** Add Claude-specific fingerprints like "claude code v" or "sign in with anthropic"

### 7. tmux_janitor uses WRONG idle detection
**File:** `server.py:587-642`
```python
idle = now - int(act)  # Uses tmux SESSION ACTIVITY TIME
```
tmux activity = ANY keypress in ANY pane. User could be using session for bash, yet janitor thinks "idle agent" and kills it.
**Fix:** Use pane content fingerprint + session creation time, not activity

### 8. showTermIfReady doesn't check if DOM is detached
**File:** `templates/index.html:2343`
```javascript
try { t.fit.fit(); } catch (e) {}  # Silently fails, terminal invisible
```
If panel is hidden (data-hidden="1"), fit() fails but no retry mechanism. Terminal stays in loading state forever.
**Fix:** Check if DOM is visible before fit, retry when visible

### 9. Splitter drag breaks on window resize
**File:** `templates/index.html:2425-2454`
```javascript
const rect = panel.getBoundingClientRect();  # Cached at drag start
```
If window resizes during drag, rect is stale. Elements can overlap or vanish.
**Fix:** Recalculate rect on resize event during drag

### 10. scan_pty_signals has NO synchronization
**File:** `server.py:411-457`
Multiple concurrent socket.io events can call this simultaneously. No lock. Could emit duplicate events.
**Fix:** Add threading.Lock for scan_pty_signals

### 11. panel_awaiting emits to WRONG socket
**File:** `server.py:419`
```python
socketio.emit("panel_awaiting", {"panel": panel, "awaiting": True}, to=sid)
```
If multiple tabs open, only THAT tab sees the awaiting pulse. Other tabs show no indication.
**Fix:** Broadcast to all or track per-sid state

### 12. tmux_janitor ONLY matches prefix "cc-"
**File:** `server.py:586-642`
Could match sessions we didn't spawn that happen to start with "cc-".
**Fix:** Add timestamp or UUID to session names for uniqueness

---

## 🟡 MODERATE (Confusing UX/Edge Cases)

### 13. Weather emits 10 times in 30s then waits 5 minutes
**File:** `server.py:547-549`
Rapid weather updates then nothing. If you connect late, you get old data for 5 minutes.
**Fix:** Start with last cached value, then emit every 60s

### 14. Metrics use random stagger that doesn't actually help
**File:** `server.py:489`
```python
gevent.sleep(2 + random.random() * 0.5)
```
All threads use similar random. Not truly staggered. Could bunch up.
**Fix:** Use fixed offsets per thread (e.g., 2.0, 2.5, 3.0, 3.5, 4.0)

### 15. Socket.IO logger disabled, no fallback
**File:** `server.py:32`
```python
socketio = SocketIO(app, ..., logger=False, engineio_logger=False)
```
If Socket.IO has issues, they're invisible. User sees stuck terminals with no diagnostic info.
**Fix:** Enable engineio_logger, add custom error handler

### 16. winClose does nothing
**File:** `templates/index.html:2116-2120`
Browsers block `window.close()` unless opened by JS. This button is dead UI.
**Fix:** Remove or replace with "minimize to tray" or similar

### 17. Two overlay click handlers could conflict
**File:** `templates/index.html:2650-2656`
Both close on overlay click but different behaviors. Could get weird state.
**Fix:** Add debounce or unified overlay manager

### 18. subprocess text mode could fail on non-UTF8
**File:** `services/git.py:7-10`
Git branch names with emoji or non-ASCII could cause UnicodeDecodeError. No handling.
**Fix:** Add errors='replace' to subprocess calls

### 19. Config path doesn't resolve symlinks
**File:** `agents/switcher.py:16-17`
If file is symlink, os.path.dirname gives wrong directory.
**Fix:** Use os.path.realpath() to resolve symlinks

### 20. Panel 3 defaults to wrong agent
**File:** `templates/index.html:2080-2081`
```javascript
{ id: 2, agentIdx: 1, ... }  # agentIdx=1 (claude) but no project!
```
Creates orphan state.
**Fix:** Set agentIdx to 0 (opencode) or null initially

---

## 🟢 MINOR (Polish/Edge Cases)

### 21. Hardcoded SPARK_LEN = 24
**File:** `templates/index.html:2032`
Magic number not defined as constant.
**Fix:** Define as constant at top of script

### 22. tmux.is_available() called on every janitor cycle
**File:** `server.py:603`
Should cache this since tmux doesn't appear/disappear during runtime.
**Fix:** Call once at startup

### 23. fnm_setup has hardcoded path
**File:** `server.py:737-758`
If fnm installed elsewhere, this silently fails. No check if fnm exists.
**Fix:** Check if fnm exists before using path

### 24. Stat value has inconsistent formatting
**File:** `templates/index.html:3193`
NET stat shows "B/s" not percentage. Misleading for maintenance.
**Fix:** Add per-stat type handling

### 25. Profile detection has 3-second timeout but no retry
**File:** `server.py:119-120`
If claude is slow, user sees "subscription" even if logged in. No indication it's still checking.
**Fix:** Show loading state, add retry logic

### 26. Add project has race condition
**File:** `templates/index.html:2723-2724`
If user changes focusedPanel in 60ms, palette opens on wrong panel.
**Fix:** Remove setTimeout delay, open immediately

### 27. Background tasks not awaited on shutdown
**File:** `server.py:922-928`
Threads just die on crash. Could leave orphaned tmux sessions.
**Fix:** Add graceful shutdown handler

---

## 🔒 SECURITY ISSUES (CRITICAL!)

### S1. NO AUTHENTICATION - Anyone can access!
**File:** `server.py` (entire app)
The app has ZERO authentication. Anyone who can reach the port can:
- Execute commands in terminals
- Access projects and their data
- View all project files through PTY
- Use AI agents to perform actions on your behalf

**THIS IS A CRITICAL VULNERABILITY IF EXPOSED ON INTERNET!**

**Fix:** Add authentication:
- API key validation
- Session cookies
- IP whitelist option

### S2. CORS WIDE OPEN
**File:** `server.py:32`
```python
socketio = SocketIO(app, ..., cors_allowed_origins="*")
```
Accepts connections from ANY origin. Combined with no auth, any website can connect and execute commands.

**Fix:** Set specific origins or add authentication

### S3. SECRET KEY IS GENERATED ON EVERY START
**File:** `server.py:27`
```python
app.config["SECRET_KEY"] = os.urandom(24)
```
Every restart invalidates all sessions. Could cause issues with WebSocket reconnects.

**Fix:** Persist secret key to file, regenerate only if missing

### S4. AWS BEARER TOKENS STORED IN PLAIN TEXT
**File:** `server.py:234`
```python
bedrock_config["env"]["AWS_BEARER_TOKEN_BEDROCK"] = token
```
AWS tokens stored in plain text in settings.json. Anyone with file access can read them.

**Fix:** Use environment variables or encrypted storage

### S5. NO RATE LIMITING ON API ENDPOINTS
**File:** `server.py` (all routes)
API endpoints have no rate limiting. Could be DoS'd or bruteforced.

**Fix:** Add Flask-Limiter for rate limiting

### S6. PROJECT PATHS EXPOSED IN API
**File:** `server.py:302-331`
`/api/dirs` and `/api/projects` expose full filesystem paths. Any authenticated user sees server directory structure.

**Fix:** Only expose what user needs to know

### S7. PTY ACCESS IS UNPROTECTED
**File:** `server.py:712-793`
`term_open`, `term_input`, `term_close` have no auth. Once connected, anyone can:
- Open new terminals
- Send input to existing terminals
- Close terminals

**Fix:** Add authentication check to all socket events

### S8. NO INPUT VALIDATION ON SOCKET EVENTS
**File:** `server.py:712-900`
```python
panel = int(data.get("panel", 0))  # No validation panel is valid!
rows = int(data.get("rows", 40))   # No validation rows is reasonable!
cols = int(data.get("cols", 120))  # No validation cols is reasonable!
```
Malicious client could send extreme values and crash the server.

**Fix:** Add input validation with reasonable bounds

### S9. ERROR MESSAGES MAY EXPOSE STACK TRACES
**File:** `server.py` (various places)
Some errors return full tracebacks in API responses.

**Fix:** Sanitize error messages, log full tracebacks server-side only

### S10. tmux session names could leak info
**File:** `server.py:735`
Session names include project name. Anyone with tmux access (or ps aux) could see project names.

**Fix:** Use hashed session names, map back internally

---

## 📋 LOGGING ISSUES

### L1. NO STRUCTURED LOGGING
**File:** `server.py` (throughout)
All logging is via `print()` statements. No structured logging, no log levels, no rotation.

**Fix:** Use Python logging module with proper handlers

### L2. ERRORS SWALLOWED SILENTLY
**File:** Multiple places
```python
except Exception:
    pass
```
Real errors vanish. Impossible to debug.

**Fix:** Log all exceptions with stack traces

### L3. NO ACCESS LOGGING
**File:** `server.py`
No logging of API requests, socket connections, etc.

**Fix:** Add access logs for all HTTP endpoints

### L4. NO AUDIT LOG FOR SECURITY EVENTS
**File:** `server.py`
Failed auth attempts, rate limit triggers, etc. not logged.

**Fix:** Add audit log for security-relevant events

### L5. METRICS THREAD ERRORS PRINT TO STDOUT
**File:** `server.py:487-488`
```python
print("metrics_thread err:", exc)
```
These should go to proper logging, not stdout.

**Fix:** Use logging module

---

## RECOMMENDED ORDER TO FIX

### Phase 1: Critical Bugs (Do First!)
1. active_projects dict (panel 3 support)
2. loadSettings JSON.parse crash
3. session name sanitization
4. showTermIfReady DOM check
5. Input validation on socket events

### Phase 2: Security (Do Second!)
1. Add authentication
2. Fix CORS
3. Add rate limiting
4. Add input validation
5. Secure token storage

### Phase 3: Major Issues (Do Third!)
1. scan_pty_signals synchronization
2. tmux_janitor detection fix
3. NEVER_USED_FINGERPRINTS update
4. git upstream detection
5. Error logging (not silent except)

### Phase 4: Polish (Do Fourth!)
1. Weather thread timing
2. Metrics stagger fix
3. Splitter drag resize
4. winClose removal/replacement
5. Graceful shutdown handler

---

## TECHNICAL DEBT

- **No tests** - 0% test coverage
- **No TypeScript** - Many type bugs possible
- **Magic numbers everywhere** - Should be constants
- **No shutdown handler** - Orphaned tmux sessions on crash
- **No error aggregation** - Silent except clauses hide all issues
- **No security testing** - Never tested for vulnerabilities

---

## VERIFICATION CHECKLIST

After fixing, verify:
- [ ] Panel 3 gets git updates
- [ ] localStorage crash doesn't break app
- [ ] Session names work with spaces in project names
- [ ] Terminal becomes visible when panel shows
- [ ] No race conditions in signal scanning
- [ ] tmux_janitor doesn't kill active sessions
- [ ] Auto-close works for Claude agents
- [ ] Git shows proper message when no upstream
- [ ] Auth blocks unauthorized access
- [ ] Rate limiting prevents DoS
- [ ] Errors are logged, not swallowed