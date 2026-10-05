"""Per-GPU detail view: tall history graphs plus every reading the card offers.

Opened with Enter (for the selected process's GPU) or by clicking a card. The extra
readings in :class:`GpuDetail` are only polled while this screen is up, because the
PCIe throughput call alone takes longer than a whole regular poll.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widget import Widget

from ..backend.models import GpuDetail, GpuSnapshot
from ..sanitize import clean
from . import render as R
from .widgets import ALERT, WARN, card_title

GUTTER = 18  # label + current value to the left of each graph
PENDING = "…"

LAB = Style(color=R.LABEL)
VAL = Style(color=R.TEXT)
DIM = Style(color=R.DIM)


def _num(v: float | None, unit: str = "", digits: int = 0) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}{unit}"


def _pair(cur: float | None, top: float | None, unit: str) -> str:
    if cur is None and top is None:
        return "n/a"
    return f"{_num(cur)}/{_num(top)} {unit}" if top is not None else f"{_num(cur)} {unit}"


def _line(*parts: tuple[str, Style] | str) -> Text:
    """Join ``(text, style)`` parts with dim separators; plain strings are values."""
    t = Text(no_wrap=True, overflow="ellipsis")
    for i, part in enumerate(parts):
        if i:
            t.append(" · ", DIM)
        text, style = (part, VAL) if isinstance(part, str) else part
        t.append(text, style)
    return t


def facts(s: GpuSnapshot, d: GpuDetail | None) -> list[tuple[str, Text]]:
    """The labelled rows under the graphs. ``d`` is None until the first detail poll."""

    def later(fn) -> str:
        return PENDING if d is None else fn(d)

    reasons = s.clock_reason_names
    limits = (
        ("n/a", DIM)
        if reasons is None
        else (", ".join(reasons) or "none", Style(color=ALERT, bold=True) if s.throttle_badges else VAL)
    )

    if s.fan is None:
        fans = _line(("no fan reported (passive cooling)", DIM))
    else:
        parts = []
        for i, pct in enumerate(s.fans or [s.fan]):
            bit = f"{i + 1}: {pct:.0f}%"
            if d is not None and i < len(d.fan_rpm):
                bit += f" {d.fan_rpm[i]} RPM"
            if d is not None and i < len(d.fan_target) and d.fan_target[i] is not None:
                bit += f" (target {d.fan_target[i]:.0f}%)"
            parts.append(bit)
        fans = _line(*parts)

    link_now = f"Gen {s.pcie_gen} x{s.pcie_width} now" if s.pcie_gen and s.pcie_width else "link n/a"
    link_max = f"up to Gen {s.pcie_gen_max} x{s.pcie_width_max}" if s.pcie_gen_max and s.pcie_width_max else ""
    pcie: list[tuple[str, Style] | str] = [link_now]
    if s.pcie_downgrade:
        pcie.append((f"below the card's {s.pcie_downgrade}", Style(color=WARN, bold=True)))
    elif link_max:
        pcie.append(link_max)
    pcie += [
        later(lambda d: f"TX {R.fmt_rate(d.pcie_tx)}"),
        later(lambda d: f"RX {R.fmt_rate(d.pcie_rx)}"),
        later(lambda d: "replays n/a" if d.pcie_replay is None else f"{d.pcie_replay} replays"),
    ]

    def ecc(d: GpuDetail) -> str:
        if d.ecc_corrected is None and d.ecc_uncorrected is None:
            return "ECC n/a"
        return f"ECC {_num(d.ecc_corrected)} corrected, {_num(d.ecc_uncorrected)} uncorrected"

    persistence = "n/a" if s.persistence is None else ("on" if s.persistence else "off")
    return [
        (
            "Clocks",
            _line(
                f"SM {_pair(s.clock_sm, s.clock_sm_max, 'MHz')}",
                f"MEM {_pair(s.clock_mem, s.clock_mem_max, 'MHz')}",
                later(lambda d: f"VIDEO {_pair(d.clock_video, d.clock_video_max, 'MHz')}"),
            ),
        ),
        ("Clock cap", _line(limits)),
        ("Fans", fans),
        (
            "Thermals",
            _line(
                f"{_num(s.temp, '°C')} now",
                later(lambda d: f"target {_num(d.temp_target, '°C')}"),
                later(lambda d: f"max operating {_num(d.temp_max_operating, '°C')}"),
                f"slowdown {_num(s.temp_slowdown, '°C')}",
                f"shutdown {_num(s.temp_shutdown, '°C')}",
            ),
        ),
        (
            "Power",
            _line(
                f"{_num(s.power, ' W')} of {_num(s.power_limit, ' W')}",
                later(lambda d: f"default limit {_num(d.power_default_limit, ' W')}"),
                later(lambda d: f"{R.fmt_energy(d.energy)} since driver load"),
            ),
        ),
        ("PCIe", _line(*pcie)),
        (
            "Memory",
            _line(
                f"{R.fmt_gib(s.mem_used)} of {R.fmt_gib(s.mem_total)} GiB",
                f"controller {_num(s.util_mem, '%')}",
                later(ecc),
            ),
        ),
        (
            "Engines",
            _line(
                f"ENC {_num(s.enc_util, '%')}",
                f"DEC {_num(s.dec_util, '%')}",
                "P-state n/a" if s.pstate is None else f"P{s.pstate}",
                f"persistence {persistence}",
            ),
        ),
        # driver-supplied strings: cleaned, and only ever appended to a Text
        (
            "Identity",
            _line(
                clean(s.uuid, 64) or "UUID n/a",
                clean(s.bus_id, 32) or "bus n/a",
                later(lambda d: f"VBIOS {clean(d.vbios, 48) or 'n/a'}"),
            ),
        ),
    ]


class DetailView(Widget):
    DEFAULT_CSS = """
    DetailView {
        width: 1fr; height: 1fr; margin: 1 2; padding: 0 1;
        border: round #76b900; border-title-color: #e6edf3; border-title-style: bold;
        border-subtitle-color: #6e7681; background: #0d1117;
    }
    """

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.snap: GpuSnapshot | None = None
        self.detail: GpuDetail | None = None
        self.hist: Mapping[str, deque] = {}

    def show(self, snap: GpuSnapshot | None, detail: GpuDetail | None, hist: Mapping[str, deque], hint: str) -> None:
        self.snap, self.detail, self.hist = snap, detail, hist
        if snap is not None:
            self.border_title = card_title(snap)
        self.border_subtitle = Text(hint)
        self.refresh()

    def render(self):
        s = self.snap
        if s is None:
            return Text("waiting for data…", style=R.DIM)
        width, height = self.size.width, self.size.height
        rows = facts(s, self.detail)
        graph_w = max(0, width - GUTTER)
        graph_h = max(1, min(8, (height - len(rows) - 1) // 4))
        t_max = float(s.temp_shutdown or 100)
        power = f"{s.power:.0f}/{s.power_limit:.0f}W" if s.power is not None and s.power_limit else _num(s.power, "W")
        graphs = [
            ("GPU", _num(s.util_gpu, "%"), "gpu", R.UTIL_GRAD, 100.0),
            ("MEM", R.fmt_mem_pair(s.mem_used, s.mem_total), "mem", R.MEM_GRAD, 100.0),
            ("PWR", power, "pwr", R.POWER_GRAD, 100.0),
            ("TMP", _num(s.temp, "°C"), "tmp", R.HEAT_GRAD, t_max),
        ]
        lines: list[Text] = []
        for label, value, key, stops, vmax in graphs:
            graph = R.history_graph(self.hist.get(key, ()), graph_w, graph_h, stops, vmax)
            for i, g in enumerate(graph):
                line = Text(no_wrap=True, overflow="crop")
                if i == len(graph) - 1:  # on the baseline, next to the newest readings' zero
                    line.append(f"{label:<4}", Style(color=R.LABEL, bold=True))
                    line.append(f"{value:>{GUTTER - 6}}  ", Style(color=R.TEXT, bold=True))
                else:
                    line.append(" " * GUTTER)
                line.append_text(g)
                lines.append(line)
        lines.append(Text(""))
        for label, value in rows:
            line = Text(no_wrap=True, overflow="ellipsis")
            line.append(f"{label:<10}", Style(color=R.LABEL, bold=True))
            line.append_text(value)
            lines.append(line)
        return Group(*lines)


class GpuDetailScreen(ModalScreen[None]):
    """Holds a :class:`DetailView`. The app feeds it; this only reports key presses."""

    BINDINGS = [
        Binding("escape,enter,q", "close", "Close"),
        Binding("left,h", "step(-1)", "Previous GPU"),
        Binding("right,l", "step(1)", "Next GPU"),
    ]

    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index

    def compose(self) -> ComposeResult:
        yield DetailView()

    def on_mount(self) -> None:
        self.app.feed_detail()  # type: ignore[attr-defined]

    def on_click(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_step(self, delta: int) -> None:
        self.app.step_detail(delta)  # type: ignore[attr-defined]
