#!/usr/bin/env python3
import json
import sys
import time
import urllib.request

CDP_URL = "http://localhost:9222"

def cdp_request(method, path=None):
    url = f"{CDP_URL}/json/{method}"
    if path:
        url += f"?{path}"
    req = urllib.request.Request(url, method='PUT' if method == 'new' else 'GET')
    return json.loads(urllib.request.urlopen(req, timeout=5).read())

def find_tab(url_pattern):
    try:
        tabs = cdp_request('list')
        for t in tabs:
            if url_pattern in t.get('url', ''):
                return t.get('webSocketDebuggerUrl')
    except Exception:
        pass
    return None

def open_tab(url):
    try:
        tab = cdp_request('new', url)
        return tab.get('webSocketDebuggerUrl')
    except Exception:
        return None

def fetch_gmail():
    from playwright.sync_api import sync_playwright

    ws_url = find_tab('mail.google.com')
    if not ws_url:
        ws_url = open_tab('https://mail.google.com/mail/u/0/')
        if not ws_url:
            return {"available": False, "needs_login": False, "emails": [], "summary": "cannot open gmail"}
        time.sleep(8)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if 'mail.google.com' in pg.url:
                page = pg
                break

        if not page:
            return {"available": False, "needs_login": False, "emails": [], "summary": "gmail tab lost"}

        if any(x in page.url for x in ['accounts.google.com', 'onelogin.com', 'login.microsoftonline.com']):
            return {"available": False, "needs_login": True, "login_url": page.url, "emails": [], "summary": "login required"}

        page.wait_for_timeout(2000)

        emails = page.evaluate('''() => {
            const rows = document.querySelectorAll('tr.zA');
            const results = [];
            for (let i = 0; i < Math.min(rows.length, 30); i++) {
                const row = rows[i];
                const isUnread = row.classList.contains('zE');
                const fromEl = row.querySelector('.yX span[email]');
                const subjectEl = row.querySelector('.y6 span') || row.querySelector('.bog span');
                const timeEl = row.querySelector('.xW span[title]');
                if (!fromEl) continue;

                // Extract thread ID from jslog base64 — e.g. ["#thread-f:1867516551939425413",...]
                const jslog = row.getAttribute('jslog') || '';
                const b64match = jslog.match(/(?:^|;\\s*)1:([A-Za-z0-9+/]+)/);
                const b64 = b64match ? b64match[1] : '';
                let threadId = '';
                let urlFragment = '';
                try {
                    const padded = b64 + '='.repeat((4 - b64.length % 4) % 4);
                    const decoded = atob(padded);
                    const m = decoded.match(/"#thread-f:([0-9]+)"/);
                    if (m) {
                        threadId = m[1];
                        // Convert decimal thread ID to hex for Gmail URL
                        urlFragment = '/mail/u/0/#inbox/' + BigInt(m[1]).toString(16).toUpperCase();
                    }
                } catch(e) {}

                const emailId = threadId || row.getAttribute('id') || `row-${i}`;
                const allText = row.innerText || '';
                // Strip lines that are just thread-count/label noise (e.g. "2", "2 GCP", "3 Inbox")
                const lines = allText.split('\\n')
                    .map(l => l.trim())
                    .filter(l => l && l !== '-' && !/^\\d+\\s*[A-Z]*$/.test(l));
                const recipients = '';
                const rawSnippet = lines.slice(1, 4).join(' ').substring(0, 300);
                const snippet = rawSnippet.replace(/^\\d+\\s+(?:[A-Z][A-Z0-9]*\\s+)*/, '');

                results.push({
                    id: emailId,
                    from: fromEl.getAttribute('email') || fromEl.textContent.trim(),
                    from_name: fromEl.getAttribute('name') || fromEl.textContent.trim(),
                    recipients: recipients,
                    subject: subjectEl ? subjectEl.textContent.trim() : '(no subject)',
                    snippet: snippet,
                    allText: allText.substring(0, 500),
                    time: timeEl ? (timeEl.getAttribute('title') || timeEl.textContent.trim()) : '',
                    unread: isUnread,
                    url: urlFragment,
                });
            }
            return results;
        }''')

        return {"available": True, "needs_login": False, "emails": emails, "summary": f"{len(emails)} emails"}


