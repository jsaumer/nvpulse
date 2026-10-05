import json
import os
import signal
import threading
import time

import pytest

from nvpulse import cli
from nvpulse.backend.mock import MockBackend
from nvpulse.ui.app import NvPulse
from nvpulse.ui.detail import DetailView, GpuDetailScreen
from nvpulse.ui.modals import ConfirmKill
from nvpulse.ui.widgets import GpuCard, ProcessTable, card_subtitle, card_title


@pytest.mark.parametrize(
    "argv, tty, mode",
    [
        ([], True, "dashboard"),
        (["-i", "0,1"], True, "dashboard"),
        (["-n", "0.5", "--compact"], True, "dashboard"),
        (["-q"], True, "passthrough"),
        (["-q", "-i", "0"], True, "passthrough"),
        (["--query-gpu=name", "--format=csv"], True, "passthrough"),
        (["-L"], True, "passthrough"),
        (["--classic"], True, "passthrough"),
        ([], False, "passthrough"),
        (["--mock", "3"], False, "dashboard"),
        (["--dump"], False, "dump"),  # JSON is meant to be piped: no TTY needed
        (["--dump", "--mock", "2", "-i", "0"], True, "dump"),
    ],
)
def test_decide(argv, tty, mode):
    assert cli.decide(argv, tty)[0] == mode


def test_parse_indices():
    assert cli.parse_indices("2,0, 1") == [0, 1, 2]
    assert cli.parse_indices(None) is None
    with pytest.raises(SystemExit):
        cli.parse_indices("GPU-abc")


def test_passthrough_strips_own_flags(monkeypatch, tmp_path):
    fake = tmp_path / "nvidia-smi"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    calls = {}
    monkeypatch.delenv(cli.LOOP_GUARD, raising=False)
    monkeypatch.setenv("NVPULSE_REAL_SMI", str(fake))
    monkeypatch.setattr(cli.os, "execve", lambda path, args, env: calls.update(path=path, args=args, env=env))
    cli.passthrough(["--classic", "-q"])
    assert calls["path"] == str(fake)
    assert calls["args"] == [str(fake), "-q"]
    assert calls["env"][cli.LOOP_GUARD] == "1"


def test_mock_backend_shapes():
    b = MockBackend(3, seed=1)
    snaps = b.poll()
    assert [s.index for s in snaps] == [0, 1, 2]
    assert snaps[1].fan is None  # A100 profile is passive
    assert all(0 <= s.util_gpu <= 100 for s in snaps)
    assert b.poll([2])[0].index == 2


@pytest.mark.parametrize("n, size", [(1, (120, 34)), (4, (150, 40)), (8, (90, 30))])
async def test_app_runs_and_adapts(n, size):
    app = NvPulse(MockBackend(n, seed=3), interval=0.2, fps=20)
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.8)
        cards = list(app.query(GpuCard))
        assert len(cards) == n
        assert all(c.compact == (n > 1) for c in cards)
        table = app.query_one(ProcessTable)
        assert table.row_count == sum(len(s.processes) for s in app._snaps)

        await pilot.press("s")
        assert table.sort_key == "sm"
        await pilot.press("c")
        assert all(c.compact == (n == 1) for c in cards)
        await pilot.press("p")
        assert app.paused
        await pilot.press("minus")
        assert app.interval > 0.2


async def test_kill_flow_mock():
    backend = MockBackend(1, seed=5)
    app = NvPulse(backend, interval=0.2)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        _gpu, pid = app.query_one(ProcessTable).selected_process()
        await pilot.press("k")
        await pilot.pause(0.2)
        await pilot.press("y")
        await pilot.pause(0.6)
        pids = [p.pid for s in app._snaps for p in s.processes]
        assert pid not in pids


