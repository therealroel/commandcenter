# Borsen Inbox Review Dock

**Date:** 2026-06-08  
**Status:** Draft  
**Scope:** Gmail inbox review widget for CommandCenter (Borsen email only)

---

## Overview

A collapsible dock in CommandCenter that fetches, classifies, and displays unread emails from the Borsen Gmail account. Emails are triaged by an opencode agent into priority tiers, with smart alerting for high-priority items and a cleanup section for bulk deletion of irrelevant mail.

## Goals

1. Never miss an important email directed to the user
2. Surface action-required emails prominently
3. Reduce inbox noise via intelligent feed summarization
4. Provide a one-click cleanup experience for irrelevant mail
5. Learn from user deletion patterns to improve classification

## Non-Goals

- Full email client (no compose, reply, or threading UI)
- Support for multiple Gmail accounts (Borsen only)
- Calendar integration (separate feature)

---

## Architecture

### Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Gmail Service | `services/gmail.py` | OAuth2 auth, fetch unread emails, delete emails |
| Classification Agent | `services/gmail_classifier.py` | Invoke opencode agent to classify each email |
| Seen Tracker | `services/gmail_seen.py` | Track which emails have been displayed while CC is open |
| Socket.IO Events | `server.py` | Push `gmail_update` events every 5 minutes |
| UI Dock | `templates/index.html` | Collapsible dock with 4 sections |

### Data Flow

```
Gmail API → gmail.py (fetch) → gmail_classifier.py (classify) → Socket.IO → UI
                                    ↓
                              gmail_seen.py (track displayed)
```

### Refresh Cycle

- **Interval:** Every 5 minutes
- **Lookback:** From `last_fetched_timestamp` to now
- **Monday behavior:** If `last_fetched_timestamp` is older than 24h (e.g., weekend), fetch from that timestamp forward — no fixed Friday 17:00 cutoff
- **First run:** Fetch last 24h of unread

---

## Email Classification

### Tiers

| Tier | Criteria | UI Treatment |
|------|----------|--------------|
| **HIGH** | Addressed directly to user in `To:` field; agent judges urgent/action-required | Red section, prominent cards, triggers alert |
| **ACTION** | User is CC'd, mentioned, or agent judges user should act | Yellow section, visible cards |
| **FEED** | Newsletters, announcements, FYI — agent summarizes only noteworthy items | White/gray section, collapsed by default, shows count + "N noteworthy" |
| **CLEANUP** | Agent judges irrelevant (newsletters user never opens, automated noise) | Bottom section with checkboxes, bulk delete |

### Classification Agent

- Implemented as a subagent spawned by `gmail_classifier.py`
- Uses the active opencode agent (same as channel panels)
- Prompt template in `services/gmail_classifier_prompt.txt`
- Input: `from`, `to`, `cc`, `subject`, `body_snippet` (first 500 chars)
- Output: `{ tier: "HIGH|ACTION|FEED|CLEANUP", summary: "...", noteworthy: bool, deletable: bool }`
- Batching: Up to 10 emails per agent invocation to reduce overhead
- Learns from deletion history: if user consistently deletes from a sender, auto-classify as CLEANUP

### Noteworthy Flag (FEED tier)

Agent marks FEED emails as `noteworthy: true` if they contain:
- Breaking news relevant to user's industry
- Action items buried in newsletters
- Time-sensitive announcements

Only noteworthy FEED emails are shown expanded; others contribute to the count only.

---

## Alerting

### HIGH Priority Alerts

When a new HIGH email arrives (not previously seen):

1. **Browser notification:** Title = sender, body = subject + snippet
2. **Alert sound:** Short chime via `static/gmail-alert.mp3` (bundled, ~1s, configurable volume)
3. **Auto-expand dock:** If collapsed, expand to show the email
4. **Visual pulse:** Dock header flashes red briefly (CSS animation, 2s)

### Seen Tracking

- Server maintains a set of `seen_email_ids` in memory (cleared on CC restart)
- An email is marked "seen" when:
  - CC is open (browser tab active)
  - The email has been rendered in the UI for ≥1 second
- Seen emails never re-trigger alerts, even on refresh
- On CC restart, all emails are "unseen" again — but only new ones (since `last_fetched_timestamp`) trigger alerts

---

## Cleanup System

### UI

- Collapsible section at bottom of dock: `🗑 CLEANUP (18) [Delete all]`
- Each email has a checkbox (default unchecked)
- "Delete all" button deletes all checked emails (or all if none checked)
- Individual delete button per email

### Learning

- When user deletes an email, record `(sender, subject_pattern)` in `config/gmail_cleanup_patterns.json`
- Schema: `{ "patterns": [{ "sender": "newsletter@techcrunch.com", "subject_regex": "daily digest", "count": 5, "last_deleted": "2026-06-08T10:00:00Z" }] }`
- On next classification, if sender matches a deleted pattern (count ≥ 3), auto-classify as CLEANUP
- User can review/edit the deletion patterns via a settings link (future)

