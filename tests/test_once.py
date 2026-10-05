"""``nvpulse --once``: a plain, safe, one-shot rendering of the same data."""

from __future__ import annotations

import pytest

from nvpulse import cli, once
from nvpulse.backend.mock import MockBackend
from nvpulse.backend.models import Alerts, ProcessInfo
from nvpulse.ui import render as R


def text(lines) -> str:
    return "\n".join(line.plain for line in lines)


def test_bar_reads_without_colour():
    assert once.bar(50, R.UTIL_GRAD, 8).plain == "████░░░░"
    assert once.bar(0, R.UTIL_GRAD, 4).plain == "░░░░"
    assert once.bar(250, R.UTIL_GRAD, 4).plain == "████"
    assert once.bar(None, R.UTIL_GRAD, 4).plain == "╌╌╌╌"


def test_render_lists_gpus_and_processes():
    out = text(once.render(MockBackend(2, seed=7), width=120))
    assert "GPU 0 · GeForce RTX 4090" in out and "GPU 1 · A100-SXM4-80GB" in out
    assert "passive" in out and "fan " in out
    assert "COMMAND" in out and "UNIT" in out and "docker:" in out
    assert "2 GPUs" in out and "(mock)" in out


def test_render_options():
    backend = MockBackend(8, seed=7)
    full = text(once.render(backend, width=120))
    assert "Xorg" in full
    assert "Xorg" not in text(once.render(MockBackend(8, seed=7), width=120, hide_graphics=True))
    assert "GPU 3 ·" not in text(once.render(MockBackend(8, seed=7), [0, 1], width=120))
    hot = text(once.render(MockBackend(1, seed=7), width=120, alerts=Alerts(temp=0, vram=0)))
    assert "[HOT]" in hot and "[VRAM]" in hot


class Custom(MockBackend):
    def __init__(self, procs, **snap):
        super().__init__(1, seed=1)
        self.procs, self.snap = procs, snap

    def poll(self, indices=None):
        snaps = super().poll(indices)
        snaps[0].processes = self.procs
        for key, value in self.snap.items():
            setattr(snaps[0], key, value)
        return snaps


def test_unit_column_only_when_something_has_a_unit():
    plain = [ProcessInfo(0, 10, "C", 1 << 30, name="a", user="u", cmdline="a --x")]
    assert "UNIT" not in text(once.render(Custom(plain), width=100))


def test_badges_warning_and_truncation():
    procs = [ProcessInfo(0, 10, "C", 1 << 30, name="a", user="u", cmdline="x" * 400)]
    out = once.render(Custom(procs, clock_reasons=0x40, pcie_width=8, pcie_width_max=16), width=80)
    joined = text(out)
    assert "[THERMAL]" in joined and "card supports 4.0 x16" in joined
    assert all(line.cell_len <= 80 for line in out if "xxx" in line.plain)
    assert "…" in joined


def test_no_gpus_and_no_processes():
    class Empty(MockBackend):
        def poll(self, indices=None):
            return []

    assert "No NVIDIA GPUs found." in text(once.render(Empty(1), width=80))
    assert "No GPU processes." in text(once.render(Custom([]), width=80))


def test_cli_once_prints_and_exits(capsys):
    assert cli.main(["--once", "--mock", "2", "--seed", "3", "--no-config"]) == 0
    out = capsys.readouterr().out
    assert "nvpulse v" in out and "GPU 1 ·" in out
    assert "\x1b" not in out  # not a terminal: no colour codes


def test_once_and_dump_do_not_mix():
    for argv in (["--once", "--dump"], ["--once", "-q"], ["--once", "--classic"]):
        with pytest.raises(SystemExit):
            cli.decide(argv, True)
    assert cli.decide(["--once"], False)[0] == "once"  # no TTY needed


def test_narrow_terminals_keep_the_command():
    procs = [ProcessInfo(0, 10, "C", 1 << 30, name="a", user="alice", cmdline="python train.py", unit="ollama")]
    wide = text(once.process_lines(Custom(procs).poll(), 120))
    assert "UNIT" in wide and "USER" in wide
    mid = text(once.process_lines(Custom(procs).poll(), 90))
    assert "UNIT" not in mid and "USER" in mid and "python train.py" in mid
    narrow = once.process_lines(Custom(procs).poll(), 60)
    assert "USER" not in text(narrow) and "python train.py" in text(narrow)
    assert all(line.cell_len <= 60 for line in narrow)


def test_once_survives_a_stdout_that_cannot_encode_block_characters():
    import os
    import subprocess
    import sys

    env = dict(os.environ, PYTHONIOENCODING="ascii", PYTHONUTF8="0")
    run = subprocess.run(
        [sys.executable, "-m", "nvpulse", "--once", "--mock", "1", "--no-config"], env=env, capture_output=True
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")[-300:]
    assert b"GPU 0" in run.stdout and b"Traceback" not in run.stderr


def test_once_and_dump_with_stdout_closed():
    import subprocess
    import sys

    for mode in ("--once", "--dump"):
        run = subprocess.run(
            f"{sys.executable} -m nvpulse {mode} --mock 1 --no-config >&-", shell=True, capture_output=True
        )
        assert b"Traceback" not in run.stderr, run.stderr.decode(errors="replace")[-300:]