def fetch_calendar(day_offset=0):
    from datetime import datetime, timedelta
    from playwright.sync_api import sync_playwright

    target_date = datetime.now() + timedelta(days=day_offset)
    date_str = target_date.strftime("%A, %b %d")
    date_path = target_date.strftime("%Y/%m/%d")

    ws_url = find_tab('calendar.google.com')
    if not ws_url:
        ws_url = open_tab(f'https://calendar.google.com/calendar/r/day/{date_path}')
        if not ws_url:
            return {"available": False, "needs_login": False, "events": [], "summary": "cannot open calendar", "date": date_str}
        time.sleep(6)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if 'calendar.google.com' in pg.url:
                page = pg
                break

        if not page:
            return {"available": False, "needs_login": False, "events": [], "summary": "calendar tab lost", "date": date_str}

        if any(x in page.url for x in ['accounts.google.com', 'onelogin.com', 'login.microsoftonline.com']):
            return {"available": False, "needs_login": True, "events": [], "summary": "login required", "date": date_str}

        # Always navigate to the specific day view
        try:
            page.goto(f'https://calendar.google.com/calendar/r/day/{date_path}', timeout=12000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        events = page.evaluate('''() => {
            // [data-eventid] is the confirmed working selector for event chips
            const eventEls = document.querySelectorAll('[data-eventid]');
            const seen = new Set();
            const results = [];

            eventEls.forEach(el => {
                const rawText = el.textContent.trim();
                if (!rawText || rawText === 'No events') return;

                // Deduplicate by raw text
                if (seen.has(rawText)) return;
                seen.add(rawText);

                // Parse format: "9:15am to 9:30am, Title, Person, ..."
                // or all-day: "TitleAll day, Title, Calendar, ..."
                let title = '', time_str = '';

                if (rawText.includes('All day,')) {
                    time_str = 'All day';
                    const afterAllDay = rawText.split('All day,')[1] || '';
                    title = afterAllDay.split(',')[0].trim();
                } else {
                    const parts = rawText.split(', ');
                    // First part looks like a time range if it contains am/pm
                    if (parts[0] && /[0-9]/.test(parts[0]) && /(am|pm)/i.test(parts[0])) {
                        time_str = parts[0].trim();
                        title = parts[1] ? parts[1].trim() : rawText;
                    } else {
                        title = parts[0].trim();
                    }
                }

                if (!title) return;

                // Try to get background color from the chip or its parent
                let color = '';
                try {
                    const chip = el.querySelector('[style*="background"]') || el;
                    const bg = window.getComputedStyle(chip).backgroundColor;
                    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') color = bg;
                } catch(e) {}

                results.push({ title, time: time_str, location: '', color });
            });

            return results;
        }''')

        summary = f"{len(events)} event{'s' if len(events) != 1 else ''}" if events else "no events"
        return {"available": True, "needs_login": False, "events": events, "summary": summary, "date": date_str}


def delete_emails(email_ids):
    from playwright.sync_api import sync_playwright

    ws_url = find_tab('mail.google.com')
    if not ws_url:
        return {"ok": False, "error": "no gmail tab open"}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if 'mail.google.com' in pg.url:
                page = pg
                break

        if not page:
            return {"ok": False, "error": "gmail tab lost"}

        # Find and select each row by matching thread ID in jslog
        deleted = page.evaluate('''(emailIds) => {
            const rows = document.querySelectorAll('tr.zA');
            let selected = 0;
            for (const eid of emailIds) {
                const row = Array.from(rows).find(r => {
                    const jslog = r.getAttribute('jslog') || '';
                    const b64 = (jslog.match(/(?:^|;\\s*)1:([A-Za-z0-9+/]+)/)?.[1] || '');
                    const padded = b64 + '='.repeat((4 - b64.length % 4) % 4);
                    try { return atob(padded).includes(`"#thread-f:${eid}"`); }
                    catch(e) { return false; }
                });
                if (!row) continue;
                // Click the row's checkbox area (works via the hover-reveal checkbox)
                const checkbox = row.querySelector('.oZ-x3') || row.querySelector('[role="checkbox"]');
                if (checkbox) { checkbox.click(); selected++; }
            }
            return selected;
        }''', email_ids)

        if deleted > 0:
            page.wait_for_timeout(500)
            try:
                delete_btn = page.query_selector('[data-tooltip="Delete"], [aria-label="Delete"]')
                if delete_btn:
                    delete_btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

        return {"ok": True, "deleted": deleted}


def mark_read(thread_ids):
    from playwright.sync_api import sync_playwright

    ws_url = find_tab('mail.google.com')
    if not ws_url:
        return {"ok": False, "error": "no gmail tab open"}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if 'mail.google.com' in pg.url:
                page = pg
                break

        if not page:
            return {"ok": False, "error": "gmail tab lost"}

        marked = page.evaluate('''(threadIds) => {
            const rows = document.querySelectorAll('tr.zA');
            let selected = 0;
            for (const tid of threadIds) {
                const row = Array.from(rows).find(r => {
                    const jslog = r.getAttribute('jslog') || '';
                    const b64 = (jslog.match(/(?:^|;\\s*)1:([A-Za-z0-9+/]+)/)?.[1] || '');
                    const padded = b64 + '='.repeat((4 - b64.length % 4) % 4);
                    try { return atob(padded).includes(`"#thread-f:${tid}"`); }
                    catch(e) { return false; }
                });
                if (!row) continue;
                const checkbox = row.querySelector('.oZ-x3') || row.querySelector('[role="checkbox"]');
                if (checkbox) { checkbox.click(); selected++; }
            }
            return selected;
        }''', thread_ids)

        if marked > 0:
            page.wait_for_timeout(800)
            read_clicked = False
            try:
                btn = page.query_selector('[data-tooltip="Mark as read"], [aria-label="Mark as read"]')
                if btn:
                    btn.click()
                    read_clicked = True
                else:
                    more = page.query_selector('[data-tooltip="More"], [aria-label="More"]')
                    if more:
                        more.click()
                        page.wait_for_timeout(400)
                        read_item = page.query_selector('[id$=":4"], [data-action-id="11"]')
                        if read_item:
                            read_item.click()
                            read_clicked = True
            except Exception:
                pass
            if not read_clicked:
                # Gmail keyboard shortcut: I = mark as read
                try:
                    page.keyboard.press('I')
                except Exception:
                    pass
            page.wait_for_timeout(600)

        return {"ok": True, "marked": marked}


def fetch_email_body(url_fragment):
    """Open Gmail thread in a new tab, extract body text, close tab."""
    from playwright.sync_api import sync_playwright

    if not url_fragment:
        return {"ok": False, "body": "no url"}

    full_url = f"https://mail.google.com{url_fragment}"

    # Open a new tab for the thread
    try:
        new_tab = cdp_request('new', full_url)
    except Exception as e:
        return {"ok": False, "body": f"cannot open tab: {e}"}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        # Wait for new page to appear
        page = None
        for _ in range(12):
            time.sleep(0.5)
            for pg in ctx.pages:
                if url_fragment.split('/')[-1] in pg.url or full_url in pg.url:
                    page = pg
                    break
            if page:
                break

        if not page:
            return {"ok": False, "body": "tab not found"}

        try:
            page.wait_for_timeout(2500)
            body = page.evaluate('''() => {
                // Try multiple Gmail selectors for email body
                const selectors = ['.a3s.aiL', '.a3s', '[data-message-id] .ii.gt'];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    let best = '';
                    els.forEach(el => {
                        const t = el.innerText.trim();
                        if (t.length > best.length) best = t;
                    });
                    if (best.length > 20) return best.substring(0, 3000);
                }
                return '';
            }''')
        except Exception as e:
            body = ""
        finally:
            try:
                page.close()
            except Exception:
                pass

    return {"ok": True, "body": body or "(could not extract body)"}


def setup_gmail_labels():
    """Create GCP and AWS labels in Gmail and set up filters via Gmail REST API."""
    from playwright.sync_api import sync_playwright

    ws_url = find_tab('mail.google.com')
    if not ws_url:
        return {"ok": False, "error": "no gmail tab"}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if 'mail.google.com' in pg.url:
                page = pg
                break
        if not page:
            return {"ok": False, "error": "gmail tab lost"}

        results = []

        # Create labels via Gmail API (user is already authenticated in the browser)
        labels_result = page.evaluate('''async () => {
            const created = [];
            const errors = [];

            // List existing labels
            let existingLabels = [];
            try {
                const resp = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/labels');
                if (resp.ok) {
                    const data = await resp.json();
                    existingLabels = (data.labels || []).map(l => l.name.toLowerCase());
                }
            } catch(e) { errors.push('list: ' + e.message); }

            // Create labels if they don't exist
            for (const name of ['GCP', 'AWS']) {
                if (existingLabels.includes(name.toLowerCase())) {
                    created.push(name + ' (already exists)');
                    continue;
                }
                try {
                    const resp = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/labels', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name})
                    });
                    if (resp.ok) created.push(name + ' created');
                    else errors.push(name + ': ' + resp.status + ' ' + await resp.text());
                } catch(e) { errors.push(name + ': ' + e.message); }
            }

            return {created, errors};
        }''')

        results.append(labels_result)

        # Create filters via Gmail API
        filters_result = page.evaluate('''async () => {
            const created = [];
            const errors = [];

            // Get label IDs
            let gcpId = null, awsId = null;
            try {
                const resp = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/labels');
                const data = await resp.json();
                for (const l of (data.labels || [])) {
                    if (l.name === 'GCP') gcpId = l.id;
                    if (l.name === 'AWS') awsId = l.id;
                }
            } catch(e) { errors.push('get labels: ' + e.message); }

            // Check existing filters
            let existingFilters = [];
            try {
                const resp = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/settings/filters');
                const data = await resp.json();
                existingFilters = data.filter || [];
            } catch(e) {}

            // GCP filter: from devops@bonniernews.se
            if (gcpId) {
                const alreadyExists = existingFilters.some(f =>
                    f.criteria && f.criteria.from && f.criteria.from.includes('devops@bonniernews.se'));
                if (!alreadyExists) {
                    try {
                        const resp = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/settings/filters', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                criteria: {from: 'devops@bonniernews.se'},
                                action: {addLabelIds: [gcpId], removeLabelIds: ['INBOX']}
                            })
                        });
                        if (resp.ok) created.push('GCP filter created');
                        else errors.push('GCP filter: ' + resp.status + ' ' + await resp.text());
                    } catch(e) { errors.push('GCP filter: ' + e.message); }
                } else {
                    created.push('GCP filter already exists');
                }
            }

            // AWS filter: from amazon.com or amazonaws.com
            if (awsId) {
                const alreadyExists = existingFilters.some(f =>
                    f.criteria && f.criteria.from && f.criteria.from.includes('amazon'));
                if (!alreadyExists) {
                    try {
                        const resp = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/settings/filters', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                criteria: {from: '(amazon.com OR amazonaws.com OR aws.amazon.com)'},
                                action: {addLabelIds: [awsId], removeLabelIds: ['INBOX']}
                            })
                        });
                        if (resp.ok) created.push('AWS filter created');
                        else errors.push('AWS filter: ' + resp.status + ' ' + await resp.text());
                    } catch(e) { errors.push('AWS filter: ' + e.message); }
                } else {
                    created.push('AWS filter already exists');
                }
            }

            return {created, errors};
        }''')

        results.append(filters_result)

    return {"ok": True, "results": results}


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'gmail'
    try:
        if cmd == 'gmail':
            result = fetch_gmail()
        elif cmd == 'calendar':
            day = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            result = fetch_calendar(day)
        elif cmd == 'delete':
            ids = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
            result = delete_emails(ids)
        elif cmd == 'mark_read':
            ids = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
            result = mark_read(ids)
        elif cmd == 'fetch_body':
            url_frag = sys.argv[2] if len(sys.argv) > 2 else ''
            result = fetch_email_body(url_frag)
        elif cmd == 'setup_labels':
            result = setup_gmail_labels()
        else:
            result = {"error": f"unknown command: {cmd}"}
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
