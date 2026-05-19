from datetime import datetime, timezone
import os


class HeaderWidget:
    BACKGROUND = "#0d1117"
    PRIMARY = "#e6edf3"
    SECONDARY = "#7d8590"
    ACCENT_CYAN = "#00d9ff"

    def __init__(self, term):
        self.term = term

    @property
    def height(self):
        return 8

    def _fgcolor(self, hex_color):
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        return self.term.rgb_color(r, g, b)

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
        lines.append(f"{self._fgcolor(self.ACCENT_CYAN)}▶ Welcome back, THOMAS!{self._fgcolor(self.PRIMARY)}")
        lines.append(f"{self._fgcolor(self.PRIMARY)}  System: {hostname} | Uptime: {uptime}")
        lines.append("")
        lines.append(f"{self._fgcolor(self.SECONDARY)}  Clock: {local_time} local | {utc_time} UTC | {copenhagen_time} Copenhagen")
        lines.append("")

        return "\n".join(lines)

    def _build_banner(self):
        chars = {
            "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
            "h": "═", "v": "║",
            "fill_tl": "█▓", "fill_tr": "▓█", "fill_m": "▒░",
            "fill_bl": "▀▄", "fill_br": "▄▀"
        }

        banner_lines = [
            f"{self._fgcolor(self.ACCENT_CYAN)}{chars['tl']}{chars['h']*6}{chars['fill_tl']}{chars['h']*10}{chars['fill_tr']}{chars['h']*6}{chars['tr']}",
            f"{self._fgcolor(self.ACCENT_CYAN)}{chars['v']}{chars['fill_m']*11}{chars['v']}",
            f"{self._fgcolor(self.ACCENT_CYAN)}{chars['v']} COMMAND {chars['fill_m']*3} CENTER {chars['fill_m']*4}{chars['v']}",
            f"{self._fgcolor(self.ACCENT_CYAN)}{chars['v']}{chars['fill_m']*11}{chars['v']}",
            f"{self._fgcolor(self.ACCENT_CYAN)}{chars['bl']}{chars['h']*6}{chars['fill_bl']}{chars['h']*10}{chars['fill_br']}{chars['h']*6}{chars['br']}",
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