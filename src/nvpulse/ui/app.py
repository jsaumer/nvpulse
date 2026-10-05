"""The Textual application: two clocks (poll + animation) and adaptive layout."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static

from ..backend.models import Alerts, Backend, GpuDetail, GpuSnapshot, SystemInfo
from ..killer import KillRefused, KillTarget, check_pid, prepare, send
from ..procinfo import enrich
from ..sanitize import clean
from . import render as R
from .detail import DetailView, GpuDetailScreen
from .modals import MODAL_CSS, ConfirmKill, HelpScreen, ProcessInfoScreen
from .widgets import MAX_FILTER, SORT_LABEL, SORTS, GpuCard, HeaderBar, ProcessTable

CARD_MIN_W = {True: 62, False: 96}  # compact, expanded
CARD_H = {True: 7, False: 11}
INTERVALS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
EXIT_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


class NvPulse(App):
    TITLE = "nvpulse"
    # The built-in command palette adds actions we don't need (theme switching,
    # "save screenshot" to the current directory). Keep the surface minimal.
    ENABLE_COMMAND_PALETTE = False
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
    #filter { display: none; height: 1; border: none; padding: 0 1; background: #161b22; color: #e6edf3; }
    #filter.-on { display: block; }
    Footer { background: #161b22; }
    .-hc #procs { border: round #8b949e; border-subtitle-color: #b1bac4; }
    .-hc #empty { color: #d0d7de; }
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
        Binding("g", "toggle_graphics", "Graphics"),
        Binding("slash", "filter", "Filter"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
        Binding("i", "info", "Info", show=False),
        Binding("enter", "detail", "Detail"),
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
        redact: bool = True,
        read_only: bool = False,
        hide_graphics: bool = False,
        sort: str = "vram",
        hidden_columns: tuple[str, ...] | list[str] = (),
        alerts: Alerts | None = None,
        cost_per_kwh: float | None = None,
        currency: str = "$",
        theme: str = "default",
    ) -> None:
        super().__init__()
        self.redact = redact
        self.read_only = read_only
        self.hide_graphics = hide_graphics
        self.sort = sort if sort in SORTS else "vram"
        self.hidden_columns = frozenset(hidden_columns)
        self.alerts = alerts
        self.cost_per_kwh, self.currency = cost_per_kwh, currency
        if theme == "high-contrast":
            self.add_class("-hc")
        self.energy_wh: dict[int, float] = {}  # per GPU, integrated from the power readings we saw
        self._last_energy = 0.0
        self._alerting: dict[int, set[str]] = {}  # limits each GPU is currently over
        self.as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        self.backend = backend
        self.interval = interval
        self.fps = max(1.0, fps)
        self.indices = indices
        self.animate = animate
        self.force_compact = compact  # None = auto
        self.paused = False
        self.cards: dict[int, GpuCard] = {}
        self._polling = False
        self._have_info = False
        # Held around every backend call. close() takes it too: shutting NVML down
        # under a poll that is still inside the driver crashes the process.
        self._backend_lock = threading.Lock()
        self._closed = False
        self._last_tick = time.monotonic()
        self._snaps: list[GpuSnapshot] = []
        self.detail_index: int | None = None  # GPU shown in the detail view, if open
        self._detail_failed = False  # warn once per opening, not on every poll
        self.detail: GpuDetail | None = None

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        self.header = HeaderBar(SystemInfo())  # versions arrive with the first poll
        self.header.interval = self.interval
        self.header.as_root = self.as_root
        self.header.read_only = self.read_only
        yield self.header
        with VerticalScroll(id="gpus-scroll"):
            yield Container(id="gpus")
        with Vertical(id="procs"):
            yield ProcessTable(id="proc-table")
            yield Input(placeholder="filter: text  user:name  gpu:0  unit:docker", id="filter", max_length=MAX_FILTER)
        yield Footer()

    def on_mount(self) -> None:
        self.table = self.query_one(ProcessTable)
        self.table.hide_graphics = self.hide_graphics
        self.table.sort_key = self.sort
        self.table.hidden_columns = self.hidden_columns
        self._procs_box = self.query_one("#procs")
        self._filter_box = self.query_one("#filter", Input)
        self._update_proc_title()
        self.anim_timer = self.set_interval(1.0 / (self.fps if self.animate else 2.0), self.animate_tick)
        self.poll_timer = self.set_interval(self.interval, self.request_poll)
        self._handle_exit_signals(True)
        self.request_poll()  # the first poll goes through the worker like every other
        self.table.focus()

    def _handle_exit_signals(self, install: bool) -> None:
        """Leave through Textual's normal shutdown on SIGTERM / SIGHUP.

        The default action kills the process mid-frame: the terminal stays in the
        alternate screen with mouse reporting on, and NVML is never shut down.
        """
        try:
            loop = asyncio.get_running_loop()
            for sig in EXIT_SIGNALS:
                if install:
                    loop.add_signal_handler(sig, self._on_exit_signal, sig)
                else:
                    loop.remove_signal_handler(sig)
        except (NotImplementedError, RuntimeError, ValueError):  # not the main thread, or no Unix signals
            pass

    def _on_exit_signal(self, sig: int) -> None:
        self.exit(return_code=128 + sig)

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
    def request_poll(self, force: bool = False) -> None:
        """Start a poll unless one is running. ``force`` polls even while paused."""
        if self._polling or (self.paused and not force):
            return
        self._polling = True
        self._poll_worker()

    @work(thread=True, exclusive=False, group="poll")
    def _poll_worker(self) -> None:
        info = detail = snaps = None
        try:
            with self._backend_lock:
                if self._closed:
                    return
                if not self._have_info:
                    info = self.backend.system_info()
                snaps = self.backend.poll(self.indices)
                index = self.detail_index
                if index is not None:
                    try:
                        detail = self.backend.detail(index)
                    except Exception as exc:  # the extras must never freeze the dashboard
                        if not self._detail_failed:
                            self._detail_failed = True
                            self.call_from_thread(self._say, f"detail readings failed: {exc}", "warning")
            enrich([p for s in snaps for p in s.processes], redact_secrets=self.redact)
        except Exception as exc:  # keep the UI alive on driver hiccups
            self.call_from_thread(self._say, f"poll failed: {exc}", "error")
            snaps = None
        finally:
            self._polling = False
        if snaps is not None:
            self.call_from_thread(self.apply_snapshots, snaps, info, detail)

    def apply_snapshots(
        self, snaps: list[GpuSnapshot], info: SystemInfo | None = None, detail: GpuDetail | None = None
    ) -> None:
        found = self.query("#gpus")
        if not found:  # a poll that finished while the app was shutting down
            return
        grid = found.first()
        self._snaps = snaps
        self._count_energy(snaps)
        self._check_alerts(snaps)
        if info is not None:
            self._have_info = True
            self.header.info = info
        if detail is not None:
            self.detail = detail
        empty = self.query("#empty")
        if snaps and empty:
            empty.remove()
        elif not snaps and not empty:
            grid.mount(Static("No NVIDIA GPUs found.", id="empty"))
        seen = set()
        new_cards = []
        for s in snaps:
            seen.add(s.index)
            card = self.cards.get(s.index)
            if card is None:
                card = GpuCard(s.index, animate=self.animate, id=f"gpu-{s.index}")
                card.alerts = self.alerts
                self.cards[s.index] = card
                new_cards.append(card)
            card.session = self._session(s.index)
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
        self.feed_detail()

    def _count_energy(self, snaps: list[GpuSnapshot]) -> None:
        """Add up watt-hours from the power readings, one poll interval at a time."""
        now = time.monotonic()
        # a long gap means we were paused or suspended: don't bill it at the current draw
        dt = min(now - self._last_energy, 3 * self.interval + 1.0) if self._last_energy else 0.0
        self._last_energy = now
        for s in snaps:
            if s.power is not None:
                self.energy_wh[s.index] = self.energy_wh.get(s.index, 0.0) + s.power * dt / 3600.0

    def _session(self, index: int) -> str:
        wh = self.energy_wh.get(index)
        return R.fmt_session_energy(wh, self.cost_per_kwh, self.currency) if wh is not None else ""

    def _check_alerts(self, snaps: list[GpuSnapshot]) -> None:
        """Announce a limit once when a GPU crosses it, not on every poll it stays over."""
        if self.alerts is None:
            return
        for s in snaps:
            active = set(self.alerts.active(s))
            for label in sorted(active - self._alerting.get(s.index, set())):
                reading = f"{s.temp:.0f}°C" if label == "HOT" else f"{s.mem_pct:.0f}% VRAM"
                self._say(f"GPU {s.index} reached its {label} limit ({reading})", "warning")
                if self.alerts.bell:
                    self.bell()
            self._alerting[s.index] = active

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
        procs = self._procs_box
        title = f" Processes · {self.table.row_count}"
        if self.table.hide_graphics:
            title += f" · {self.table.hidden} graphics hidden"
        if self.table.filter_text.strip():
            title += f" · filter: {clean(self.table.filter_text.strip(), 40)}"
        # Text, not str: the filter is typed by the user and must not be parsed as markup
        procs.border_title = Text(title + " ")
        procs.border_subtitle = Text(
            f" sort: {SORT_LABEL[self.table.sort_key]} ▼ · / filter · i info · k term · K kill "
        )

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.header.paused = self.paused

    def _set_interval(self, value: float) -> None:
        self.interval = value
        self.header.interval = value
        self.poll_timer.stop()
        self.poll_timer = self.set_interval(self.interval, self.request_poll)
        self._say(f"poll every {value:g}s", timeout=1.5)

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
        self._say("animation " + ("on" if self.animate else "off"), timeout=1.5)

    def action_sort(self) -> None:
        self.table.cycle_sort()
        self.table.update_processes(self._snaps)
        self._update_proc_title()

    def action_toggle_graphics(self) -> None:
        self.table.hide_graphics = not self.table.hide_graphics
        self.table.update_processes(self._snaps)
        self._update_proc_title()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    # ---------------------------------------------------------------- filter
    def action_filter(self) -> None:
        self._filter_box.add_class("-on")
        self._filter_box.focus()

    def action_clear_filter(self) -> None:
        self._filter_box.value = ""  # triggers on_input_changed
        self._filter_box.remove_class("-on")
        self.table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.table.filter_text = event.value
        self.table.update_processes(self._snaps)
        self._update_proc_title()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            self._filter_box.remove_class("-on")
        self.table.focus()  # keep the filter, go back to the rows

    def action_info(self) -> None:
        sel = self.table.selected_process()
        proc = sel and next((p for s in self._snaps for p in s.processes if (p.gpu_index, p.pid) == sel), None)
        if not proc:
            self._say("no process selected", "warning")
            return
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.started)) if proc.started else ""
        self.push_screen(ProcessInfoScreen(proc, started))

    # ----------------------------------------------------------- detail view
    def action_detail(self, index: int | None = None) -> None:
        """Open the detail view for ``index``, or for the selected process's GPU."""
        if isinstance(self.screen, GpuDetailScreen):
            return
        shown = [s.index for s in self._snaps]
        if not shown:
            self._say("no GPU to show", "warning")
            return
        if index is None:
            sel = self.table.selected_process()
            index = sel[0] if sel else shown[0]
        if index not in shown:
            index = shown[0]
        self.detail_index, self.detail, self._detail_failed = index, None, False

        def closed(_result: None) -> None:
            self.detail_index = self.detail = None

        self.push_screen(GpuDetailScreen(index), closed)
        self.request_poll(force=True)  # fetch the extra readings now, even if paused

    def on_gpu_card_open(self, message: GpuCard.Open) -> None:
        self.action_detail(message.index)

    def on_process_table_open_detail(self, _message: ProcessTable.OpenDetail) -> None:
        self.action_detail()

    def step_detail(self, delta: int) -> None:
        shown = [s.index for s in self._snaps]
        if self.detail_index not in shown or len(shown) < 2:
            return
        self.detail_index = shown[(shown.index(self.detail_index) + delta) % len(shown)]
        self.detail = None
        self.feed_detail()
        self.request_poll(force=True)

    def feed_detail(self) -> None:
        """Push the current data into the detail view, if it is open."""
        screen = self.screen
        if not isinstance(screen, GpuDetailScreen) or self.detail_index is None:
            return
        shown = [s.index for s in self._snaps]
        if self.detail_index not in shown or self.detail_index not in self.cards:
            screen.dismiss(None)  # GPU fell off the bus or got filtered out
            return
        snap = self._snaps[shown.index(self.detail_index)]
        detail = self.detail if self.detail is not None and self.detail.index == snap.index else None
        hint = " esc close "
        if len(shown) > 1:
            hint = f" GPU {shown.index(snap.index) + 1} of {len(shown)} · ←/→ switch ·{hint}"
        view = screen.query(DetailView)
        if view:  # absent while the screen is still mounting or already closing
            view.first().show(snap, detail, self.cards[snap.index].hist, hint, self._session(snap.index), self.alerts)

    def _say(self, message: str, severity: str = "information", timeout: float | None = None) -> None:
        """notify() with markup off: messages can contain process names or driver errors."""
        self.notify(clean(message, 200), severity=severity, timeout=timeout, markup=False)

    def action_kill(self, force: bool) -> None:
        if self.read_only:
            self._say("read-only mode: signalling processes is disabled", "warning")
            return
        sel = self.table.selected_process()
        if sel is None:
            self._say("no process selected", "warning")
            return
        gpu, pid = sel
        proc = next((p for s in self._snaps for p in s.processes if p.pid == pid and p.gpu_index == gpu), None)
        if proc is None:
            self._say("process list changed; select again", "warning")
            return
        target = KillTarget(gpu=gpu, pid=pid, started=proc.started, name=proc.cmdline or proc.name, user=proc.user)
        is_mock = getattr(self.backend, "kill", None) is not None
        try:
            if is_mock:
                check_pid(pid)  # simulated PIDs: never touch real processes
            else:
                prepare(target)  # pin with pidfd + verify start time
        except KillRefused as exc:
            self._say(str(exc), "warning")
            return

        def done(ok: bool | None) -> None:
            if not ok:
                target.close()
                return
            self._send_signal(target, force, is_mock)

        self.push_screen(ConfirmKill(target, force, as_root=self.as_root), done)

    def _send_signal(self, target: KillTarget, force: bool, is_mock: bool) -> None:
        live = {(p.gpu_index, p.pid) for s in self._snaps for p in s.processes}
        try:
            if is_mock:
                self.backend.kill(target.gpu, target.pid)  # type: ignore[attr-defined]
                msg = f"sent {'SIGKILL' if force else 'SIGTERM'} to PID {target.pid} (mock)"
            else:
                msg = send(target, force, live)
            self._say(msg)
            self.request_poll()
        except KillRefused as exc:
            self._say(str(exc), "warning")
        except ProcessLookupError:
            self._say(f"PID {target.pid} already exited", "warning")
        except PermissionError:
            self._say(f"permission denied for PID {target.pid} (owned by {target.user})", "error")
        except OSError as exc:
            self._say(f"could not signal PID {target.pid}: {exc.strerror}", "error")

    def on_unmount(self) -> None:
        self._handle_exit_signals(False)
        # Wait for a poll in flight. If the driver is hung, leave it open: the
        # process is exiting anyway and the OS cleans up.
        if self._backend_lock.acquire(timeout=2.0):
            try:
                self._closed = True
                self.backend.close()
            finally:
                self._backend_lock.release()
