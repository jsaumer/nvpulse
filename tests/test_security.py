"""Regression tests for the hardening in docs/security.md."""

from __future__ import annotations

import math
import os
import subprocess
import sys
import time

import pytest

from nvpulse import cli, dump, killer
from nvpulse.backend.mock import MockBackend
from nvpulse.backend.models import ProcessInfo
from nvpulse.procinfo import enrich
from nvpulse.sanitize import clean, redact
from nvpulse.ui.app import NvPulse
from nvpulse.ui.detail import DetailView, GpuDetailScreen
from nvpulse.ui.modals import ConfirmKill
from nvpulse.ui.widgets import ProcessTable

HOSTILE = "py \x1b]0;PWNED\x1b\\ \x1b[2J \x9b31m [/] [@click=app.quit]x[/] ‮txt.exe​\n"


# --------------------------------------------------------------- sanitizing
@pytest.mark.parametrize("bad", ["\x1b", "\x07", "\x9b", "\x7f", "‮", "⁦", "​", " ", ""])
def test_clean_escapes_unsafe_characters(bad):
    out = clean(f"a{bad}b")
    assert bad not in out
    assert out.startswith("a\\") and out.endswith("b")


def test_clean_keeps_normal_unicode_and_truncates():
    assert clean("python3 train.py — résumé 日本") == "python3 train.py — résumé 日本"
    out = clean("x" * 100_000, 50)
    assert len(out) == 50 and out.endswith("…")


@pytest.mark.parametrize(
    "cmd, hidden, kept",
    [
        ("app --password=hunter2", "hunter2", "--password="),
        ("app --api-key sk-live-123", "sk-live-123", "--api-key"),
        ("HF_TOKEN=hf_abc python x.py", "hf_abc", "HF_TOKEN="),
        ("psql postgres://admin:s3cret@db/x", "s3cret", "admin"),
        ("app --client_secret=zz", "zz", "--client_secret"),
    ],
)
def test_redact_masks_secrets(cmd, hidden, kept):
    out = redact(cmd)
    assert hidden not in out and kept in out


@pytest.mark.parametrize("cmd", ["python --author bob", "python --tokenizer gpt2", "app --pass -v", "x --keyfile a"])
def test_redact_leaves_non_secrets(cmd):
    assert redact(cmd) == cmd


def test_enrich_sanitizes_backend_supplied_text():
    p = ProcessInfo(gpu_index=0, pid=10, kind="C", used_memory=1, name="n\x1b", user="u\x1b", cmdline=HOSTILE)
    enrich([p])
    for field in (p.name, p.user, p.cmdline):
        assert not any(c in field for c in "\x1b\x9b‮​\n")


# ------------------------------------------------------------ UI end-to-end
class HostileMock(MockBackend):
    def poll(self, indices=None):
        snaps = super().poll(indices)
        snaps[0].processes = [
            ProcessInfo(gpu_index=0, pid=4242, kind="C", used_memory=1 << 30, name="evil", user="m", cmdline=HOSTILE)
        ]
        return snaps


async def test_hostile_cmdline_never_reaches_terminal_and_dialog_survives():
    app = NvPulse(HostileMock(1, seed=1), interval=0.2)
    async with app.run_test(size=(140, 36)) as pilot:
        await pilot.pause(0.5)
        table = app.query_one(ProcessTable)
        for y in range(table.size.height):
            text = "".join(seg.text for seg in table.render_line(y))
            assert "\x1b" not in text and "\x9b" not in text and "‮" not in text
        # opening the kill dialog on the hostile row must not crash (markup injection)
        await pilot.press("k")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmKill)
        await pilot.press("n")
        await pilot.pause(0.2)
        assert app.is_running


async def test_read_only_blocks_kill():
    app = NvPulse(MockBackend(1, seed=5), interval=0.2, read_only=True)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("k")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ConfirmKill)


def test_command_palette_disabled():
    assert NvPulse.ENABLE_COMMAND_PALETTE is False


# ------------------------------------------------------------------ killing
@pytest.mark.parametrize("pid", [0, 1, -1, -1234])
def test_check_pid_refuses_special_pids(pid):
    with pytest.raises(killer.KillRefused):
        killer.check_pid(pid)


def test_check_pid_refuses_self_and_parent():
    for pid in (os.getpid(), os.getppid()):
        with pytest.raises(killer.KillRefused):
            killer.check_pid(pid)


@pytest.fixture
def sleeper():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    time.sleep(0.2)
    yield proc
    proc.kill()
    proc.wait()


def test_kill_real_process_via_pidfd(sleeper):
    from nvpulse.procinfo import process_start_time

    t = killer.KillTarget(gpu=0, pid=sleeper.pid, started=process_start_time(sleeper.pid), name="sleep", user="me")
    killer.prepare(t)
    msg = killer.send(t, force=False, live_pids={(0, sleeper.pid)})
    assert "SIGTERM" in msg
    assert sleeper.wait(timeout=5) != 0
    assert t.pidfd is None  # closed after use


def test_pid_reuse_is_detected(sleeper):
    t = killer.KillTarget(gpu=0, pid=sleeper.pid, started=12345.0, name="x", user="x")  # wrong start time
    with pytest.raises(killer.KillRefused, match="different process"):
        killer.prepare(t)
    assert sleeper.poll() is None  # untouched