async def test_process_table_updates_in_place():
    app = NvPulse(MockBackend(1, seed=5), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        table = app.query_one(ProcessTable)
        snaps = app._snaps
        procs = sorted(snaps[0].processes, key=lambda p: -(p.used_memory or 0))
        assert len(procs) >= 2
        rebuilds = []
        table.clear = lambda *a, **k: rebuilds.append(1) or ProcessTable.clear(table, *a, **k)

        # same processes, one value changed: the cell is updated, the table is not rebuilt
        table.move_cursor(row=1, animate=False)
        procs[0].sm_util = 77
        table.update_processes(snaps)
        assert not rebuilds
        assert table.cursor_row == 1
        assert table.get_cell(f"0:{procs[0].pid}", "sm").plain == "77%"

        # a process went away: rebuild, and the cursor stays on the process it was on
        snaps[0].processes.remove(procs[0])
        table.update_processes(snaps)
        assert rebuilds == [1]
        assert table.row_count == len(procs) - 1
        assert table.selected_process() == (0, procs[1].pid)


# ------------------------------------------------------------------- v0.2
def test_dump_refuses_nvidia_smi_flags():
    for argv in (["--dump", "-q"], ["--dump", "--classic"]):
        with pytest.raises(SystemExit):
            cli.decide(argv, True)


def test_parse_indices_accepts_uuids_and_bus_ids():
    assert cli.parse_indices("1, GPU-9d06d26f-4b35-dc7b-3fd7-4ef30ba3b554,0,2d:00.0") == [
        0,
        1,
        "GPU-9d06d26f-4b35-dc7b-3fd7-4ef30ba3b554",
        "2d:00.0",
    ]


def test_resolve_indices():
    ids = [(0, "GPU-aaaaaaaa-0000", "00000000:01:00.0"), (1, "GPU-bbbbbbbb-0000", "00000000:2D:00.0")]
    assert cli.resolve_indices(None, ids) is None
    assert cli.resolve_indices([3, 0], []) == [0, 3]  # plain indices need no lookup
    assert cli.resolve_indices(["GPU-BBBBBBBB-0000"], ids) == [1]  # case-insensitive
    # nvidia-smi prints an 8-digit domain; lspci prints 4 digits or none
    for bus in ("00000000:2d:00.0", "0000:2D:00.0", "2d:00.0"):
        assert cli.resolve_indices([bus], ids) == [1]
    assert cli.resolve_indices([0, "2d:00.0", "GPU-aaaaaaaa-0000"], ids) == [0, 1]
    with pytest.raises(SystemExit, match="no GPU matches"):
        cli.resolve_indices(["GPU-cccccccc-0000"], ids)


def test_dump_prints_json_without_identifying_data(capsys):
    assert cli.main(["--dump", "--mock", "2", "--seed", "3", "-i", "21:00.0"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == 1 and data["backend"] == "MockBackend"
    (gpu,) = data["gpus"]
    assert gpu["index"] == 1 and gpu["uuid"] == "GPU-<redacted>"
    assert gpu["detail"]["vbios"] and gpu["mem_total"] > 0
    assert gpu["processes"] and all(set(p) == {"kind", "used_memory", "sm_util", "mem_util"} for p in gpu["processes"])
    assert "hostname" not in data["system"]


def test_mock_does_not_start_near_full_vram():
    for seed in range(40):
        assert all(s.mem_pct < 90 for s in MockBackend(8, seed=seed).poll())


def test_card_title_badges():
    (snap,) = MockBackend(1, seed=1).poll()
    snap.clock_reasons = 0x40 | 0x20 | 0x04 | 0x01
    title = card_title(snap)
    assert title.plain.count("THERMAL") == 1 and "POWER" not in title.plain
    assert any(span.style.bgcolor is not None for span in title.spans)
    snap.clock_reasons = None
    assert not card_title(snap).spans


def test_card_subtitle_flags_a_narrow_link():
    (snap,) = MockBackend(1, seed=1).poll()
    assert "supports" not in card_subtitle(snap).plain
    snap.pcie_gen, snap.pcie_width = 4, 8
    assert "PCIe 4.0 x8 ▼ card supports 4.0 x16" in card_subtitle(snap).plain


async def test_first_poll_runs_in_the_worker():
    calls = []

    class Spy(MockBackend):
        def system_info(self):
            calls.append(("info", threading.current_thread() is threading.main_thread()))
            return super().system_info()

        def poll(self, indices=None):
            calls.append(("poll", threading.current_thread() is threading.main_thread()))
            return super().poll(indices)

    app = NvPulse(Spy(1, seed=5), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.4)
        assert calls[:2] == [("info", False), ("poll", False)]  # never on the UI thread
        assert "(mock)" in app.header.info.driver_version
        assert len(app.cards) == 1


async def test_backend_is_not_closed_under_a_running_poll():
    events = []

    class Slow(MockBackend):
        def poll(self, indices=None):
            events.append("poll start")
            time.sleep(0.4)
            events.append("poll end")
            return super().poll(indices)

        def close(self):
            events.append("close")

    app = NvPulse(Slow(1, seed=5), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.1)  # leave while the first poll is still inside the backend
    assert events == ["poll start", "poll end", "close"]


async def test_hide_graphics_toggle():
    app = NvPulse(MockBackend(8, seed=7), interval=3600)
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause(0.4)
        table = app.query_one(ProcessTable)
        procs = [p for s in app._snaps for p in s.processes]
        graphics = [p for p in procs if p.kind == "G"]
        assert graphics and table.row_count == len(procs)
        await pilot.press("g")
        assert table.row_count == len(procs) - len(graphics)
        assert f"{len(graphics)} graphics hidden" in str(app.query_one("#procs").border_title)
        await pilot.press("g")
        assert table.row_count == len(procs)

    app = NvPulse(MockBackend(8, seed=7), interval=3600, hide_graphics=True)
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause(0.4)
        assert app.query_one(ProcessTable).row_count == len(procs) - len(graphics)


async def test_detail_view_opens_steps_and_closes():
    app = NvPulse(MockBackend(3, seed=7), interval=0.2)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.5)
        gpu, _pid = app.query_one(ProcessTable).selected_process()
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert isinstance(app.screen, GpuDetailScreen) and app.detail_index == gpu
        view = app.screen.query_one(DetailView)
        assert view.snap.index == gpu and view.detail is not None and view.detail.index == gpu
        text = "\n".join(line.plain for line in view.render().renderables)
        assert "VBIOS 95.02." in text and "Thermals" in text and "⣀" in text

        await pilot.press("right")
        await pilot.pause(0.5)
        assert app.detail_index == (gpu + 1) % 3 and view.detail.index == app.detail_index

        await pilot.press("k")  # main-screen keys must not act on rows hidden behind the view
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ConfirmKill)

        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, GpuDetailScreen) and app.detail_index is None


