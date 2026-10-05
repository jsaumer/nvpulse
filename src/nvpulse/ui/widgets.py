"""Textual widgets: header bar, animated GPU card, process table."""

from __future__ import annotations

import time
from collections import deque

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.markup import escape as escape_markup
from textual.widget import Widget
from textual.widgets import DataTable

from ..backend.models import GpuSnapshot, ProcessInfo, SystemInfo
from ..sanitize import clean
from . import render as R

HISTORY = 240
OMEGA_MAX = 7.0  # rad/s at 100 % fan; keeps per-frame rotation under the strobe limit


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

    def __init__(self, index: int, animate: bool = True, **kw) -> None:
        super().__init__(**kw)
        self.index = index
        self.animate_enabled = animate
        self.snap: GpuSnapshot | None = None
        self.tw = R.Tween(rate=6.0)
        self.hist: dict[str, deque] = {k: deque(maxlen=HISTORY) for k in ("gpu", "mem", "pwr", "tmp")}
        self.phase = 0.0
        self.t = 0.0
        self.compact = False

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
        if not self.animate_enabled:
            self.tw.snap()

        # border titles are parsed as markup: escape driver-supplied strings
        self.border_title = escape_markup(f" GPU {s.index} · {clean(s.name.replace('NVIDIA ', ''), 48)} ")
        bits = [s.bus_id[-12:] if s.bus_id else ""]
        if s.pstate is not None:
            bits.append(f"P{s.pstate}")
        if s.pcie_gen and s.pcie_width:
            bits.append(f"PCIe {s.pcie_gen}.0 x{s.pcie_width}")
        self.border_subtitle = escape_markup(clean(" " + " · ".join(b for b in bits if b) + " ", 80))
        load = (s.util_gpu or 0) / 100
        self.styles.border = ("round", R.mix("#30363d", R.gradient(R.UTIL_GRAD, load), 0.25 + 0.6 * load))
        self.refresh()

    def set_compact(self, compact: bool) -> None:
        self.compact = compact
        self.set_class(compact, "-compact")
        self.refresh()

    # ---------------------------------------------------------- animation
    def tick(self, dt: float) -> None:
        self.t += dt
        if self.animate_enabled:
            self.tw.step(dt)
            fan = self.tw["fan"] or 0.0
            self.phase = (self.phase + dt * OMEGA_MAX * fan / 100.0) % 1e6
        self.refresh()

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
SORTS = ("vram", "sm", "pid", "gpu")
SORT_LABEL = {"vram": "VRAM", "sm": "SM%", "pid": "PID", "gpu": "GPU"}


class ProcessTable(DataTable):
    DEFAULT_CSS = """
    ProcessTable { background: #0d1117; height: 1fr; }
    ProcessTable > .datatable--header { background: #161b22; color: #8b949e; text-style: bold; }
    ProcessTable > .datatable--cursor { background: #1f6feb 40%; }
    """

    def __init__(self, **kw) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, **kw)
        self.sort_key = "vram"
        self.gpu_totals: dict[int, int] = {}

    def on_mount(self) -> None:
        self.add_column("GPU", key="gpu", width=3)
        self.add_column("PID", key="pid", width=8)
        self.add_column("USER", key="user", width=10)
        self.add_column("TYPE", key="type", width=4)
        self.add_column("SM%", key="sm", width=4)
        self.add_column("VRAM", key="vram", width=21)
        self.add_column("COMMAND", key="cmd")

    def cycle_sort(self) -> str:
        self.sort_key = SORTS[(SORTS.index(self.sort_key) + 1) % len(SORTS)]
        return self.sort_key

    def _sorted(self, procs: list[ProcessInfo]) -> list[ProcessInfo]:
        key = {
            "vram": lambda p: -(p.used_memory or 0),
            "sm": lambda p: -(p.sm_util or -1),
            "pid": lambda p: p.pid,
            "gpu": lambda p: (p.gpu_index, -(p.used_memory or 0)),
        }[self.sort_key]
        return sorted(procs, key=key)

    def update_processes(self, snaps: list[GpuSnapshot]) -> None:
        self.gpu_totals = {s.index: s.mem_total or 0 for s in snaps}
        procs = self._sorted([p for s in snaps for p in s.processes])

        selected = None
        if self.row_count and 0 <= self.cursor_row < self.row_count:
            try:
                selected = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            except Exception:
                selected = None

        self.clear()
        for p in procs:
            total = self.gpu_totals.get(p.gpu_index) or 0
            pct = 100.0 * p.used_memory / total if (p.used_memory is not None and total) else None
            vram = R.gauge(8, pct, R.MEM_GRAD, solid=True)
            vram.append(f" {R.fmt_bytes(p.used_memory):>11}", Style(color=R.TEXT))
            sm = Text(
                _pct(p.sm_util) if p.sm_util is not None else "—", style=R.gradient(R.UTIL_GRAD, (p.sm_util or 0) / 100)
            )
            kind_color = {"C": "#58a6ff", "G": "#d2a8ff", "C+G": "#ffa657"}.get(p.kind, R.TEXT)
            self.add_row(
                Text(str(p.gpu_index), style=R.ACCENT),
                Text(str(p.pid), style=R.TEXT),
                Text(clean(p.user, 10), style=R.LABEL),
                Text(p.kind, style=kind_color),
                sm,
                vram,
                Text(clean(p.cmdline or p.name, 1024), style=R.TEXT, overflow="ellipsis", no_wrap=True),
                key=f"{p.gpu_index}:{p.pid}",
            )
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
