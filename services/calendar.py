import json
import sys
import time
import logging
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import gevent.subprocess as subprocess

logger = logging.getLogger("cc.calendar")

CDP_URL = "http://localhost:9222"
_CDP_FETCH = Path(__file__).parent / "cdp_fetch.py"

class CalendarService:
    def __init__(self):
        self._last_fetch_ts = 0

    def is_available(self):
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def get_events(self, day_offset=0):
        target_date = datetime.now() + timedelta(days=day_offset)
        fallback = {
            "available": False,
            "needs_login": False,
            "events": [],
            "summary": "connecting...",
            "date": target_date.strftime("%A, %B %d"),
        }

        if not self.is_available():
            fallback["summary"] = "chrome offline"
            return fallback

        try:
            proc = subprocess.run(
                [sys.executable, str(_CDP_FETCH), "calendar", str(day_offset)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            data = json.loads(proc.stdout)
        except Exception as e:
            logger.warning(f"calendar subprocess error: {e}")
            fallback["summary"] = f"error: {str(e)[:40]}"
            return fallback

        if data.get("available"):
            self._last_fetch_ts = time.time()
        return data

    def get_status(self):
        return {
            "available": self.is_available(),
            "last_fetch": self._last_fetch_ts,
        }