async def test_clicking_a_card_opens_its_detail_view():
    app = NvPulse(MockBackend(2, seed=7), interval=3600)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.4)
        await pilot.click("#gpu-1")
        await pilot.pause(0.3)
        assert isinstance(app.screen, GpuDetailScreen) and app.detail_index == 1


async def test_detail_is_only_polled_while_the_view_is_open():
    asked = []

    class Spy(MockBackend):
        def detail(self, index):
            asked.append(index)
            return super().detail(index)

    app = NvPulse(Spy(1, seed=7), interval=0.1)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.5)
        assert asked == []
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert asked and set(asked) == {0}
        await pilot.press("escape")
        await pilot.pause(0.3)
        seen = len(asked)
        await pilot.pause(0.4)
        assert len(asked) == seen


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
async def test_exit_signals_shut_down_cleanly(sig):
    closed = []

    class Spy(MockBackend):
        def close(self):
            closed.append(True)

    app = NvPulse(Spy(1, seed=5), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        os.kill(os.getpid(), sig)
        await pilot.pause(0.3)
    assert app.return_code == 128 + sig
    assert closed == [True]


async def test_poll_finishing_during_shutdown_is_ignored():
    app = NvPulse(MockBackend(1, seed=5), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        snaps = app._snaps
    app.apply_snapshots(snaps)  # the DOM is gone: must be a no-op, not NoMatches


async def test_quitting_with_the_detail_view_open_under_fast_polling():
    """A poll landing while the detail screen was being torn down raised NoMatches."""
    for _ in range(3):
        app = NvPulse(MockBackend(1, seed=7), interval=0.02)
        async with app.run_test(size=(130, 36)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("enter")
            await pilot.pause(0.2)
        assert app.return_code in (0, None)


async def test_running_version_is_shown_in_header_and_help():
    from nvpulse import __version__
    from nvpulse.ui.modals import help_text

    app = NvPulse(MockBackend(1, seed=5), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        assert f"nvpulse  v{__version__} " in app.header.render().plain
    assert f"nvpulse {__version__}" in help_text().plain


async def test_failing_detail_does_not_freeze_the_dashboard():
    polls = []

    class Broken(MockBackend):
        def poll(self, indices=None):
            polls.append(1)
            return super().poll(indices)

        def detail(self, index):
            raise RuntimeError("boom")

    app = NvPulse(Broken(1, seed=7), interval=0.1)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.2)
        applied = []
        original = app.apply_snapshots
        app.apply_snapshots = lambda *a, **k: (applied.append(1), original(*a, **k))[1]
        await pilot.pause(0.6)
        assert isinstance(app.screen, GpuDetailScreen)
        assert len(applied) >= 3  # the cards behind the view keep updating
        warnings = [n.message for n in app._notifications if "detail readings failed" in n.message]
        assert len(warnings) == 1  # said once, not on every poll


def test_dump_survives_a_failing_detail(capsys):
    class Broken(MockBackend):
        def detail(self, index):
            raise RuntimeError("boom")

    from nvpulse import dump

    data = json.loads(dump.dumps(Broken(1, seed=3)))
    assert data["gpus"][0]["detail"] is None and data["gpus"][0]["mem_total"] > 0
