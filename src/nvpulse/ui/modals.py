from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

MODAL_CSS = """
ModalScreen { align: center middle; background: #010409 60%; }
#dialog {
    width: 64; height: auto; padding: 1 2;
    border: round #f85149; background: #161b22;
}
#dialog.help { border: round #76b900; width: 56; }
#dialog Static { width: 100%; }
#buttons { height: auto; margin-top: 1; align: right middle; }
#buttons Button { margin-left: 2; min-width: 10; }
"""


class ConfirmKill(ModalScreen[bool]):
    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No")]

    def __init__(self, pid: int, name: str, gpu: int, force: bool) -> None:
        super().__init__()
        self.pid, self.name_, self.gpu, self.force = pid, name, gpu, force

    def compose(self) -> ComposeResult:
        sig = "SIGKILL" if self.force else "SIGTERM"
        with Vertical(id="dialog"):
            yield Static(f"[b]Send {sig} to PID {self.pid}?[/b]")
            yield Static(f"[#8b949e]GPU {self.gpu} · {self.name_}[/]")
            with Horizontal(id="buttons"):
                yield Button("Kill (y)", variant="error", id="yes")
                yield Button("Cancel (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


HELP = """[b #76b900]nvpulse[/] keys

  [b]q[/]        quit
  [b]p[/] / space  pause / resume polling
  [b]+[/] / [b]-[/]    poll faster / slower
  [b]c[/]        toggle compact / expanded cards
  [b]a[/]        toggle animation
  [b]s[/]        cycle process sort (VRAM, SM%, PID, GPU)
  [b]k[/]        SIGTERM selected process
  [b]K[/]        SIGKILL selected process
  [b]↑ ↓[/]      move in process table
  [b]?[/]        this help

[#8b949e]Any nvidia-smi flag (e.g. -q, -L, --query-gpu=…) is
forwarded to the real nvidia-smi.[/]"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="help"):
            yield Static(HELP)

    def action_close(self) -> None:
        self.dismiss(None)
