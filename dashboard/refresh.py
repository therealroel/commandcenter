import asyncio


class RefreshManager:
    def __init__(self, dashboard, weather_service, system_gatherer):
        self.dashboard = dashboard
        self.weather_service = weather_service
        self.system_gatherer = system_gatherer
        self._system_task = None
        self._weather_task = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._system_task = asyncio.create_task(self._system_refresh_loop())
        self._weather_task = asyncio.create_task(self._weather_refresh_loop())

    def stop(self) -> None:
        self._running = False
        if self._system_task:
            self._system_task.cancel()
        if self._weather_task:
            self._weather_task.cancel()

    async def _system_refresh_loop(self):
        while self._running:
            try:
                self.dashboard.update_system_metrics(
                    cpu=self.system_gatherer.get_cpu(),
                    ram=self.system_gatherer.get_ram(),
                    disk=self.system_gatherer.get_disk(),
                    system=self.system_gatherer.get_system()
                )
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1)

    async def _weather_refresh_loop(self):
        while self._running:
            try:
                self.dashboard.update_weather(self.weather_service.get_current())
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(300)