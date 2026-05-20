import time
import psutil


class SystemService:
    def get_metrics(self) -> dict:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_freq = psutil.cpu_freq()
        freq_mhz = cpu_freq.current if cpu_freq else 0

        try:
            temps = psutil.sensors_temperatures()
            if temps:
                first_sensor = next(iter(temps.values()))
                temp_c = first_sensor[0].current if first_sensor else 0
            else:
                temp_c = 0
        except (AttributeError, StopIteration):
            temp_c = 0

        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        uptime_seconds = time.time() - psutil.boot_time()
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        return {
            "cpu": {
                "percent": cpu_percent,
                "freq_mhz": freq_mhz,
                "temp_c": temp_c,
                "cores": psutil.cpu_count(logical=True),
            },
            "ram": {
                "used_gb": round(ram.used / (1024**3), 2),
                "total_gb": round(ram.total / (1024**3), 2),
                "percent": ram.percent,
            },
            "disk": {
                "used_gb": round(disk.used / (1024**3), 2),
                "total_gb": round(disk.total / (1024**3), 2),
                "percent": disk.percent,
            },
            "uptime": {
                "days": days,
                "hours": hours,
                "minutes": minutes,
            },
        }
