import psutil
import os
from datetime import timedelta


class SystemGatherer:
    def get_cpu(self) -> dict:
        percent = psutil.cpu_percent(interval=0.1)
        freq_mhz = psutil.cpu_freq().current if psutil.cpu_freq() else 0
        cores = psutil.cpu_count()
        temp_c = self._get_cpu_temp()
        return {"percent": percent, "freq_mhz": freq_mhz, "temp_c": temp_c, "cores": cores}

    def _get_cpu_temp(self) -> float:
        try:
            temp_file = "/sys/class/thermal/thermal_zone0/temp"
            if os.path.exists(temp_file):
                with open(temp_file) as f:
                    return int(f.read().strip()) / 1000.0
        except Exception:
            pass
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    for entry in entries:
                        if entry.current is not None:
                            return entry.current
        except Exception:
            pass
        return 0.0

    def get_ram(self) -> dict:
        mem = psutil.virtual_memory()
        return {
            "used_gb": mem.used / (1024**3),
            "total_gb": mem.total / (1024**3),
            "percent": mem.percent
        }

    def get_disk(self) -> dict:
        for partition in psutil.disk_partitions():
            if partition.mountpoint == "/":
                usage = psutil.disk_usage(partition.mountpoint)
                return {
                    "used_gb": usage.used / (1024**3),
                    "total_gb": usage.total / (1024**3),
                    "percent": usage.percent,
                    "mount": partition.mountpoint
                }
        return {"used_gb": 0, "total_gb": 0, "percent": 0, "mount": "/"}

    def get_system(self) -> dict:
        hostname = psutil.os.uname().nodename
        os_name = psutil.os.uname().sysname
        kernel = psutil.os.uname().release
        uptime_seconds = psutil.boot_time()
        now = psutil.os.path.getmtime("/proc/1") if os.path.exists("/proc/1") else psutil.boot_time()
        uptime_seconds = (now - psutil.boot_time()) if os.path.exists("/proc/1") else 0
        try:
            with open("/proc/uptime") as f:
                uptime_seconds = float(f.read().split()[0])
        except Exception:
            uptime_seconds = psutil.time.time() - psutil.boot_time()
        uptime_delta = timedelta(seconds=int(uptime_seconds))
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m"
        return {
            "hostname": hostname,
            "os": os_name,
            "kernel": kernel,
            "uptime_str": uptime_str
        }


class SystemWidget:
    def __init__(self, term, gatherer):
        self.term = term
        self.gatherer = gatherer

    def render(self):
        cpu = self.gatherer.get_cpu()
        ram = self.gatherer.get_ram()
        disk = self.gatherer.get_disk()
        system = self.gatherer.get_system()

        if cpu["percent"] < 70:
            cpu_color = "#00ff88"
        elif cpu["percent"] < 90:
            cpu_color = "#ffaa00"
        else:
            cpu_color = "#ff4444"

        cpu_line = f"CPU: {cpu['percent']:.0f}% @ {cpu['freq_mhz']:.0f}MHz | {cpu['temp_c']:.0f}°C | {cpu['cores']} cores"
        cpu_line = self.term.color(cpu_line, cpu_color)

        ram_line = f"RAM: {ram['used_gb']:.1f} / {ram['total_gb']:.1f} GB | {ram['percent']:.0f}%"
        disk_line = f"Disk: {disk['used_gb']:.0f} / {disk['total_gb']:.0f} GB | {disk['percent']:.0f}%"
        sys_line = f"{system['hostname']} | {system['os']} | {system['kernel']} | uptime {system['uptime_str']}"

        return [cpu_line, ram_line, disk_line, sys_line]