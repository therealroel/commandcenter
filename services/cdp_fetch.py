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
            return {"available": False, "needs_login": False, "high": [], "action": [], "feed": [], "cleanup": [], "summary": "cannot open gmail", "new_high": []}
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
            return {"available": False, "needs_login": False, "high": [], "action": [], "feed": [], "cleanup": [], "summary": "gmail tab lost", "new_high": []}

        url = page.url
        if any(x in url for x in ['accounts.google.com', 'onelogin.com', 'login.microsoftonline.com']):
            return {"available": False, "needs_login": True, "login_url": url, "high": [], "action": [], "feed": [], "cleanup": [], "summary": "login required", "new_high": []}

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
                const linkEl = row.querySelector('a[href*="#inbox/"]');
                if (!fromEl) continue;
                const emailId = row.getAttribute('data-id') || (linkEl ? linkEl.getAttribute('href').split('/').pop() : `row-${i}`);
                const allText = row.innerText || '';
                const lines = allText.split('\\n').map(l => l.trim()).filter(l => l && l !== '-');
                const recipients = lines.length > 1 ? lines[0] : '';
                results.push({
                    id: emailId,
                    from: fromEl.getAttribute('email') || fromEl.textContent.trim(),
                    from_name: fromEl.getAttribute('name') || fromEl.textContent.trim(),
                    recipients: recipients,
                    subject: subjectEl ? subjectEl.textContent.trim() : '(no subject)',
                    snippet: lines.slice(1, 4).join(' ').substring(0, 200),
                    allText: allText.substring(0, 500),
                    time: timeEl ? (timeEl.getAttribute('title') || timeEl.textContent.trim()) : '',
                    unread: isUnread,
                    url: linkEl ? linkEl.getAttribute('href') : ''
                });
            }
            return results;
        }''')

        return {"available": True, "needs_login": False, "emails": emails, "summary": f"{len(emails)} emails"}

def fetch_calendar(day_offset=0):
    from datetime import datetime, timedelta
    from playwright.sync_api import sync_playwright

    target_date = datetime.now() + timedelta(days=day_offset)

    ws_url = find_tab('calendar.google.com')
    if not ws_url:
        ws_url = open_tab('https://calendar.google.com/calendar/r')
        if not ws_url:
            return {"available": False, "needs_login": False, "events": [], "summary": "cannot open calendar", "date": target_date.strftime("%A, %B %d")}
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
            return {"available": False, "needs_login": False, "events": [], "summary": "calendar tab lost", "date": target_date.strftime("%A, %B %d")}

        url = page.url
        if any(x in url for x in ['accounts.google.com', 'onelogin.com', 'login.microsoftonline.com']):
            return {"available": False, "needs_login": True, "events": [], "summary": "login required", "date": target_date.strftime("%A, %B %d")}

        if day_offset == 1:
            try:
                page.goto(f'https://calendar.google.com/calendar/r/day/{target_date.strftime("%Y/%m/%d")}', timeout=10000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
        else:
            try:
                page.goto('https://calendar.google.com/calendar/r', timeout=10000)
                page.wait_for_timeout(2000)
            except Exception:
                pass

        events = page.evaluate('''() => {
            const eventEls = document.querySelectorAll('[data-eventid], .EfQccc, .FAxxKc');
            const results = [];
            eventEls.forEach(el => {
                const titleEl = el.querySelector('.lhydbb, .gVNoLb, [data-event-title]') || el;
                const timeEl = el.querySelector('.gVNoLb.EiZ8Zd, .SuAnhb');
                const locationEl = el.querySelector('.IE3WHd, [data-event-location]');
                const title = titleEl ? titleEl.textContent.trim() : '';
                const time = timeEl ? timeEl.textContent.trim() : '';
                const location = locationEl ? locationEl.textContent.trim() : '';
                if (title && title !== 'No events') {
                    const bgColor = window.getComputedStyle(el).backgroundColor;
                    results.push({ title, time, location, color: bgColor });
                }
            });
            return results;
        }''')

        return {"available": True, "needs_login": False, "events": events, "summary": f"{len(events)} events" if events else "no events", "date": target_date.strftime("%A, %B %d")}

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

        deleted = 0
        for eid in email_ids:
            try:
                row = page.query_selector(f'tr[data-id="{eid}"]')
                if row:
                    checkbox = row.query_selector('.oZ-x3')
                    if checkbox:
                        checkbox.click()
                        page.wait_for_timeout(300)
                        deleted += 1
            except Exception:
                pass

        if deleted > 0:
            try:
                delete_btn = page.query_selector('[data-tooltip="Delete"]')
                if delete_btn:
                    delete_btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

        return {"ok": True, "deleted": deleted}


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
        else:
            result = {"error": f"unknown command: {cmd}"}
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
