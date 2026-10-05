"""Run nvpulse in a pseudo-terminal, end it three ways, and report how it exits.

usage: signals.py [path-to-nvpulse]
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


def run(how: str, exe: str) -> None:
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.execv(exe, [exe, "--no-config"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
    out = b""

    def drain(seconds: float) -> None:
        nonlocal out
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    return

    drain(2.5)
    before = len(out)
    start = time.monotonic()
    if how == "SIGTERM":
        os.kill(pid, signal.SIGTERM)
        drain(2.0)
    elif how == "SIGHUP":
        os.kill(pid, signal.SIGHUP)
        drain(2.0)
    else:  # the terminal goes away: the kernel sends SIGHUP to the session
        os.close(fd)
    status = None
    while time.monotonic() - start < 8:
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
            break
        time.sleep(0.05)
    took = time.monotonic() - start
    if status is None:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        print(f"{how:<16} DID NOT EXIT within 8 s")
        return
    exited = (
        f"exit code {os.WEXITSTATUS(status)}" if os.WIFEXITED(status) else f"killed by signal {os.WTERMSIG(status)}"
    )
    tail = out[before:]
    restored = b"\x1b[?1049l" in tail  # leave the alternate screen
    mouse_off = b"\x1b[?1000l" in tail
    print(f"{how:<16} {exited:<22} in {took:.2f}s  alt-screen restored={restored}  mouse off={mouse_off}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else shutil.which("nvpulse")
    if not target:
        sys.exit("nvpulse not found; pass its path")
    for way in ("SIGTERM", "SIGHUP", "terminal closed"):
        run(way, os.path.abspath(target))
