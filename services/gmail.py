import json
import sys
import time
import logging
import urllib.request
from pathlib import Path
from datetime import datetime
import gevent.subprocess as subprocess

logger = logging.getLogger("cc.gmail")

CDP_URL = "http://localhost:9222"
CONFIG_DIR = Path("config")
SEEN_FILE = CONFIG_DIR / "gmail_seen.json"
PATTERNS_FILE = CONFIG_DIR / "gmail_cleanup_patterns.json"
OPENCODE_MODEL = "opencode-go/qwen3.7-max"

class GmailService:
    def __init__(self):
        self._last_fetch_ts = 0
        self._seen_ids = set()
        self._cleanup_patterns = []
        self._load_state()
    
    def is_available(self):
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
            return True
        except Exception:
            return False
    
    def _load_state(self):
        try:
            if SEEN_FILE.exists():
                self._seen_ids = set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            self._seen_ids = set()
        try:
            if PATTERNS_FILE.exists():
                self._cleanup_patterns = json.loads(PATTERNS_FILE.read_text()).get("patterns", [])
        except Exception:
            self._cleanup_patterns = []
    
    def _save_seen(self):
        try:
            SEEN_FILE.parent.mkdir(exist_ok=True)
            SEEN_FILE.write_text(json.dumps(list(self._seen_ids)))
        except Exception:
            pass
    
    def _save_patterns(self):
        try:
            PATTERNS_FILE.parent.mkdir(exist_ok=True)
            PATTERNS_FILE.write_text(json.dumps({"patterns": self._cleanup_patterns}))
        except Exception:
            pass
    
    def _cdp_request(self, method, path=None):
        url = f"{CDP_URL}/json/{method}"
        if path:
            url += f"?{path}"
        req = urllib.request.Request(url, method='PUT' if method == 'new' else 'GET')
        return json.loads(urllib.request.urlopen(req, timeout=5).read())
    
    def _find_gmail_tab(self):
        try:
            tabs = self._cdp_request('list')
            for t in tabs:
                if 'mail.google.com' in t.get('url', ''):
                    return t.get('webSocketDebuggerUrl')
        except Exception:
            pass
        return None
    
    def _open_gmail_tab(self):
        try:
            tab = self._cdp_request('new', 'https://mail.google.com/mail/u/0/')
            return tab.get('webSocketDebuggerUrl')
        except Exception as e:
            logger.warning(f"Failed to open Gmail tab: {e}")
            return None
    
    def get_emails(self):
        result = {
            "available": False,
            "needs_login": False,
            "login_url": None,
            "high": [],
            "action": [],
            "feed": [],
            "cleanup": [],
            "summary": "connecting...",
            "new_high": []
        }
        
        if not self.is_available():
            result["summary"] = "chrome offline"
            return result
        
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cdp_fetch.py"), "gmail"],
                capture_output=True,
                text=True,
                timeout=30
            )
            data = json.loads(proc.stdout)
        except Exception as e:
            logger.warning(f"gmail subprocess error: {e}")
            result["summary"] = f"error: {str(e)[:40]}"
            return result
        
        if "error" in data:
            result["summary"] = data["error"][:40]
            return result
        
        if data.get("needs_login"):
            result["needs_login"] = True
            result["login_url"] = data.get("login_url")
            result["summary"] = "login required"
            return result
        
        if not data.get("available"):
            result["summary"] = data.get("summary", "unavailable")
            return result
        
        emails = data.get("emails", [])
        result["available"] = True
        
        classifications = self._classify_batch(emails)
        
        for i, email in enumerate(emails):
            email_id = email["id"]
            is_new = email_id not in self._seen_ids
            
            classification = classifications[i] if i < len(classifications) else self._classify_rules(email)
            tier = classification['tier']
            email["tier"] = tier
            email["summary"] = classification.get('summary', email.get('subject', ''))
            email["noteworthy"] = classification.get('noteworthy', False)
            
            if tier == "HIGH":
                result["high"].append(email)
                if is_new and email.get("unread"):
                    result["new_high"].append(email)
            elif tier == "ACTION":
                result["action"].append(email)
            elif tier == "CLEANUP":
                result["cleanup"].append(email)
            else:
                if email.get("noteworthy"):
                    result["feed"].append(email)
            
            if email.get("unread"):
                self._seen_ids.add(email_id)
        
        self._save_seen()
        
        h = len(result["high"])
        a = len(result["action"])
        f = len(result["feed"])
        c = len(result["cleanup"])
        parts = []
        if h: parts.append(f"{h} high")
        if a: parts.append(f"{a} action")
        if f: parts.append(f"{f} feed")
        if c: parts.append(f"{c} cleanup")
        result["summary"] = " · ".join(parts) if parts else "inbox clear"
        
        self._last_fetch_ts = time.time()
        
        return result
    
    def _classify_batch(self, emails):
        """Classify multiple emails in batched LLM calls."""
        if not emails:
            return []
        
        all_results = []
        chunk_size = 10
        
        for start in range(0, len(emails), chunk_size):
            chunk = emails[start:start + chunk_size]
            
            email_summaries = []
            for i, email in enumerate(chunk):
                email_summaries.append(f"""
Email {i+1}:
From: {email.get('from', 'unknown')}
Recipients: {email.get('recipients', 'unknown')}
Subject: {email.get('subject', 'no subject')}
Content: {email.get('snippet', email.get('allText', '')[:200])}""")
            
            prompt = f"""Classify these {len(chunk)} emails for Thomas Roel Jørgensen (thomas.roel@borsen.dk). Reply with ONLY a JSON array like [{{"tier":"HIGH","summary":"one line","noteworthy":true}}, ...]. No markdown, no explanation.

Tiers:
- HIGH: Directly addressed to Thomas in the To: field. Look for "me" in recipients, his name, his email, or context that shows he's the primary recipient. Urgent or needs immediate action.
- ACTION: Thomas should act on it but he's CC'd, mentioned, or it's relevant to his work/team. Not the primary recipient.
- FEED: Newsletters, announcements, FYI - only mark noteworthy:true if truly important
- CLEANUP: Automated noise, irrelevant newsletters, things Thomas would delete without reading

Key: If recipients show "me" that's Thomas in To field. If it shows only other names, Thomas is likely CC'd or not directly addressed.

{chr(10).join(email_summaries)}"""

            try:
                result = subprocess.run(
                    ["opencode", "run", "--pure", "--model", OPENCODE_MODEL, prompt],
                    capture_output=True,
                    text=True,
                    timeout=45
                )
                
                output = result.stdout.strip()
                parsed = False
                for line in output.split('\n'):
                    line = line.strip()
                    if line.startswith('[') and '"tier"' in line:
                        classifications = json.loads(line)
                        if len(classifications) == len(chunk):
                            all_results.extend(classifications)
                            parsed = True
                            break
                
                if not parsed:
                    all_results.extend([self._classify_rules(email) for email in chunk])
                    
            except Exception as e:
                logger.warning(f"Batch LLM classification failed for chunk {start}: {e}")
                all_results.extend([self._classify_rules(email) for email in chunk])
        
        return all_results
    
    def _classify_rules(self, email):
        """Fallback rule-based classification."""
        from_addr = (email.get("from") or "").lower()
        
        for pattern in self._cleanup_patterns:
            if pattern.get("sender", "").lower() in from_addr and pattern.get("count", 0) >= 3:
                return {'tier': 'CLEANUP', 'summary': email.get('subject', ''), 'noteworthy': False}
        
        known_noise = [
            "newsletter", "digest", "noreply", "no-reply", "notifications",
            "hello@", "welcome@", "team@ship.", "notice@email.",
            "marketing@", "jira@", "confluence@"
        ]
        for pattern in known_noise:
            if pattern in from_addr:
                return {'tier': 'FEED', 'summary': email.get('subject', ''), 'noteworthy': False}
        
        return {'tier': 'ACTION', 'summary': email.get('subject', ''), 'noteworthy': False}
    
    def delete_emails(self, email_ids):
        if not self.is_available():
            return {"ok": False, "error": "chrome offline"}
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cdp_fetch.py"), "delete",
                 json.dumps(email_ids)],
                capture_output=True,
                text=True,
                timeout=30
            )
            return json.loads(proc.stdout)
        except Exception as e:
            logger.warning(f"delete subprocess error: {e}")
            return {"ok": False, "error": str(e)}
    
    def mark_seen(self, email_ids):
        for eid in email_ids:
            self._seen_ids.add(eid)
        self._save_seen()
        return {"ok": True}
    
    def record_deletion(self, sender, subject=""):
        for pattern in self._cleanup_patterns:
            if pattern.get("sender", "").lower() == sender.lower():
                pattern["count"] = pattern.get("count", 0) + 1
                pattern["last_deleted"] = datetime.now().isoformat()
                self._save_patterns()
                return
        
        self._cleanup_patterns.append({
            "sender": sender,
            "subject_regex": subject[:50],
            "count": 1,
            "last_deleted": datetime.now().isoformat()
        })
        self._save_patterns()
    
    def get_status(self):
        return {
            "available": self.is_available(),
            "last_fetch": self._last_fetch_ts,
            "seen_count": len(self._seen_ids),
            "patterns_count": len(self._cleanup_patterns)
        }
