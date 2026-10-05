"""Textual widgets: header bar, animated GPU card, process table."""

from __future__ import annotations

import time
from collections import deque

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from .. import __version__
from ..backend.models import Alerts, GpuSnapshot, ProcessInfo, SystemInfo
from ..sanitize import clean
from . import render as R

HISTORY = 240
OMEGA_MAX = 7.0  # rad/s at 100 % fan; keeps per-frame rotation under the strobe limit
WARN = "#d29922"
ALERT = "#f85149"


def card_title(s: GpuSnapshot, alerts: Alerts | None = None) -> Text:
    """Border title: the GPU name, a badge per active throttle, then per reached alert.

    Returned as ``Text`` so Textual never parses the driver-supplied name as markup.
    (Its ``escape()`` only covers complete ``[tags]``; a name cut off mid-tag would
    swallow the badge markup that follows.)
    """
    title = Text(f" GPU {s.index} · {clean(s.name.replace('NVIDIA ', ''), 48)} ")
    for badge in s.throttle_badges:
        title.append(f" {badge} ", Style(color="#0d1117", bgcolor=ALERT, bold=True))
        title.append(" ")
    for badge in alerts.active(s) if alerts else ():
        title.append(f" {badge} ", Style(color="#0d1117", bgcolor=WARN, bold=True))
        title.append(" ")
    return title


def card_subtitle(s: GpuSnapshot) -> Text:
    """Border subtitle: bus ID, P-state and PCIe link, with a downgrade warning."""
    bits = [clean(s.bus_id[-12:], 32) if s.bus_id else ""]
    if s.pstate is not None:
        bits.append(f"P{s.pstate}")
    out = Text(" " + " · ".join(b for b in bits if b))
    if s.pcie_gen and s.pcie_width:
        if out.plain.strip():
            out.append(" · ")
        link = f"PCIe {s.pcie_gen}.0 x{s.pcie_width}"
        if s.pcie_downgrade:
            out.append(f"{link} ▼ card supports {s.pcie_downgrade}", Style(color=WARN, bold=True))
        else:
            out.append(link)
    out.append(" ")
    return out


# ====================================================================== header
class HeaderBar(Widget):
    DEFAULT_CSS = "HeaderBar { height: 1; background: #161b22; }"

    def __init__(self, info: SystemInfo, **kw) -> None:
        super().__init__(**kw)
        self.info = info
        self.gpu_count = 0
        self.total_power: float | None = None
        self.total_limit: float | None = None
        self.mem_used = 0
        self.mem_total = 0
        self.interval = 1.0
        self.paused = False
        self.as_root = False
        self.read_only = False
        self.t = 0.0

    def set_totals(self, snaps: list[GpuSnapshot]) -> None:
        self.gpu_count = len(snaps)
        powers = [s.power for s in snaps if s.power is not None]
        limits = [s.power_limit for s in snaps if s.power_limit is not None]
        self.total_power = sum(powers) if powers else None
        self.total_limit = sum(limits) if limits else None
        self.mem_used = sum(s.mem_used or 0 for s in snaps)
        self.mem_total = sum(s.mem_total or 0 for s in snaps)

    def render(self) -> Text:
        sep = (" │ ", Style(color="#30363d"))
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(" ∿ nvpulse ", Style(color="#0d1117", bgcolor=R.ACCENT, bold=True))
        t.append(f" v{__version__}", Style(color=R.LABEL))
        t.append("  ")
        t.append("Driver ", Style(color=R.LABEL))
        t.append(self.info.driver_version, Style(color=R.TEXT, bold=True))
        t.append(*sep)
        t.append("CUDA ", Style(color=R.LABEL))
        t.append(self.info.cuda_version, Style(color=R.TEXT, bold=True))
        t.append(*sep)
        t.append(self.info.hostname or "localhost", Style(color=R.TEXT))
        t.append(*sep)
        t.append(f"{self.gpu_count} GPU{'s' if self.gpu_count != 1 else ''}", Style(color=R.TEXT))
        if self.gpu_count > 1:
            t.append(*sep)
            t.append("Σ ", Style(color=R.LABEL))
            if self.total_power is not None:
                t.append(f"{self.total_power:,.0f} W", Style(color="#fbbf24"))
                t.append("  ")
            t.append(f"{R.fmt_gib(self.mem_used, 0)}/{R.fmt_gib(self.mem_total, 0)} GiB", Style(color="#a5b4fc"))

        right = Text(no_wrap=True)
        if self.as_root:
            right.append(" ROOT ", Style(color="#0d1117", bgcolor="#f85149", bold=True))
            right.append(" ")
        if self.read_only:
            right.append(" READ-ONLY ", Style(color="#0d1117", bgcolor="#58a6ff", bold=True))
            right.append(" ")
        if self.paused:
            right.append(" ❚❚ PAUSED ", Style(color="#0d1117", bgcolor="#d29922", bold=True))
        else:
            glow = R.pulse(self.t, 1.6)
            right.append("● ", Style(color=R.mix("#1f6f3f", "#3fb950", glow)))
            right.append("LIVE", Style(color="#3fb950", bold=True))
        right.append(f"  {self.interval:g}s  ", Style(color=R.LABEL))
        right.append(time.strftime("%H:%M:%S") + " ", Style(color=R.TEXT))

        pad = self.size.width - t.cell_len - right.cell_len
        if pad > 0:
            t.append(" " * pad)
        else:
            t.truncate(max(0, self.size.width - right.cell_len - 1), overflow="ellipsis")
            t.append(" ")
        t.append_text(right)
        return t


