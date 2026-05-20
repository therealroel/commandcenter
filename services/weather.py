import time
import urllib.request
import json


class WeatherService:
    def __init__(self, city: str = "Copenhagen"):
        self.city = city
        self._cache = None
        self._cache_time = 0
        self._cache_ttl = 300

    def get_current(self) -> dict:
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        try:
            url = f"https://wttr.in/{self.city}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "commandcenter"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())

            current = data["current_condition"][0]
            result = {
                "temp_c": float(current["temp_C"]),
                "condition": current["weatherDesc"][0]["value"],
                "feels_like_c": float(current["FeelsLikeC"]),
                "humidity": int(current["humidity"]),
                "wind_kph": float(current["windspeedKmph"]),
            }
            self._cache = result
            self._cache_time = now
            return result
        except Exception:
            if self._cache:
                return self._cache
            return {
                "temp_c": 0,
                "condition": "unknown",
                "feels_like_c": 0,
                "humidity": 0,
                "wind_kph": 0,
            }