### Safety

- Deleted emails go to Gmail Trash (recoverable for 30 days)
- Confirmation dialog for "Delete all" (not for individual deletes)

---

## Authentication

### OAuth2 Flow

1. First visit to CC shows "Connect Borsen Gmail" button in the dock
2. Click opens Google OAuth2 consent popup
3. User grants `gmail.readonly` + `gmail.modify` scopes
4. Server stores refresh token in `config/gmail_token.json`
5. Access token auto-refreshed on expiry

### Token Storage

- Refresh token: `config/gmail_token.json` (gitignored)
- Client ID/secret: `config/gmail_credentials.json` (gitignored, user provides from Google Cloud Console)

### Setup Instructions (shown in UI if credentials missing)

1. Go to Google Cloud Console → APIs & Services → Credentials
2. Create OAuth 2.0 Client ID (Web application)
3. Add `http://localhost:5000` to authorized redirect URIs
4. Download JSON, save as `config/gmail_credentials.json`
5. Restart CC, click "Connect Borsen Gmail"

---

## UI Specification

### Dock Structure

```html
<div class="gmail-dock" id="gmail-dock">
  <div class="gmail-head" id="gmail-head" role="button" tabindex="0" aria-expanded="true">
    <span class="gmail-caret">▾</span>
    <span class="gmail-title">✉ BORSEN INBOX <span class="dot" id="gmail-dot"></span></span>
    <span class="gmail-summary" id="gmail-summary">connecting...</span>
  </div>
  <div class="gmail-body" id="gmail-body">
    <div class="gmail-section gmail-high">...</div>
    <div class="gmail-section gmail-action">...</div>
    <div class="gmail-section gmail-feed">...</div>
    <div class="gmail-section gmail-cleanup">...</div>
  </div>
</div>
```

### Dock Header Summary

Format: `3 high · 5 action · 12 feed · 18 cleanup`

- Dot color: green (no HIGH), red (HIGH present), yellow (ACTION only)
- Click header to collapse/expand (localStorage persisted)

### Sections

Each section is collapsible independently (click section header to toggle):

- **HIGH:** Always expanded if present
- **ACTION:** Expanded by default
- **FEED:** Collapsed by default, shows "12 feed — 3 noteworthy"
- **CLEANUP:** Collapsed by default, shows "18 cleanup [Delete all]"

### Email Card

```html
<div class="gmail-card" data-email-id="...">
  <div class="gmail-card-head">
    <span class="gmail-from">CEO</span>
    <span class="gmail-time">2h ago</span>
  </div>
  <div class="gmail-subject">Q3 budget approval needed</div>
  <div class="gmail-snippet">Please review the attached budget proposal and approve by EOD...</div>
  <div class="gmail-actions">
    <a href="..." target="_blank">Open in Gmail</a>
    <button class="gmail-delete">Delete</button>
  </div>
</div>
```

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/gmail/auth` | GET | Initiate OAuth2 flow |
| `/api/gmail/auth/callback` | GET | OAuth2 callback, store token |
| `/api/gmail/status` | GET | Check auth status + last fetch time |
| `/api/gmail/delete` | POST | Delete email(s) by ID |
| `/api/gmail/seen` | POST | Mark email(s) as seen |

---

## Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `gmail_update` | server → client | `{ high: [...], action: [...], feed: [...], cleanup: [...], summary: "..." }` |
| `gmail_alert` | server → client | `{ email_id, from, subject, snippet }` (triggers notification + sound) |

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No credentials | Show "Connect Borsen Gmail" button + setup instructions |
| Token expired | Auto-refresh; if fails, prompt re-auth |
| Gmail API quota | Log warning, retry with exponential backoff |
| Network error | Show "offline" dot, retry on next cycle |
| Classification agent error | Fall back to rule-based (To/CC fields), log error |

---

## Testing

### Unit Tests

- `test_gmail_fetch.py`: Mock Gmail API, verify fetch + lookback logic
- `test_gmail_classifier.py`: Mock agent, verify tier assignment
- `test_gmail_seen.py`: Verify seen tracking + alert suppression

### Integration Tests

- OAuth2 flow (mock Google)
- Socket.IO event emission
- Delete endpoint

### Manual Testing

- Connect real Borsen Gmail account
- Verify Monday lookback catches weekend emails
- Verify HIGH alerts trigger notification + sound + auto-expand
- Verify cleanup deletes work + learning persists

---

## Future Enhancements

- **Calendar integration:** Show upcoming meetings in the same dock
- **Smart reply suggestions:** Agent suggests quick replies for ACTION emails
- **Snooze:** "Remind me later" button on emails
- **Multi-account:** Support additional Gmail accounts
- **Deletion pattern editor:** UI to review/edit auto-cleanup rules

---

## Open Questions

None — design approved 2026-06-08.
