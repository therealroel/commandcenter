from datetime import datetime, timezone
import os


class HeaderWidget:
    def __init__(self, term):
        self.term = term

    @property
    def height(self):
        return 8

    def _color(self, hex_color):
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        try:
            return self.term.color(r, g, b)
        except Exception:
            return self.term.white

    def render(self):
        hostname = os.uname().nodename
        uptime = self._get_uptime()
        local_time = datetime.now().strftime("%H:%M:%S")
        utc_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
        copenhagen_time = self._get_copenhagen_time()

        lines = []
        banner = self._build_banner()
        for line in banner:
            lines.append(line)

        lines.append("")
        lines.append(f"{self._color('#00d9ff')}▶ Welcome back, THOMAS!{self.term.normal}")
        lines.append(f"{self.term.white}  System: {hostname} | Uptime: {uptime}")
        lines.append("")
        lines.append(f"{self.term.dim}  Clock: {local_time} local | {utc_time} UTC | {copenhagen_time} Copenhagen")
        lines.append("")

        return "\n".join(lines)

    def _build_banner(self):
        cyan = self._color('#00d9ff')
        banner_lines = [
            f"{cyan}╔══════█▓══════════▓█══════╗",
            f"{cyan}║▒░▒░▒░▒░▒░▒░▒░▒░▒░▒░▒░║",
            f"{cyan}║ COMMAND ▒░▒░▒░ CENTER ▒░▒░▒░▒░║",
            f"{cyan}║▒░▒░▒░▒░▒░▒░▒░▒░▒░▒░▒░║",
            f"{cyan}╚══════▀▄══════════▄▀══════╝",
        ]
        return banner_lines

    def _get_uptime(self):
        try:
            with open("/proc/uptime", "r") as f:
                uptime_seconds = float(f.readline().split()[0])
            hours = int(uptime_seconds // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
        except Exception:
            return "unknown"

    def _get_copenhagen_time(self):
        copenhagen_tz = timezone.utc
        return datetime.now(copenhagen_tz).strftime("%H:%M:%S")