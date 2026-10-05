"""The Textual application: two clocks (poll + animation) and adaptive layout."""

from __future__ import annotations

import os
import signal
import time

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Footer, Static

from ..backend.models import Backend, GpuSnapshot
from ..procinfo import enrich
from .modals import MODAL_CSS, ConfirmKill, HelpScreen
from .widgets import SORT_LABEL, GpuCard, HeaderBar, ProcessTable

CARD_MIN_W = {True: 62, False: 96}  # compact, expanded
CARD_H = {True: 7, False: 11}
INTERVALS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


class NvPulse(App):
    TITLE = "nvpulse"
    CSS = (
        """
    Screen { background: #0d1117; layers: base; }
    #gpus-scroll { height: auto; max-height: 70%; scrollbar-size-vertical: 1; }
    #gpus { layout: grid; grid-size: 1; grid-gutter: 0 1; height: auto; padding: 0 1; }
    #procs {
        height: 1fr; min-height: 6; margin: 0 1;
        border: round #30363d; border-title-color: #e6edf3; border-title-style: bold;
        border-subtitle-color: #6e7681; background: #0d1117;
    }
    #empty { content-align: center middle; height: 1fr; color: #8b949e; }
    Footer { background: #161b22; }
    """
        + MODAL_CSS
    )
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p,space", "pause", "Pause"),
        Binding("plus,equals_sign", "faster", "+Rate", show=False),
        Binding("minus,underscore", "slower", "-Rate", show=False),
        Binding("c", "compact", "Compact"),
        Binding("a", "toggle_anim", "Anim", show=False),
        Binding("s", "sort", "Sort"),
        Binding("k", "kill(False)", "Term"),
        Binding("K", "kill(True)", "Kill", show=False),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(
        self,
        backend: Backend,
        *,
        interval: float = 1.0,
        fps: float = 20.0,
        indices: list[int] | None = None,
        animate: bool = True,
        compact: bool | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.interval = interval
        self.fps = max(1.0, fps)
        self.indices = indices
        self.animate = animate
        self.force_compact = compact  # None = auto
        self.paused = False
        self.cards: dict[int, GpuCard] = {}
        self._polling = False
        self._last_tick = time.monotonic()
        self._snaps: list[GpuSnapshot] = []

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        self.header = HeaderBar(self.backend.system_info())
        self.header.interval = self.interval
        yield self.header
        with VerticalScroll(id="gpus-scroll"):
            yield Container(id="gpus")
        with Vertical(id="procs"):
            yield ProcessTable(id="proc-table")
        yield Footer()

    def on_mount(self) -> None:
        self.table = self.query_one(ProcessTable)
        self._update_proc_title()
        snaps = self.backend.poll(self.indices)
        enrich([p for s in snaps for p in s.processes])
        self.apply_snapshots(snaps)
        if not snaps:
            self.query_one("#gpus").mount(Static("No NVIDIA GPUs found.", id="empty"))
        self.anim_timer = self.set_interval(1.0 / (self.fps if self.animate else 2.0), self.animate_tick)
        self.poll_timer = self.set_interval(self.interval, self.request_poll)
        self.table.focus()

    def _compact(self) -> bool:
        if self.force_compact is not None:
            return self.force_compact
        return len(self.cards) > 1 or self.size.height < 30

    def relayout(self) -> None:
        if not self.cards:
            return
        compact = self._compact()
        n = len(self.cards)
        width = max(1, self.size.width - 2)
        cols = max(1, min(n, width // CARD_MIN_W[compact]))
        grid = self.query_one("#gpus")
        grid.styles.grid_size_columns = cols
        grid.styles.grid_rows = str(CARD_H[compact])
        for card in self.cards.values():
            if card.compact != compact:
                card.set_compact(compact)

    def on_resize(self) -> None:
        self.relayout()

    # ------------------------------------------------------------------ data
    def request_poll(self) -> None:
        if self.paused or self._polling:
            return
        self._polling = True
        self._poll_worker()

    @work(thread=True, exclusive=False, group="poll")
    def _poll_worker(self) -> None:
        try:
            snaps = self.backend.poll(self.indices)
            enrich([p for s in snaps for p in s.processes])
        except Exception as exc:  # keep the UI alive on driver hiccups
            self.call_from_thread(self.notify, f"poll failed: {exc}", severity="error")
            snaps = None
        finally:
            self._polling = False
        if snaps is not None:
            self.call_from_thread(self.apply_snapshots, snaps)

    def apply_snapshots(self, snaps: list[GpuSnapshot]) -> None:
        self._snaps = snaps
        grid = self.query_one("#gpus")
        seen = set()
        new_cards = []
        for s in snaps:
            seen.add(s.index)
            card = self.cards.get(s.index)
            if card is None:
                card = GpuCard(s.index, animate=self.animate, id=f"gpu-{s.index}")
                self.cards[s.index] = card
                new_cards.append(card)
            card.update_snapshot(s)
        if new_cards:
            grid.mount_all(new_cards)
        for idx in list(self.cards):
            if idx not in seen:  # GPU fell off the bus / filtered out
                self.cards.pop(idx).remove()
        if new_cards:
            self.call_after_refresh(self.relayout)
        self.header.set_totals(snaps)
        self.table.update_processes(snaps)
        self._update_proc_title()

    # ------------------------------------------------------------- animation
    def animate_tick(self) -> None:
        now = time.monotonic()
        dt = min(0.25, now - self._last_tick)
        self._last_tick = now
        for card in self.cards.values():
            card.tick(dt)
        self.header.t += dt
        self.header.refresh()

    # --------------------------------------------------------------- actions
    def _update_proc_title(self) -> None:
        procs = self.query_one("#procs")
        n = self.table.row_count
        procs.border_title = f" Processes · {n} "
        procs.border_subtitle = f" sort: {SORT_LABEL[self.table.sort_key]} ▼ · k term · K kill "

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.header.paused = self.paused

    def _set_interval(self, value: float) -> None:
        self.interval = value
        self.header.interval = value
        self.poll_timer.stop()
        self.poll_timer = self.set_interval(self.interval, self.request_poll)
        self.notify(f"poll every {value:g}s", timeout=1.5)

    def action_faster(self) -> None:
        smaller = [i for i in INTERVALS if i < self.interval]
        if smaller:
            self._set_interval(smaller[-1])

    def action_slower(self) -> None:
        larger = [i for i in INTERVALS if i > self.interval]
        if larger:
            self._set_interval(larger[0])

    def action_compact(self) -> None:
        self.force_compact = not self._compact()
        self.relayout()

    def action_toggle_anim(self) -> None:
        self.animate = not self.animate
        for card in self.cards.values():
            card.animate_enabled = self.animate
        self.anim_timer.stop()
        self.anim_timer = self.set_interval(1.0 / (self.fps if self.animate else 2.0), self.animate_tick)
        self.notify("animation " + ("on" if self.animate else "off"), timeout=1.5)

    def action_sort(self) -> None:
        self.table.cycle_sort()
        self.table.update_processes(self._snaps)
        self._update_proc_title()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_kill(self, force: bool) -> None:
        sel = self.table.selected_process()
        if sel is None:
            self.notify("no process selected", severity="warning")
            return
        gpu, pid = sel
        name = next(
            (p.cmdline or p.name for s in self._snaps for p in s.processes if p.pid == pid and p.gpu_index == gpu),
            "?",
        )

        def done(ok: bool | None) -> None:
            if ok:
                self._send_signal(gpu, pid, force)

        self.push_screen(ConfirmKill(pid, name, gpu, force), done)

    def _send_signal(self, gpu: int, pid: int, force: bool) -> None:
        mock_kill = getattr(self.backend, "kill", None)
        try:
            if mock_kill is not None:
                mock_kill(gpu, pid)
            else:
                os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            self.notify(f"sent {'SIGKILL' if force else 'SIGTERM'} to {pid}")
            self.request_poll()
        except ProcessLookupError:
            self.notify(f"PID {pid} already exited", severity="warning")
        except PermissionError:
            self.notify(f"permission denied for PID {pid} (run with sudo?)", severity="error")

    def on_unmount(self) -> None:
        self.backend.close()
