"""Pure rendering helpers (no Textual dependency) — gradients, bars, sparklines, fan art.

Everything returns ``rich.text.Text`` so it can be composed by widgets and unit-tested.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from functools import lru_cache
from itertools import pairwise

from rich.style import Style
from rich.text import Text

# ---------------------------------------------------------------- palette
TRACK = "#252b35"
DIM = "#6e7681"
LABEL = "#8b949e"
TEXT = "#e6edf3"
ACCENT = "#76b900"  # NVIDIA green
RING = "#3d4654"
HUB = "#d0d7de"
BORDER = "#30363d"

_DEFAULT_PALETTE = {"TRACK": TRACK, "DIM": DIM, "LABEL": LABEL, "TEXT": TEXT, "RING": RING, "BORDER": BORDER}
_THEMES = {
    "default": {},
    # brighter secondary text and a lighter track, for washed-out displays and projectors
    "high-contrast": {
        "TRACK": "#3b4552",
        "DIM": "#b1bac4",
        "LABEL": "#d0d7de",
        "TEXT": "#ffffff",
        "RING": "#8b949e",
        "BORDER": "#8b949e",
    },
    "mono": {},  # colour is removed by Textual's NO_COLOR handling, not by the palette
}


def set_theme(name: str) -> None:
    """Switch the neutral colours. Call before the app starts; callers read them at draw time."""
    globals().update({**_DEFAULT_PALETTE, **_THEMES[name]})


Stops = Sequence[tuple[float, str]]

UTIL_GRAD: Stops = ((0.0, "#2dd4bf"), (0.45, "#a3e635"), (0.7, "#facc15"), (0.85, "#fb923c"), (1.0, "#ef4444"))
MEM_GRAD: Stops = ((0.0, "#38bdf8"), (0.5, "#818cf8"), (0.8, "#c084fc"), (1.0, "#f472b6"))
POWER_GRAD: Stops = ((0.0, "#fde68a"), (0.55, "#fbbf24"), (0.8, "#fb923c"), (1.0, "#f43f5e"))
HEAT_GRAD: Stops = (
    (0.0, "#3b82f6"),
    (0.25, "#06b6d4"),
    (0.45, "#22c55e"),
    (0.62, "#eab308"),
    (0.78, "#f97316"),
    (0.9, "#ef4444"),
    (1.0, "#ff2d75"),
)
FAN_GRAD: Stops = ((0.0, "#64748b"), (0.25, "#22d3ee"), (0.65, "#a78bfa"), (1.0, "#f472b6"))

EIGHTHS = " ▏▎▍▌▋▊▉█"
SPARKS = " ▁▂▃▄▅▆▇█"


# --------------------------------------------------------------- colours
@lru_cache(maxsize=4096)
def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in rgb))


def mix(a: str, b: str, t: float) -> str:
    """Linear blend between two hex colours."""
    t = max(0.0, min(1.0, t))
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb, strict=True)))


def gradient(stops: Stops, t: float) -> str:
    """Colour at position ``t`` (0..1) along a multi-stop gradient."""
    t = max(0.0, min(1.0, t))
    # quantise so the lru caches in rich stay small and hot
    t = round(t * 64) / 64
    return _gradient_q(tuple(stops), t)


@lru_cache(maxsize=4096)
def _gradient_q(stops: tuple, t: float) -> str:
    for (p0, c0), (p1, c1) in pairwise(stops):
        if t <= p1:
            span = (p1 - p0) or 1.0
            return mix(c0, c1, (t - p0) / span)
    return stops[-1][1]


def pulse(t: float, period: float = 1.2) -> float:
    """Smooth 0..1 oscillation."""
    return 0.5 + 0.5 * math.sin(t * math.tau / period)


# ---------------------------------------------------------------- formatting
def fmt_gib(b: int | float | None, digits: int = 1) -> str:
    if b is None:
        return "n/a"
    return f"{b / 1024**3:.{digits}f}"


def fmt_mem_pair(used: float | None, total: float | None) -> str:
    if used is None or not total:
        return "n/a"
    digits = 0 if total >= 100 * 1024**3 else 1
    return f"{fmt_gib(used, digits)}/{fmt_gib(total, 0)}G"


def fmt_bytes(b: int | float | None) -> str:
    if b is None:
        return "n/a"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(b) < 1024 or unit == "TiB":
            return f"{b:.0f} {unit}" if unit in ("B", "KiB", "MiB") else f"{b:.1f} {unit}"
        b /= 1024
    return "n/a"  # pragma: no cover


def fmt_rate(kb_per_s: float | None) -> str:
    """NVML reports PCIe throughput in KB/s."""
    if kb_per_s is None:
        return "n/a"
    if kb_per_s < 1000:
        return f"{kb_per_s:.0f} KB/s"
    if kb_per_s < 1_000_000:
        return f"{kb_per_s / 1000:.1f} MB/s"
    return f"{kb_per_s / 1_000_000:.2f} GB/s"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def fmt_session_energy(wh: float | None, cost_per_kwh: float | None = None, currency: str = "$") -> str:
    """Energy drawn while nvpulse has been watching, with its cost when a rate is set."""
    if wh is None:
        return "n/a"
    text = f"{wh / 1000:.2f} kWh" if wh >= 1000 else f"{wh:.1f} Wh"
    if cost_per_kwh is not None:
        text += f" ({currency}{wh / 1000 * cost_per_kwh:.2f})"
    return text


def fmt_energy(joules: float | None) -> str:
    if joules is None:
        return "n/a"
    kwh = joules / 3.6e6
    return f"{kwh:.2f} kWh" if kwh >= 0.1 else f"{joules / 3600:.1f} Wh"


# --------------------------------------------------------------------- bars
def gauge(width: int, pct: float | None, stops: Stops, *, track: str = TRACK, solid: bool = False) -> Text:
    """Horizontal bar with per-cell gradient and 1/8-cell precision.

    ``solid`` draws filled cells as foreground "█" instead of background-coloured
    spaces (needed inside DataTable, which repaints cell backgrounds).
    """
    text = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return text
    if pct is None:
        text.append("╌" * width, Style(color=DIM, bgcolor=track))
        return text
    frac = max(0.0, min(1.0, pct / 100.0))
    eighths = round(frac * width * 8)
    full, part = divmod(eighths, 8)
    for i in range(width):
        color = gradient(stops, (i + 0.5) / width)
        if i < full:
            text.append("█" if solid else " ", Style(color=color, bgcolor=track) if solid else Style(bgcolor=color))
        elif i == full and part:
            text.append(EIGHTHS[part], Style(color=color, bgcolor=track))
        else:
            text.append("█" if solid else " ", Style(color=track) if solid else Style(bgcolor=track))
    return text


def heat_bar(
    width: int,
    temp: float | None,
    *,
    t_min: float = 20.0,
    t_max: float = 100.0,
    slowdown: float | None = None,
    glow: float = 0.0,
    track: str = TRACK,
) -> Text:
    """Temperature bar: colour shows absolute heat, marker at the slowdown threshold.

    ``glow`` (0..1) brightens the head of the bar — used for the hot-GPU pulse.
    """
    text = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return text
    if temp is None:
        text.append("╌" * width, Style(color=DIM, bgcolor=track))
        return text
    span = max(1.0, t_max - t_min)
    frac = max(0.0, min(1.0, (temp - t_min) / span))
    eighths = round(frac * width * 8)
    full, part = divmod(eighths, 8)
    head = full if part else full - 1
    marker = None
    if slowdown is not None:
        marker = int(max(0.0, min(0.999, (slowdown - t_min) / span)) * width)
    for i in range(width):
        color = gradient(HEAT_GRAD, (i + 0.5) / width)
        if glow and i == head:
            color = mix(color, "#ffffff", glow * 0.65)
        if i < full:
            text.append(" ", Style(bgcolor=color))
        elif i == full and part:
            text.append(EIGHTHS[part], Style(color=color, bgcolor=track))
        elif i == marker:
            text.append("┃", Style(color="#7f1d1d", bgcolor=track))
        else:
            text.append(" ", Style(bgcolor=track))
    return text


def sparkline(values: Iterable[float | None], width: int, stops: Stops, vmax: float = 100.0) -> Text:
    """Single-row history graph, newest value on the right."""
    text = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return text
    vals = list(values)[-width:]
    # dotted lead-in until the history fills, so the graph area doesn't look broken
    text.append("·" * (width - len(vals)), Style(color=TRACK))
    for v in vals:
        if v is None:
            text.append("·", Style(color=DIM))
            continue
        f = max(0.0, min(1.0, v / vmax)) if vmax else 0.0
        idx = max(1, round(f * 8)) if v > 0 else 0
        text.append(SPARKS[idx] if idx else "▁", Style(color=gradient(stops, f) if idx else TRACK))
    return text


def time_axis(width: int, span: float) -> Text:
    """A ruler for ``history_graph``: how long ago the left edge and the middle were."""
    text = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return text
    left, mid, right = f"-{fmt_duration(span)}", f"-{fmt_duration(span / 2)}", "now"
    if span <= 0 or width < len(left) + len(mid) + len(right) + 6:
        text.append(" " * max(0, width - len(right)) + right[:width], Style(color=DIM))
        return text
    fill = width - len(left) - len(mid) - len(right) - 4
    a = fill // 2
    text.append(f"{left} {'┄' * a} {mid} {'┄' * (fill - a)} {right}", Style(color=DIM))
    return text


def stats(values: Iterable[float | None]) -> tuple[float, float, float] | None:
    """(min, mean, max) of the readings present, or None when there are none."""
    vals = [v for v in values if v is not None]
    return (min(vals), sum(vals) / len(vals), max(vals)) if vals else None


# ------------------------------------------------------------- braille fan
_BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # [row][col]


def history_graph(
    values: Iterable[float | None], width: int, height: int, stops: Stops, vmax: float = 100.0
) -> list[Text]:
    """Multi-row area graph on a braille canvas, newest value on the right.

    Each cell holds two samples across and four levels down, so a ``width`` × ``height``
    graph shows ``2 * width`` samples at ``4 * height`` levels. Rows are coloured by
    their position on the gradient, so tall peaks reach the hot end.
    """
    if width <= 0 or height <= 0:
        return []
    bits = [[0] * width for _ in range(height)]
    vals = list(values)[-width * 2 :]
    offset = width * 2 - len(vals)
    levels = height * 4
    for i, v in enumerate(vals):
        if v is None:
            continue
        f = max(0.0, min(1.0, v / vmax)) if vmax else 0.0
        cx, bx = divmod(offset + i, 2)
        for y in range(max(1, round(f * levels))):  # at least the baseline dot
            cy, by = divmod(levels - 1 - y, 4)
            bits[cy][cx] |= _BRAILLE_BITS[by][bx]
    lead = offset // 2  # cells with no history yet: a faint baseline, as in sparkline()
    lines = []
    for cy in range(height):
        line = Text(no_wrap=True, overflow="crop")
        cells = "".join(chr(0x2800 + b) if b else " " for b in bits[cy])
        if cy == height - 1 and lead:
            line.append("⣀" * lead, Style(color=TRACK))
            cells = cells[lead:]
        line.append(cells, Style(color=gradient(stops, (height - cy - 0.5) / height)))
        lines.append(line)
    return lines


@lru_cache(maxsize=32)
def _polar_grid(w_cells: int, h_cells: int) -> tuple:
    """Pre-compute (r_norm, theta) for each braille dot of a w×h cell canvas."""
    W, H = w_cells * 2, h_cells * 4
    cx, cy = (W - 1) / 2, (H - 1) / 2
    R = min(W, H) / 2 - 0.25
    grid = []
    for y in range(H):
        row = []
        for x in range(W):
            dx, dy = x - cx, y - cy
            row.append((math.hypot(dx, dy) / R, math.atan2(dy, dx)))
        grid.append(tuple(row))
    return tuple(grid), R


def fan_art(
    w_cells: int,
    h_cells: int,
    phase: float,
    *,
    speed: float = 0.0,
    blades: int = 7,
    blade_color: str = "#22d3ee",
    ring_color: str = RING,
    hub_color: str = HUB,
) -> list[Text]:
    """Draw a spinning axial fan on a braille canvas.

    ``phase`` is the rotation angle (radians). ``speed`` (0..1) widens the blades with
    a motion-blur smear so fast fans read as fast instead of strobing.
    """
    grid, R = _polar_grid(w_cells, h_cells)
    sector = math.tau / blades
    blade_w = 0.46 + 0.18 * speed
    smear = [0.0] + ([-0.12 * speed, -0.24 * speed] if speed > 0.05 else [])
    ring_in = 1.0 - 1.15 / R
    hub_r = 0.26
    curve = 1.1

    cells_bits = [[0] * w_cells for _ in range(h_cells)]
    cells_kind = [[0] * w_cells for _ in range(h_cells)]  # 0 none 1 ring 2 blade 3 hub

    for y, row in enumerate(grid):
        cy, by = divmod(y, 4)
        for x, (r, th) in enumerate(row):
            if r > 1.0:
                continue
            kind = 0
            if r >= ring_in:
                kind = 1
            elif r <= hub_r:
                # hub: solid disc with a dark centre dot for a bit of depth
                kind = 3 if r > 0.08 else 0
            else:
                for s in smear:
                    a = (th - phase - s + curve * r) % sector
                    if a < sector * blade_w:
                        kind = 2
                        break
            if kind:
                cx, bx = divmod(x, 2)
                cells_bits[cy][cx] |= _BRAILLE_BITS[by][bx]
                if kind > cells_kind[cy][cx] or (kind == 2 and cells_kind[cy][cx] == 1):
                    cells_kind[cy][cx] = kind if cells_kind[cy][cx] != 3 else 3

    colors = {1: ring_color, 2: blade_color, 3: hub_color}
    lines = []
    for cy in range(h_cells):
        t = Text(no_wrap=True, overflow="crop")
        for cx in range(w_cells):
            bits = cells_bits[cy][cx]
            kind = cells_kind[cy][cx]
            t.append(chr(0x2800 + bits) if bits else " ", Style(color=colors.get(kind, DIM)))
        lines.append(t)
    return lines


def heatsink_art(w_cells: int, h_cells: int, t: float, heat: float, fin_color: str) -> list[Text]:
    """Passive heatsink: vertical fins with rising heat shimmer above them.

    ``heat`` (0..1) controls how much shimmer is drawn.
    """
    W, H = w_cells * 2, h_cells * 4
    haze_rows = max(2, H // 3)
    cells = [[0] * w_cells for _ in range(h_cells)]
    kinds = [[0] * w_cells for _ in range(h_cells)]  # 1 fin, 2 haze
    step = int(t * 6)
    for y in range(H):
        for x in range(W):
            on, kind = False, 0
            if y >= haze_rows:
                on, kind = (x % 2 == 0) or y == H - 1, 1
            elif heat > 0.2:
                # deterministic sparkle drifting upward
                seed = (x * 7 + (y + step) * 13 + (x * y) % 5) % 11
                on, kind = seed < heat * 3.2, 2
            if on:
                cy, by = divmod(y, 4)
                cx, bx = divmod(x, 2)
                cells[cy][cx] |= _BRAILLE_BITS[by][bx]
                kinds[cy][cx] = max(kinds[cy][cx], kind)
    haze = mix(fin_color, "#ffffff", 0.35)
    lines = []
    for cy in range(h_cells):
        line = Text(no_wrap=True, overflow="crop")
        for cx in range(w_cells):
            bits = cells[cy][cx]
            color = fin_color if kinds[cy][cx] == 1 else haze
            line.append(chr(0x2800 + bits) if bits else " ", Style(color=color))
        lines.append(line)
    return lines


# ----------------------------------------------------------------- tweening
class Tween:
    """Exponential easing of a set of named values toward their latest targets."""

    def __init__(self, rate: float = 7.0) -> None:
        self.rate = rate
        self.value: dict[str, float | None] = {}
        self.target: dict[str, float | None] = {}

    def set(self, key: str, target: float | None) -> None:
        self.target[key] = target
        if target is None:
            self.value[key] = None
        elif self.value.get(key) is None:
            self.value[key] = target

    def step(self, dt: float) -> bool:
        """Advance every value; returns whether any of them is still moving.

        A value within 0.1 % of its target lands on it, so easing ends and the
        caller can stop repainting instead of chasing an asymptote forever.
        """
        k = 1.0 - math.exp(-self.rate * max(0.0, dt))
        moving = False
        for key, tgt in self.target.items():
            cur = self.value.get(key)
            if tgt is None or cur is None or cur == tgt:
                continue
            nxt = cur + (tgt - cur) * k
            if abs(tgt - nxt) <= 1e-3 * max(1.0, abs(tgt)):
                nxt = tgt
            self.value[key] = nxt
            moving = True
        return moving

    def snap(self) -> None:
        self.value.update(self.target)

    def __getitem__(self, key: str) -> float | None:
        return self.value.get(key)
