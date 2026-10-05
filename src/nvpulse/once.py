"""``nvpulse --once``: print one snapshot and exit.

For SSH one-liners, login banners and quick looks: the same numbers as the
dashboard, as plain lines. Colour is used on a terminal and dropped when piped.
Process text goes through the same cleaning and redaction as the dashboard.
"""

from __future__ import annotations

import shutil
import sys
import time

from rich.console import Console
from rich.style import Style
from rich.text import Text

from . import __version__
from .backend.models import Alerts, Backend, GpuSnapshot
from .procinfo import enrich
from .sanitize import clean
from .ui import render as R
from .ui.widgets import ALERT, WARN

BAR = 24


def bar(pct: float | None, stops: R.Stops, width: int = BAR) -> Text:
    """A gauge that still reads without colour: filled █, empty ░."""
    text = Text(no_wrap=True)
    if pct is None:
        text.append("╌" * width, Style(color=R.DIM))
        return text
    filled = round(max(0.0, min(1.0, pct / 100.0)) * width)
    for i in range(width):
        on = i < filled
        text.append("█" if on else "░", Style(color=R.gradient(stops, (i + 0.5) / width) if on else R.DIM))
    return text


def _row(label: str, pct: float | None, stops: R.Stops, value: str) -> Text:
    t = Text("  ", no_wrap=True)
    t.append(f"{label:<4}", Style(color=R.LABEL, bold=True))
    t.append_text(bar(pct, stops))
    t.append(f" {value}", Style(color=R.TEXT, bold=True))
    return t


def gpu_lines(s: GpuSnapshot, alerts: Alerts | None = None) -> list[Text]:
    # driver strings are cleaned here as well: a backend may hand them over raw
    name = clean(s.name.replace("NVIDIA ", ""), 48)
    head = Text(f"GPU {s.index} · {name}", style=Style(color=R.TEXT, bold=True), no_wrap=True)
    for badge in s.throttle_badges:
        head.append(f"  [{badge}]", Style(color=ALERT, bold=True))
    for badge in alerts.active(s) if alerts else ():
        head.append(f"  [{badge}]", Style(color=WARN, bold=True))
    bits = [clean(s.bus_id[-12:], 32)] if s.bus_id else []
    if s.pstate is not None:
        bits.append(f"P{s.pstate}")
    if s.pcie_gen and s.pcie_width:
        bits.append(f"PCIe {s.pcie_gen}.0 x{s.pcie_width}")
    head.append("   " + " · ".join(bits), Style(color=R.DIM))
    if s.pcie_downgrade:
        head.append(f" (card supports {s.pcie_downgrade})", Style(color=WARN))

    temp_pct = None if s.temp is None else 100.0 * (s.temp - 20) / max(1.0, (s.temp_shutdown or 100) - 20)
    power = (
        f"{s.power:.0f}/{s.power_limit:.0f} W"
        if s.power is not None and s.power_limit
        else ("n/a" if s.power is None else f"{s.power:.0f} W")
    )
    if s.fan is None:
        fan = "passive"
    else:
        fan = "fan " + " ".join(f"{v:.0f}%" for v in (s.fans or [s.fan]))
    return [
        head,
        _row("GPU", s.util_gpu, R.UTIL_GRAD, "n/a" if s.util_gpu is None else f"{s.util_gpu:.0f}%"),
        _row("MEM", s.mem_pct, R.MEM_GRAD, R.fmt_mem_pair(s.mem_used, s.mem_total)),
        _row("PWR", s.power_pct, R.POWER_GRAD, power),
        _row("TMP", temp_pct, R.HEAT_GRAD, ("n/a" if s.temp is None else f"{s.temp:.0f}°C") + f"   {fan}"),
    ]


def process_lines(snaps: list[GpuSnapshot], width: int, hide_graphics: bool = False) -> list[Text]:
    procs = [p for s in snaps for p in s.processes if not (hide_graphics and p.kind == "G")]
    procs.sort(key=lambda p: -(p.used_memory or 0))
    if not procs:
        return [Text("No GPU processes.", style=Style(color=R.DIM))]
    # narrow terminals: the command matters more than the unit, then than the user
    units = any(p.unit for p in procs) and width >= 100
    users = width >= 72
    header = (
        f"{'GPU':>3} {'PID':>8} "
        + (f"{'USER':<10} " if users else "")
        + f"{'TYPE':<4} {'SM%':>4} {'VRAM':>10} "
        + (f"{'UNIT':<19} " if units else "")
    )
    lines = [Text(header + "COMMAND", style=Style(color=R.LABEL, bold=True), no_wrap=True)]
    room = max(16, width - len(header))
    for p in procs:
        sm = "—" if p.sm_util is None else f"{p.sm_util}%"
        t = Text(no_wrap=True)
        t.append(f"{p.gpu_index:>3} {p.pid:>8} ", Style(color=R.TEXT))
        if users:
            t.append(f"{p.user[:10]:<10} ", Style(color=R.LABEL))
        t.append(f"{p.kind:<4} {sm:>4} {R.fmt_bytes(p.used_memory):>10} ", Style(color=R.TEXT))
        if units:
            t.append(f"{p.unit[:19]:<19} ", Style(color="#79c0ff"))
        cmd = Text(p.cmdline or p.name, style=Style(color=R.TEXT), no_wrap=True)
        cmd.truncate(room, overflow="ellipsis")
        t.append_text(cmd)
        lines.append(t)
    return lines


def render(
    backend: Backend,
    indices: list[int] | None = None,
    *,
    width: int = 100,
    redact: bool = True,
    hide_graphics: bool = False,
    alerts: Alerts | None = None,
) -> list[Text]:
    info = backend.system_info()
    snaps = backend.poll(indices)
    enrich([p for s in snaps for p in s.processes], redact_secrets=redact)
    top = Text(no_wrap=True)
    top.append(f"nvpulse v{__version__}", Style(color=R.ACCENT, bold=True))
    n = len(snaps)
    top.append(
        f"   Driver {clean(info.driver_version, 32)} · CUDA {clean(info.cuda_version, 16)}"
        f" · {clean(info.hostname, 64) or 'localhost'}"
        f" · {n} GPU{'s' if n != 1 else ''} · {time.strftime('%Y-%m-%d %H:%M:%S')}",
        Style(color=R.LABEL),
    )
    lines = [top]
    if not snaps:
        lines.append(Text("No NVIDIA GPUs found.", style=Style(color=R.DIM)))
        return lines
    for s in snaps:
        lines.append(Text(""))
        lines.extend(gpu_lines(s, alerts))
    lines.append(Text(""))
    lines.extend(process_lines(snaps, width, hide_graphics))
    return lines


def print_once(backend: Backend, indices: list[int] | None = None, **options) -> None:
    width = shutil.get_terminal_size((100, 24)).columns
    # Text objects only, so nothing here is ever parsed as markup; no_color follows NO_COLOR / pipes
    console = Console(width=width, highlight=False, soft_wrap=False, emoji=False)
    # Captured, then written in one go: Rich turns a closed pipe (`| head`) into exit
    # status 1 by itself, and the caller wants to treat that as a normal end.
    with console.capture() as capture:
        for line in render(backend, indices, width=width, **options):
            console.print(line, overflow="ellipsis", no_wrap=True)
    out = sys.stdout
    if out is None:  # fd 1 is closed
        return
    if hasattr(out, "reconfigure"):
        out.reconfigure(errors="replace")  # a C / latin-1 locale over SSH can't encode █ or ·
    out.write(capture.get())
