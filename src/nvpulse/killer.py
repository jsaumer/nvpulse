"""Safe signalling of GPU processes.

Two hazards when killing "the process the user selected a moment ago":

* **PID reuse.** Between the snapshot and the confirmation the process can exit and
  the kernel can hand its PID to something else. When nvpulse runs as root, a stale
  PID could mean signalling an unrelated system process. We pin the target with a
  pidfd (Linux 5.3+) as soon as the dialog opens and check that its start time
  matches the snapshot. The signal then goes through the pidfd, so it can only
  reach that exact process.
* **Special PIDs.** ``kill(0, …)`` signals our whole process group, negative PIDs
  signal groups, and PID 1 is init. NVML can report PID 0 for processes in other
  namespaces, so these are refused outright, along with our own PID and our parent.
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass, field

from .procinfo import process_start_time

_START_TOLERANCE = 0.05  # seconds; psutil derives create_time from jiffies


class KillRefused(Exception):
    """The target failed a safety check; the message is safe to show the user."""


@dataclass
class KillTarget:
    gpu: int
    pid: int
    started: float | None
    name: str
    user: str
    pidfd: int | None = field(default=None, repr=False)

    def close(self) -> None:
        if self.pidfd is not None:
            try:
                os.close(self.pidfd)
            except OSError:
                pass
            self.pidfd = None


def check_pid(pid: int) -> None:
    if not isinstance(pid, int) or pid <= 1:
        raise KillRefused(f"refusing to signal PID {pid}")
    if pid in (os.getpid(), os.getppid()):
        raise KillRefused("refusing to signal nvpulse or its parent shell")


def _same_process(target: KillTarget) -> bool:
    if target.started is None:
        return True  # nothing to compare against (no psutil / mock); pidfd still pins it
    now = process_start_time(target.pid)
    return now is not None and abs(now - target.started) <= _START_TOLERANCE


def prepare(target: KillTarget) -> KillTarget:
    """Validate the target and pin it with a pidfd. Call when the confirm dialog opens."""
    check_pid(target.pid)
    if hasattr(os, "pidfd_open"):
        try:
            target.pidfd = os.pidfd_open(target.pid)
        except ProcessLookupError:
            raise KillRefused(f"PID {target.pid} has already exited") from None
        except OSError:
            target.pidfd = None  # old kernel or seccomp; fall back to re-checking
    if not _same_process(target):
        target.close()
        raise KillRefused(f"PID {target.pid} now belongs to a different process; refresh and retry")
    return target


def send(target: KillTarget, force: bool, live_pids: set[tuple[int, int]]) -> str:
    """Deliver SIGTERM/SIGKILL after re-validating. Returns a status message."""
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        check_pid(target.pid)
        if (target.gpu, target.pid) not in live_pids:
            raise KillRefused(f"PID {target.pid} is no longer using GPU {target.gpu}")
        if target.pidfd is not None and hasattr(signal, "pidfd_send_signal"):
            signal.pidfd_send_signal(target.pidfd, sig)
        else:
            if not _same_process(target):
                raise KillRefused(f"PID {target.pid} was reused by another process; not signalled")
            os.kill(target.pid, sig)
        return f"sent {sig.name} to PID {target.pid}"
    finally:
        target.close()
