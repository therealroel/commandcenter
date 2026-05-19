from blessed import Terminal

SPARKLINE_CHARS = '▁▂▃▄▅▆▇█▉'
FUEL_FULL = '█'
FUEL_EMPTY = '░'


class TokenWidget:
    def __init__(self, term: Terminal, history: list[int]):
        self.term = term
        self.history = history

    def _get_color(self, percent: float) -> str:
        if percent < 50:
            return '#00ff88'
        elif percent <= 80:
            return '#ffaa00'
        else:
            return '#ff4444'

    def _build_fuel_bar(self, percent: float, width: int = 10) -> str:
        filled = int(percent * width / 100)
        return FUEL_FULL * filled + FUEL_EMPTY * (width - filled)

    def _build_sparkline(self) -> str:
        if not self.history:
            return ''
        min_val = min(self.history)
        max_val = max(self.history)
        range_val = max_val - min_val
        if range_val == 0:
            range_val = 1
        result = []
        for val in self.history:
            normalized = int((val - min_val) * 8 / range_val)
            normalized = min(8, max(0, normalized))
            result.append(SPARKLINE_CHARS[normalized])
        return ''.join(result)

    def render(self, current: int = None, maximum: int = 100000) -> str:
        if current is None:
            current = self.history[-1] if self.history else 0
        percent = (current / maximum * 100) if maximum > 0 else 0
        color = self._get_color(percent)
        fuel_bar = self._build_fuel_bar(percent)
        sparkline = self._build_sparkline()

        return f'{self.term.color(color)}Context: {percent:.0f}% {fuel_bar} {current:,} / {maximum:,} tokens{self.term.normal}\nTrend: {sparkline}'
