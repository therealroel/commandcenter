import requests
from datetime import datetime, timedelta


class WeatherService:
    def __init__(self, location="Copenhagen", units="metric"):
        self.location = location
        self.units = units
        self._cache = None
        self._cache_time = None

    def _is_cache_valid(self):
        if self._cache is None or self._cache_time is None:
            return False
        return datetime.now() - self._cache_time < timedelta(minutes=5)

    def get_current(self) -> dict:
        if self._is_cache_valid():
            return self._cache

        try:
            url = f"https://wttr.in/{self.location}?format=j1"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            current = data.get("current_condition", [{}])[0]
            self._cache = {
                "temp_c": int(current.get("temp_C", 0)),
                "feels_like_c": int(current.get("FeelsLikeC", 0)),
                "condition": current.get("weatherDesc", [{}])[0].get("value", "Unknown"),
                "humidity": int(current.get("humidity", 0)),
                "wind_kph": int(current.get("windspeedKmph", 0)),
                "icon": current.get("weatherIconUrl", [{}])[0].get("value", "")
            }
            self._cache_time = datetime.now()
            return self._cache
        except Exception:
            return {
                "temp_c": 0,
                "feels_like_c": 0,
                "condition": "Error fetching weather",
                "humidity": 0,
                "wind_kph": 0,
                "icon": ""
            }


class WeatherWidget:
    def __init__(self, term, service):
        self.term = term
        self.service = service

    def render(self):
        w = self.service.get_current()
        return f"☀️ {self.service.location} {w['temp_c']}°C | {w['condition']} | Feels {w['feels_like_c']}°C | 💧 {w['humidity']}% | 💨 {w['wind_kph']} km/h"