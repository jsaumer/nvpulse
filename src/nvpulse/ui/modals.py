from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from .. import __version__
from ..killer import KillTarget

MODAL_CSS = """
ModalScreen { align: center middle; background: #010409 60%; }
#dialog {
    width: 64; height: auto; padding: 1 2;
    border: round #f85149; background: #161b22;
}
#dialog.help { border: round #76b900; width: 70; }
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
    ("s", "cycle process sort (VRAM, SM%, PID, GPU)"),
    ("g", "hide / show graphics-only processes"),
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