def test_send_refuses_when_process_left_gpu(sleeper):
    t = killer.prepare(killer.KillTarget(gpu=0, pid=sleeper.pid, started=None, name="x", user="x"))
    with pytest.raises(killer.KillRefused, match="no longer"):
        killer.send(t, force=True, live_pids=set())
    assert sleeper.poll() is None


# ---------------------------------------------------------------------- CLI
def _exe(path, mode=0o755):
    path.write_text("#!/bin/sh\n")
    path.chmod(mode)
    return path


def test_trusted_executable_rules(tmp_path):
    good = _exe(tmp_path / "good")
    assert cli._trusted_executable(str(good))
    assert not cli._trusted_executable("relative/nvidia-smi")
    assert not cli._trusted_executable(str(_exe(tmp_path / "ww", 0o757)))  # world-writable
    assert not cli._trusted_executable(str(_exe(tmp_path / "noexec", 0o644)))
    assert not cli._trusted_executable(str(tmp_path))  # directory


def test_find_real_skips_cwd_and_relative_path_entries(tmp_path, monkeypatch):
    _exe(tmp_path / "nvidia-smi")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NVPULSE_REAL_SMI", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "bin"]))
    assert cli.find_real_nvidia_smi() is None


def test_env_override_must_be_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("NVPULSE_REAL_SMI", "nvidia-smi")
    assert cli.find_real_nvidia_smi() is None
    monkeypatch.setenv("NVPULSE_REAL_SMI", str(_exe(tmp_path / "ww", 0o777)))
    assert cli.find_real_nvidia_smi() is None


def test_passthrough_loop_guard(monkeypatch):
    monkeypatch.setenv(cli.LOOP_GUARD, "1")
    monkeypatch.setattr(cli.os, "execve", lambda *a: pytest.fail("must not exec"))
    assert cli.passthrough(["-q"]) == 2


def test_no_abbreviated_flag_capture():
    # "--comp" must be forwarded to nvidia-smi, not silently treated as --compact
    assert cli.decide(["--comp"], True)[0] == "passthrough"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_clamp_rejects_non_finite(value):
    with pytest.raises(SystemExit):
        cli.clamp(value, 0.1, 10, "--interval")


def test_clamp_bounds():
    assert cli.clamp(1e9, 1, 60, "--fps") == 60
    assert cli.clamp(0, 0.1, 10, "--interval") == 0.1


def test_parse_indices_rejects_negative():
    with pytest.raises(SystemExit):
        cli.parse_indices("-1")


# ------------------------------------------------------------- v0.2 surfaces
class HostileDriver(HostileMock):
    """A backend whose *driver* strings are hostile too (remote or buggy NVML)."""

    def poll(self, indices=None):
        snaps = super().poll(indices)
        snaps[0].name = snaps[0].uuid = snaps[0].bus_id = HOSTILE
        snaps[0].clock_reasons = 0x40
        return snaps

    def detail(self, index):
        d = super().detail(index)
        d.vbios = HOSTILE
        return d


def test_dump_is_ascii_and_leaves_out_identifying_data():
    out = dump.dumps(HostileDriver(1, seed=1))
    assert out.isascii() and not any(ord(c) < 0x20 and c != "\n" for c in out)  # no raw control characters
    for private in ("evil", "4242", "cmdline", "user", "pid", "hostname", "PWNED\x1b"):
        assert private not in out
    assert '"uuid": "GPU-<redacted>"' in out


async def test_detail_view_survives_hostile_driver_strings():
    app = NvPulse(HostileDriver(1, seed=1), interval=0.2)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.4)
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert isinstance(app.screen, GpuDetailScreen)
        view = app.screen.query_one(DetailView)
        assert view.detail is not None
        for widget in (view, app.query_one("#gpu-0")):
            for y in range(widget.outer_size.height):
                text = "".join(seg.text for seg in widget.render_lines(widget.region.at_offset((0, y)))[0])
                assert "\x1b" not in text and "\x9b" not in text and "\u202e" not in text
        assert "THERMAL" in str(view.border_title)
        assert app.is_running


@pytest.mark.parametrize("spec", ["GPU-\x1b[2J", "0;rm", "GPU-zzzzzzzz", "../../x", "0," + "GPU-" + "a" * 80, "²"])
def test_gpu_selectors_reject_anything_unexpected(spec):
    with pytest.raises(SystemExit):
        cli.parse_indices(spec)


def test_gpu_selector_count_is_capped():
    with pytest.raises(SystemExit):
        cli.parse_indices(",".join(str(i) for i in range(cli.MAX_INDICES + 1)))


@pytest.mark.parametrize("name", ["[/]", "x [@click=app.quit", "[bold", "a\\[/]", HOSTILE])
async def test_gpu_name_is_never_parsed_as_markup(name):
    """A driver-supplied name next to the throttle badges once raised MarkupError."""

    class Named(MockBackend):
        def poll(self, indices=None):
            snaps = super().poll(indices)
            snaps[0].name, snaps[0].clock_reasons = name, 0x40
            return snaps

    app = NvPulse(Named(1, seed=1), interval=0.2)
    async with app.run_test(size=(140, 36)) as pilot:
        await pilot.pause(0.4)
        card = app.query_one("#gpu-0")
        top = "".join(seg.text for seg in card.render_lines(card.region.at_offset((0, 0)))[0])
        assert "THERMAL" in top and "\x1b" not in top
        if name.isprintable():
            assert name in top  # shown literally
        assert app.is_running
