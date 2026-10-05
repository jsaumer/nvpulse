from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from .. import __version__
from ..backend.models import ProcessInfo
from ..killer import KillTarget
from . import render as R

MODAL_CSS = """
ModalScreen { align: center middle; background: #010409 60%; }
#dialog {
    width: 64; height: auto; padding: 1 2;
    border: round #f85149; background: #161b22;
}
#dialog.help { border: round #76b900; width: 70; }
#dialog.info { border: round #58a6ff; width: 90%; max-width: 110; max-height: 80%; scrollbar-size-vertical: 1; }
#dialog.info Static { height: auto; }
#dialog Static { width: 100%; }
#buttons { height: auto; margin-top: 1; align: right middle; }
#buttons Button { margin-left: 2; min-width: 10; }
"""


class ConfirmKill(ModalScreen[bool]):
    """Kill confirmation.

    The process name and command line are attacker-controlled, so they are rendered
    as plain ``Text`` with markup disabled; a crafted argv like ``[/]`` or
    ``[@click=...]`` can't break the dialog or forge its contents.
    """

    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No")]

    def __init__(self, target: KillTarget, force: bool, as_root: bool = False) -> None:
        super().__init__()
        self.target, self.force, self.as_root = target, force, as_root

    def compose(self) -> ComposeResult:
        t = self.target
        sig = "SIGKILL" if self.force else "SIGTERM"
        title = Text(f"Send {sig} to PID {t.pid}?", style="bold")
        detail = Text(no_wrap=False)
        detail.append(f"GPU {t.gpu} · user ", style="#8b949e")
        detail.append(t.user or "?", style="#e6edf3")
        detail.append("\n")
        detail.append(t.name or "?", style="#e6edf3")
        with Vertical(id="dialog"):
            yield Static(title, markup=False)
            yield Static(detail, markup=False)
            if self.as_root:
                yield Static(Text("Running as root: this can signal any process.", style="bold #d29922"), markup=False)
            with Horizontal(id="buttons"):
                yield Button("Kill (y)", variant="error", id="yes")
                yield Button("Cancel (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


KEYS = [
    ("q", "quit"),
    ("p / space", "pause / resume polling"),
    ("+ / -", "poll faster / slower"),
    ("c", "toggle compact / expanded cards"),
    ("a", "toggle animation"),
    ("s", "cycle process sort (VRAM, SM%, PID, GPU, UNIT)"),
    ("g", "hide / show graphics-only processes"),
    ("/", "filter processes (text, user:x, gpu:N, unit:x)"),
    ("esc", "clear the filter"),
    ("i", "full details of the selected process"),
    ("enter", "GPU detail view (or click a card)"),
    ("k", "SIGTERM selected process (confirms first)"),
    ("K", "SIGKILL selected process (off with --read-only)"),
    ("↑ ↓", "move in process table"),
    ("?", "this help"),
]


def help_text() -> Text:
    width = max(len(keys) for keys, _ in KEYS)
    t = Text()
    t.append("nvpulse", style="bold #76b900")
    t.append(f" {__version__}", style="#8b949e")
    t.append("  keys\n\n")
    for keys, what in KEYS:
        t.append(f"  {keys:<{width}}", style="bold")
        t.append(f"   {what}\n")
    t.append(
        "\nAny nvidia-smi flag (e.g. -q, -L, --query-gpu=…) is\nforwarded to the real nvidia-smi.", style="#8b949e"
    )
    return t


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="help"):
            yield Static(help_text(), markup=False)

    def action_close(self) -> None:
        self.dismiss(None)


def process_info(p: ProcessInfo, started: str = "") -> Text:
    """Everything known about one process, command line in full.

    The strings were cleaned and redacted by ``procinfo.enrich()``; they are only
    appended to a ``Text`` here, so none of it is parsed as markup.
    """
    t = Text()
    rows = [
        ("PID", str(p.pid)),
        ("User", p.user or "?"),
        ("GPU", str(p.gpu_index)),
        ("Type", {"C": "compute", "G": "graphics", "C+G": "compute + graphics"}.get(p.kind, p.kind)),
        ("VRAM", R.fmt_bytes(p.used_memory)),
        (
            "SM / mem",
            f"{'n/a' if p.sm_util is None else f'{p.sm_util}%'} / {'n/a' if p.mem_util is None else f'{p.mem_util}%'}",
        ),
        ("Unit", p.unit or "none"),
        ("Started", started or "unknown"),
    ]
    t.append(p.name or "?", style="bold #e6edf3")
    t.append("\n\n")
    for label, value in rows:
        t.append(f"{label:<10}", style="#8b949e")
        t.append(f"{value}\n", style="#e6edf3")
    t.append("\nCommand\n", style="#8b949e")
    t.append(p.cmdline or p.name or "?", style="#e6edf3")
    return t


class ProcessInfoScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,i,q,enter", "close", "Close")]

    def __init__(self, proc: ProcessInfo, started: str = "") -> None:
        super().__init__()
        self.proc, self.started = proc, started

    def compose(self) -> ComposeResult:
        # scrolls: a long command line on a small terminal is taller than the dialog
        with VerticalScroll(id="dialog", classes="info"):
            yield Static(process_info(self.proc, self.started), markup=False)

    def on_click(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