# ===================================================================== GPU card
class GpuCard(Widget):
    """One GPU: animated fan / heatsink on the left, gauges and sparklines on the right."""

    DEFAULT_CSS = """
    GpuCard {
        height: 11;
        border: round #30363d;
        border-title-color: #e6edf3;
        border-title-style: bold;
        border-subtitle-color: #6e7681;
        padding: 0 1;
        background: #0d1117;
    }
    GpuCard.-compact { height: 7; }
    """

    class Open(Message):
        """The card was clicked: show this GPU's detail view."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, index: int, animate: bool = True, **kw) -> None:
        super().__init__(**kw)
        self.index = index
        self.animate_enabled = animate
        self.snap: GpuSnapshot | None = None
        self.tw = R.Tween(rate=6.0)
        # "t" holds the monotonic time of each sample, for the detail view's time axis
        self.hist: dict[str, deque] = {k: deque(maxlen=HISTORY) for k in ("gpu", "mem", "pwr", "tmp", "t")}
        self.phase = 0.0
        self.t = 0.0
        self.compact = False
        self.alerts: Alerts | None = None
        self.session = ""  # energy drawn since nvpulse started, already formatted

    # -------------------------------------------------------------- data in
    def update_snapshot(self, s: GpuSnapshot) -> None:
        self.snap = s
        self.tw.set("gpu", s.util_gpu)
        self.tw.set("mem", s.mem_pct)
        self.tw.set("mem_used", s.mem_used)
        self.tw.set("pwr", s.power_pct)
        self.tw.set("pwr_w", s.power)
        self.tw.set("tmp", s.temp)
        self.tw.set("fan", s.fan)
        self.tw.set("sm", s.clock_sm)
        self.hist["gpu"].append(s.util_gpu)
        self.hist["mem"].append(s.mem_pct)
        self.hist["pwr"].append(s.power_pct)
        self.hist["tmp"].append(s.temp)
        self.hist["t"].append(time.monotonic())
        if not self.animate_enabled:
            self.tw.snap()

        # str border titles are parsed as markup; these are Text, which is not
        self.border_title = card_title(s, self.alerts)
        self.border_subtitle = card_subtitle(s)
        load = (s.util_gpu or 0) / 100
        self.styles.border = ("round", R.mix(R.BORDER, R.gradient(R.UTIL_GRAD, load), 0.25 + 0.6 * load))
        self.refresh()

    def on_click(self) -> None:
        self.post_message(self.Open(self.index))

    def set_compact(self, compact: bool) -> None:
        self.compact = compact
        self.set_class(compact, "-compact")
        self.refresh()

    # ---------------------------------------------------------- animation
    def tick(self, dt: float) -> None:
        self.t += dt
        if not self.animate_enabled:
            return  # nothing moves between polls; update_snapshot() repaints
        easing = self.tw.step(dt)
        fan = self.tw["fan"] or 0.0
        self.phase = (self.phase + dt * OMEGA_MAX * fan / 100.0) % 1e6
        # An idle card with stopped fans looks the same frame after frame: skip the repaint.
        if easing or fan > 0.5 or self._pulsing():
            self.refresh()

    def _pulsing(self) -> bool:
        """Is something on the card animated by time alone (heat shimmer, hot glow)?"""
        s = self.snap
        if s is None or s.temp is None:
            return False
        shimmer = s.fan is None and (s.temp - 40) / 45 > 0.2  # see heatsink_art()
        hot = s.temp_slowdown is not None and s.temp >= s.temp_slowdown - 10
        return shimmer or hot

    # -------------------------------------------------------------- render
    def _metric_row(self, label: str, bar: Text, value: str, value_w: int, spark: Text | None) -> Text:
        row = Text(no_wrap=True, overflow="crop")
        row.append(f"{label:<4}", Style(color=R.LABEL, bold=True))
        row.append_text(bar)
        row.append(f" {value:>{value_w}}", Style(color=R.TEXT, bold=True))
        if spark is not None and spark.cell_len:
            row.append(" ")
            row.append_text(spark)
        return row

    def _left_art(self, fw: int, fh: int) -> list[Text]:
        s = self.snap
        assert s is not None
        fan = self.tw["fan"]
        if s.fan is None:
            temp = self.tw["tmp"] or 0
            heat = max(0.0, min(1.0, (temp - 40) / 45))
            return R.heatsink_art(fw, fh, self.t, heat, R.gradient(R.HEAT_GRAD, (temp - 20) / 80))
        f = (fan or 0.0) / 100.0
        return R.fan_art(
            fw,
            fh,
            self.phase,
            speed=f if self.animate_enabled else 0.0,
            blade_color=R.gradient(R.FAN_GRAD, f),
        )

    def _fan_caption(self, width: int) -> Text:
        s = self.snap
        assert s is not None
        t = Text(no_wrap=True, overflow="crop")
        if s.fan is None:
            t.append("passive", Style(color=R.DIM, italic=True))
        else:
            t.append("FAN ", Style(color=R.LABEL, bold=True))
            if len(s.fans) > 1 and width >= 4 + 5 * len(s.fans):
                t.append(" ".join(f"{v:.0f}%" for v in s.fans), Style(color=R.TEXT))
            else:
                t.append(f"{self.tw['fan'] or 0:.0f}%", Style(color=R.TEXT))
        return _center(t, width)

    def render(self):
        s = self.snap
        if s is None:
            return Text("waiting for data…", style=R.DIM)
        W = self.size.width
        compact = self.compact
        fw, fh = (8, 4) if compact else (14, 7)
        if W < 40:  # very narrow: drop the art
            fw = 0
        right_w = max(10, W - fw - 2) if fw else W

        value_w = 11
        avail = right_w - 4 - 1 - value_w
        if avail >= 36:
            gw = int((avail - 1) * 0.55)
            sw = avail - 1 - gw
        else:
            gw, sw = max(4, avail), 0

        tw = self.tw
        temp = tw["tmp"]
        hot = s.temp_slowdown is not None and temp is not None and temp >= s.temp_slowdown - 10
        glow = R.pulse(self.t, 0.9) if hot and self.animate_enabled else (0.6 if hot else 0.0)
        t_max = float(s.temp_shutdown or 100) if s.temp_shutdown else 100.0

        def spark(key: str, stops, vmax=100.0) -> Text | None:
            return R.sparkline(self.hist[key], sw, stops, vmax) if sw else None

        mem_val = R.fmt_mem_pair(tw["mem_used"], s.mem_total)
        pwr_val = (
            f"{tw['pwr_w']:.0f}/{s.power_limit:.0f}W"
            if tw["pwr_w"] is not None and s.power_limit
            else (f"{tw['pwr_w']:.0f}W" if tw["pwr_w"] is not None else "n/a")
        )
        rows = [
            self._metric_row(
                "GPU", R.gauge(gw, tw["gpu"], R.UTIL_GRAD), _pct(tw["gpu"]), value_w, spark("gpu", R.UTIL_GRAD)
            ),
            self._metric_row("MEM", R.gauge(gw, tw["mem"], R.MEM_GRAD), mem_val, value_w, spark("mem", R.MEM_GRAD)),
            self._metric_row("PWR", R.gauge(gw, tw["pwr"], R.POWER_GRAD), pwr_val, value_w, spark("pwr", R.POWER_GRAD)),
            self._metric_row(
                "TMP",
                R.heat_bar(gw, temp, t_max=t_max, slowdown=s.temp_slowdown, glow=glow),
                f"{temp:.0f}°C" if temp is not None else "n/a",
                value_w,
                spark("tmp", R.HEAT_GRAD, vmax=t_max),
            ),
        ]
        detail = self._detail_lines(right_w, compact)
        if compact:
            right = rows + detail[:1]
        else:
            right = [*rows, Text(""), *detail]

        n_lines = fh + 1 if fw else len(right)
        n_lines = max(n_lines, len(right))
        art = [*self._left_art(fw, fh), self._fan_caption(fw)] if fw else []

        lines = []
        for i in range(n_lines):
            line = Text(no_wrap=True, overflow="crop")
            if fw:
                line.append_text(art[i] if i < len(art) else Text(" " * fw))
                line.append("  ")
            if i < len(right):
                line.append_text(right[i])
            lines.append(line)
        return Group(*lines)

    def _detail_lines(self, width: int, compact: bool) -> list[Text]:
        s = self.snap
        assert s is not None
        lab = Style(color=R.LABEL)
        val = Style(color=R.TEXT)
        dim = Style(color=R.DIM)

        clocks = Text(no_wrap=True, overflow="ellipsis")
        sm = self.tw["sm"]
        clocks.append("SM ", lab)
        clocks.append(f"{sm:.0f}" if sm is not None else "n/a", val)
        if s.clock_sm_max:
            clocks.append(f"/{s.clock_sm_max}", dim)
        clocks.append(" MHz", dim)
        clocks.append("   MEM ", lab)
        clocks.append(f"{s.clock_mem}" if s.clock_mem is not None else "n/a", val)
        clocks.append(" MHz", dim)

        engines = Text(no_wrap=True, overflow="ellipsis")
        engines.append("ENC ", lab)
        engines.append(_pct(s.enc_util), val)
        if s.enc_sessions:
            engines.append(f" ({s.enc_sessions} session{'s' if s.enc_sessions != 1 else ''}", dim)
            engines.append(f" · {s.enc_fps} fps)" if s.enc_fps else ")", dim)
        engines.append("   DEC ", lab)
        engines.append(_pct(s.dec_util), val)
        engines.append("   MEM BUS ", lab)
        engines.append(_pct(s.util_mem), val)

        procs = Text(no_wrap=True, overflow="ellipsis")
        n = len(s.processes)
        procs.append(f"{n} process{'es' if n != 1 else ''}", val)
        pm = [p.used_memory for p in s.processes if p.used_memory is not None]
        if pm:
            procs.append(f" · {R.fmt_gib(sum(pm))} GiB", dim)
        if s.persistence is not None:
            procs.append("   persistence ", lab)
            procs.append("on" if s.persistence else "off", val)
        if self.session:
            procs.append("   session ", lab)
            procs.append(self.session, val)

        if compact:
            one = Text(no_wrap=True, overflow="ellipsis")
            one.append("SM ", lab)
            one.append(f"{sm:.0f}" if sm is not None else "n/a", val)
            one.append(" MHz", dim)
            one.append(" · ", dim)
            one.append(f"{n} proc", val)
            if s.enc_util or s.dec_util:
                one.append(" · ", dim)
                one.append(f"enc {_pct(s.enc_util)} dec {_pct(s.dec_util)}", dim)
            return [one]
        return [clocks, engines, procs]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0f}%"


def _center(t: Text, width: int) -> Text:
    t = t.copy()
    t.rstrip()
    left = max(0, (width - t.cell_len) // 2)
    out = Text(" " * left, no_wrap=True, overflow="crop")
    out.append_text(t)
    out.append(" " * max(0, width - out.cell_len))
    out.truncate(width)
    return out


# =============================================================== process table
SORTS = ("vram", "sm", "pid", "gpu", "unit")
SORT_LABEL = {"vram": "VRAM", "sm": "SM%", "pid": "PID", "gpu": "GPU", "unit": "UNIT"}
# key -> (header, width). The command column is not here: it takes whatever is left.
COLUMN_SPECS = {
    "gpu": ("GPU", 3),
    "pid": ("PID", 8),
    "user": ("USER", 10),
    "type": ("TYPE", 4),
    "sm": ("SM%", 4),
    "vram": ("VRAM", 21),
    "unit": ("UNIT", 19),
}
MIN_CMD = 16
FILTER_FIELDS = ("user", "gpu", "unit", "pid", "type")
MAX_FILTER = 80


def parse_filter(text: str) -> list[tuple[str, str]]:
    """Split a filter line into (field, needle) terms; field "" searches name and command."""
    terms = []
    for token in text[:MAX_FILTER].lower().split():
        field, sep, needle = token.partition(":")
        if sep and field in FILTER_FIELDS and needle:
            terms.append((field, needle))
        else:
            terms.append(("", token))
    return terms


def matches(p: ProcessInfo, terms: list[tuple[str, str]]) -> bool:
    """Every term must match. ``gpu:`` and ``pid:`` compare exactly, the rest by substring."""
    for field, needle in terms:
        if field == "gpu":
            ok = str(p.gpu_index) == needle
        elif field == "pid":
            ok = str(p.pid) == needle
        elif field == "type":
            ok = p.kind.lower() == needle
        elif field in ("user", "unit"):
            ok = needle in getattr(p, field).lower()
        else:
            ok = needle in f"{p.name} {p.cmdline}".lower()
        if not ok:
            return False
    return True


class ProcessTable(DataTable):
    DEFAULT_CSS = """
    ProcessTable { background: #0d1117; height: 1fr; }
    ProcessTable > .datatable--header { background: #161b22; color: #8b949e; text-style: bold; }
    ProcessTable > .datatable--cursor { background: #1f6feb 40%; }
    """

    # DataTable binds enter itself (hidden); rebind it so the footer shows what it does here
    BINDINGS = [Binding("enter", "select_cursor", "Detail")]

    class OpenDetail(Message):
        """Enter was pressed in the table."""

    def __init__(self, **kw) -> None:
        # "renderable" keeps each cell's own colours on the cursor row; the default
        # repaints everything in the cursor foreground and whites out the VRAM gauge
        super().__init__(cursor_type="row", zebra_stripes=True, cursor_foreground_priority="renderable", **kw)
        self.sort_key = "vram"
        self.hide_graphics = False
        self.hidden = 0  # rows left out by hide_graphics
        self.filter_text = ""
        self.filtered = 0  # rows left out by the filter
        self.hidden_columns: frozenset[str] = frozenset()
        self.gpu_totals: dict[int, int] = {}
        self._snaps: list[GpuSnapshot] = []
        self._layout: tuple[tuple[str, ...], int] = ((), 0)  # column keys and command width in use
        self._shown: dict[str, tuple[Text, ...]] = {}  # row key -> cells currently in the table

    def action_select_cursor(self) -> None:
        self.post_message(self.OpenDetail())

    def on_resize(self) -> None:
        self.update_processes(self._snaps)  # the command column follows the width

    def cycle_sort(self) -> str:
        self.sort_key = SORTS[(SORTS.index(self.sort_key) + 1) % len(SORTS)]
        return self.sort_key

    def _sorted(self, procs: list[ProcessInfo]) -> list[ProcessInfo]:
        key = {
            "vram": lambda p: -(p.used_memory or 0),
            "sm": lambda p: -(p.sm_util or -1),
            "pid": lambda p: p.pid,
            "gpu": lambda p: (p.gpu_index, -(p.used_memory or 0)),
            # grouped by container / service, the unlabelled rest last
            "unit": lambda p: (not p.unit, p.unit, -(p.used_memory or 0)),
        }[self.sort_key]
        return sorted(procs, key=key)

    def _plan(self, procs: list[ProcessInfo]) -> tuple[tuple[str, ...], int]:
        """Which columns to show and how wide the command column can be without scrolling."""
        keys = [k for k in COLUMN_SPECS if k not in self.hidden_columns]
        if "unit" in keys and not any(p.unit for p in procs):
            keys.remove("unit")  # nothing to say on a box without containers or services
        pad = 2 * self.cell_padding

        def room() -> int:
            used = sum(COLUMN_SPECS[k][1] + pad for k in keys)
            return self.size.width - 2 - used - pad if self.size.width else 60  # 2: vertical scrollbar

        if room() < MIN_CMD and "unit" in keys:
            keys.remove("unit")  # too narrow for both: the command matters more
        return (*keys, "cmd"), max(MIN_CMD, room())

    def _cells(self, p: ProcessInfo, columns: tuple[str, ...], cmd_width: int) -> tuple[Text, ...]:
        total = self.gpu_totals.get(p.gpu_index) or 0
        pct = 100.0 * p.used_memory / total if (p.used_memory is not None and total) else None
        vram = R.gauge(8, pct, R.MEM_GRAD, solid=True)
        vram.append(f" {R.fmt_bytes(p.used_memory):>11}", Style(color=R.TEXT))
        sm = Text(
            _pct(p.sm_util) if p.sm_util is not None else "—", style=R.gradient(R.UTIL_GRAD, (p.sm_util or 0) / 100)
        )
        kind_color = {"C": "#58a6ff", "G": "#d2a8ff", "C+G": "#ffa657"}.get(p.kind, R.TEXT)
        cmd = Text(clean(p.cmdline or p.name, 1024), style=R.TEXT, no_wrap=True)
        cmd.truncate(cmd_width, overflow="ellipsis")  # the full line is on the info screen (i)
        cells = {
            "gpu": Text(str(p.gpu_index), style=R.ACCENT),
            "pid": Text(str(p.pid), style=R.TEXT),
            "user": Text(clean(p.user, 10), style=R.LABEL),
            "type": Text(p.kind, style=kind_color),
            "sm": sm,
            "vram": vram,
            "unit": Text(clean(p.unit, 19), style="#79c0ff"),
            "cmd": cmd,
        }
        return tuple(cells[c] for c in columns)

    def update_processes(self, snaps: list[GpuSnapshot]) -> None:
        self._snaps = snaps
        self.gpu_totals = {s.index: s.mem_total or 0 for s in snaps}
        procs = [p for s in snaps for p in s.processes]
        shown = [p for p in procs if p.kind != "G"] if self.hide_graphics else procs
        self.hidden = len(procs) - len(shown)
        terms = parse_filter(self.filter_text)
        kept = [p for p in shown if matches(p, terms)] if terms else shown
        self.filtered = len(shown) - len(kept)
        procs = self._sorted(kept)

        layout = self._plan(procs)
        columns, cmd_width = layout
        rows = {f"{p.gpu_index}:{p.pid}": self._cells(p, columns, cmd_width) for p in procs}

        # Same processes in the same order (the usual case): touch only the cells that
        # changed. A rebuild re-renders every visible row and resets the scroll position,
        # which costs real CPU on a desktop with dozens of graphics clients.
        if layout == self._layout and list(rows) == list(self._shown):
            for key, cells in rows.items():
                for col, old, new in zip(columns, self._shown[key], cells, strict=True):
                    if new != old:
                        self.update_cell(key, col, new)
            self._shown = rows
            return

        selected = None
        if self.row_count and 0 <= self.cursor_row < self.row_count:
            try:
                selected = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            except Exception:
                selected = None

        if layout != self._layout:
            self.clear(columns=True)
            for key in columns[:-1]:
                label, width = COLUMN_SPECS[key]
                self.add_column(label, key=key, width=width)
            self.add_column("COMMAND", key="cmd", width=cmd_width)
            self._layout = layout
        else:
            self.clear()
        for key, cells in rows.items():
            self.add_row(*cells, key=key)
        self._shown = rows
        if selected is not None:
            try:
                self.move_cursor(row=self.get_row_index(selected), animate=False)
            except Exception:
                pass

    def selected_process(self) -> tuple[int, int] | None:
        if not self.row_count:
            return None
        try:
            key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
        except Exception:
            return None
        gpu, pid = key.split(":")
        return int(gpu), int(pid)
