"""Run nvpulse in a pseudo-terminal and report CPU share and terminal output rate.

usage: cpu_usage.py [path-to-nvpulse]
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import sys
import termios
import time

import psutil

CASES = ([], ["--fps", "10"], ["--no-anim"], ["-n", "0.25"], ["--hide-graphics"])


def run(exe: str, args: list[str], seconds: float = 12, rows: int = 46, cols: int = 150) -> None:
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ["COLORTERM"] = "truecolor"
        os.execv(exe, [exe, "--no-config", *args])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    os.kill(pid, signal.SIGWINCH)
    proc = psutil.Process(pid)
    written = 0

    def drain(duration: float) -> None:
        nonlocal written
        end = time.monotonic() + duration
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                try:
                    written += len(os.read(fd, 65536))
                except OSError:
                    return

    drain(3.0)  # startup
    cpu0, t0, written0 = proc.cpu_times(), time.monotonic(), written
    drain(seconds)
    cpu1, elapsed = proc.cpu_times(), time.monotonic() - t0
    rss = proc.memory_info().rss >> 20
    os.write(fd, b"q")
    drain(1.0)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)
    share = 100 * ((cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)) / elapsed
    rate = (written - written0) / elapsed / 1024
    print(f"{' '.join(args) or '(default)':<18} cpu {share:5.1f}%  rss {rss} MiB  terminal output {rate:6.1f} KiB/s")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else shutil.which("nvpulse")
    if not target:
        sys.exit("nvpulse not found; pass its path")
    for case in CASES:
        run(os.path.abspath(target), list(case))
