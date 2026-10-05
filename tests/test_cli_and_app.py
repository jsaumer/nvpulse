import json
import os
import signal
import threading
import time

import pytest

from nvpulse import cli
from nvpulse.backend.mock import MockBackend
from nvpulse.backend.models import Alerts, ProcessInfo
from nvpulse.procinfo import parse_cgroup
from nvpulse.ui.app import NvPulse
from nvpulse.ui.detail import DetailView, GpuDetailScreen
from nvpulse.ui.modals import ConfirmKill, ProcessInfoScreen
from nvpulse.ui.widgets import GpuCard, ProcessTable, card_subtitle, card_title, matches, parse_filter


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


# ------------------------------------------------------------------- v0.3
HEX = "3f2a9c1b2d4e" + "0" * 52


@pytest.mark.parametrize(
    "cgroup, unit",
    [
        (f"0::/system.slice/docker-{HEX}.scope", "docker:3f2a9c1b2d4e"),  # systemd cgroup driver
        (f"0::/docker/{HEX}", "docker:3f2a9c1b2d4e"),  # cgroupfs driver
        (f"12:devices:/docker/{HEX}\n1:name=systemd:/docker/{HEX}", "docker:3f2a9c1b2d4e"),  # cgroup v1
        (
            f"0::/user.slice/user-1000.slice/user@1000.service/user.slice/libpod-{HEX}.scope/container",
            "podman:3f2a9c1b2d4e",
        ),
        (f"0::/kubepods.slice/kubepods-pod12.slice/cri-containerd-{HEX}.scope", "containerd:3f2a9c1b2d4e"),
        (f"0::/kubepods.slice/kubepods-pod12.slice/crio-{HEX}.scope", "crio:3f2a9c1b2d4e"),
        (f"11:devices:/kubepods/besteffort/pod9f/{HEX}", "k8s:3f2a9c1b2d4e"),
        ("0::/lxc.payload.build01/system.slice/foo.service", "lxc:build01"),
        ("0::/lxc/web/init.scope", "lxc:web"),
        ("0::/system.slice/ollama.service", "ollama"),
        ("0::/system.slice/system-getty.slice/getty@tty1.service", "getty@tty1"),
        # a desktop session runs every app as a user unit: not worth a label
        ("0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-org.kde.konsole@a1.service", ""),
        ("0::/user.slice/user-1000.slice/user@1000.service", ""),
        ("0::/user.slice/user-1000.slice/session-2.scope", ""),
        ("0::/", ""),
        ("", ""),
        ("not a cgroup file", ""),
        (f"0::/system.slice/docker-{HEX[:40]}.scope", ""),  # not a full container ID
    ],
)
def test_parse_cgroup(cgroup, unit):
    assert parse_cgroup(cgroup) == unit


def proc(pid=1, gpu=0, kind="C", user="alice", name="python", cmd="python train.py", unit="", mem=1 << 30):
    return ProcessInfo(gpu, pid, kind, mem, name=name, user=user, cmdline=cmd, unit=unit)


def test_filter_terms():
    p = proc(pid=4242, gpu=1, user="Alice", cmd="python train.py --model llama", unit="docker:3f2a9c1b2d4e")
    for query in (
        "llama",
        "PYTHON llama",
        "user:ali",
        "gpu:1",
        "pid:4242",
        "type:c",
        "unit:docker",
        "gpu:1 user:alice train",
    ):
        assert matches(p, parse_filter(query)), query
    for query in ("vllm", "user:bob", "gpu:0", "gpu:11", "pid:42", "type:g", "unit:podman", "llama user:bob"):
        assert not matches(p, parse_filter(query)), query
    assert parse_filter("") == [] and parse_filter("   ") == []
    assert parse_filter("user:") == [("", "user:")]  # an empty field value is just text
    assert parse_filter("http://x") == [("", "http://x")]  # unknown field: plain text too
    assert len(parse_filter("x " * 500)) <= 40  # capped


class Fixed(MockBackend):
    """One mock GPU with exactly the processes given."""

    def __init__(self, procs):
        super().__init__(1, seed=1)
        self.procs = procs

    def poll(self, indices=None):
        snaps = super().poll(indices)
        snaps[0].processes = list(self.procs)
        return snaps


LONG = "/opt/app/bin/server " + "--flag=value " * 60


async def test_process_table_fits_its_width():
    procs = [proc(pid=10, cmd=LONG), proc(pid=11, cmd="short", unit="ollama", mem=2 << 30)]
    for size, unit_shown in (((160, 40), True), ((100, 30), False)):  # narrow: UNIT gives way to the command
        app = NvPulse(Fixed(procs), interval=3600)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.4)
            table = app.query_one(ProcessTable)
            assert table.virtual_size.width <= table.size.width  # no horizontal scrolling
            cmd = table.get_cell("0:10", "cmd").plain
            assert cmd.endswith("…") and len(cmd) < len(LONG)
            assert ("unit" in [c.value for c in table.columns]) is unit_shown


async def test_unit_column_hidden_columns_and_unit_sort():
    plain = [proc(pid=10), proc(pid=11, mem=2 << 30)]
    app = NvPulse(Fixed(plain), interval=3600, hidden_columns=["user", "sm"])
    async with app.run_test(size=(140, 34)) as pilot:
        await pilot.pause(0.4)
        keys = [c.value for c in app.query_one(ProcessTable).columns]
        assert keys == ["gpu", "pid", "type", "vram", "cmd"]  # hidden ones gone, no empty UNIT column

    mixed = [
        proc(pid=1, mem=9 << 30),
        proc(pid=2, unit="ollama"),
        proc(pid=3, unit="docker:aaaaaaaaaaaa"),
        proc(pid=4, unit="ollama", mem=3 << 30),
    ]
    app = NvPulse(Fixed(mixed), interval=3600, sort="unit")
    async with app.run_test(size=(140, 34)) as pilot:
        await pilot.pause(0.4)
        table = app.query_one(ProcessTable)
        assert [k.value for k in table.rows] == ["0:3", "0:4", "0:2", "0:1"]  # grouped, unlabelled last


async def test_filter_flow():
    procs = [
        proc(pid=10, cmd="ollama runner", user="ollama"),
        proc(pid=11, cmd="python train.py"),
        proc(pid=12, cmd="blender"),
    ]
    app = NvPulse(Fixed(procs), interval=3600)
    async with app.run_test(size=(140, 34)) as pilot:
        await pilot.pause(0.4)
        table = app.query_one(ProcessTable)
        box = app.query_one("#filter")
        assert not box.display
        await pilot.press("slash")
        assert box.display and box.has_focus
        await pilot.press(*"ollama")
        assert table.row_count == 1 and table.filtered == 2
        assert "filter: ollama" in str(app.query_one("#procs").border_title)

        # letters typed into the filter are text, not commands
        await pilot.press("k", "q")
        await pilot.pause(0.2)
        assert app.is_running and not isinstance(app.screen, ConfirmKill) and box.value == "ollamakq"
        assert table.row_count == 0

        await pilot.press("backspace", "backspace", "enter")
        assert table.has_focus and box.display and table.row_count == 1  # filter stays, focus returns
        await pilot.press("escape")
        assert not box.display and box.value == "" and table.row_count == 3 and table.has_focus

        await pilot.press("slash", "enter")  # opened and left empty: put it away again
        assert not box.display


async def test_process_info_screen_shows_the_full_command():
    app = NvPulse(Fixed([proc(pid=10, cmd=LONG, unit="docker:3f2a9c1b2d4e")]), interval=3600)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        await pilot.press("i")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ProcessInfoScreen)
        from nvpulse.ui.modals import process_info

        text = process_info(app.screen.proc).plain
        assert LONG.strip() in text and "docker:3f2a9c1b2d4e" in text and "compute" in text
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ProcessInfoScreen)


def test_alert_limits():
    (snap,) = MockBackend(1, seed=1).poll()
    snap.temp, snap.mem_used, snap.mem_total = 80, 90, 100
    assert Alerts().active(snap) == []
    assert Alerts(temp=80).active(snap) == ["HOT"]
    assert Alerts(temp=81, vram=90).active(snap) == ["VRAM"]
    assert Alerts(temp=70, vram=50).active(snap) == ["HOT", "VRAM"]
    snap.temp = None
    assert Alerts(temp=0).active(snap) == []
    assert "HOT" not in card_title(snap, Alerts(temp=0)).plain and "VRAM" in card_title(snap, Alerts(vram=10)).plain


async def test_alert_is_announced_once_per_crossing():
    app = NvPulse(MockBackend(1, seed=1), interval=3600, alerts=Alerts(temp=85))
    bells = []
    app.bell = lambda: bells.append(1)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        (snap,) = app._snaps
        for temp in (40, 90, 91, 92, 40, 95):  # fed straight in: no race with the poll worker
            snap.temp = temp
            app.apply_snapshots([snap])
        await pilot.pause(0.2)  # notifications are delivered as messages
        said = [n.message for n in app._notifications if "HOT limit" in n.message]
        assert len(said) == 2 and len(bells) == 2  # 90 and 95, not 91 or 92
        assert "HOT" in str(app.query_one("#gpu-0").border_title)


async def test_session_energy_adds_up():
    app = NvPulse(MockBackend(1, seed=1), interval=1.0, cost_per_kwh=0.5, currency="€")
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        (snap,) = app._snaps
        snap.power = 360.0
        app.energy_wh[0] = 0.0
        for gap, expected in ((1.0, 0.1), (1.0, 0.2), (600.0, 0.6)):  # a pause is capped at 3 intervals + 1 s
            app._last_energy = time.monotonic() - gap
            app._count_energy([snap])
            assert app.energy_wh[0] == pytest.approx(expected, abs=0.01)
        assert app._session(0) == "0.6 Wh (€0.00)"
        assert app._session(7) == ""


async def test_idle_card_skips_repaints_but_a_spinning_fan_does_not():
    app = NvPulse(MockBackend(1, seed=1), interval=3600)
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        card = app.query_one(GpuCard)
        snap = app._snaps[0]
        snap.fan, snap.fans, snap.temp = 0.0, [0.0, 0.0], 40
        card.update_snapshot(snap)
        for _ in range(200):  # let the easing finish
            card.tick(0.05)
        paints = []
        card.refresh = lambda *a, **k: paints.append(1)
        for _ in range(20):
            card.tick(0.05)
        assert paints == []

        snap.fan, snap.fans = 60.0, [60.0, 60.0]
        del card.refresh
        card.update_snapshot(snap)
        card.refresh = lambda *a, **k: paints.append(1)
        for _ in range(5):
            card.tick(0.05)
        assert len(paints) == 5


async def test_detail_view_has_a_time_axis_and_ranges():
    app = NvPulse(MockBackend(1, seed=7), interval=0.05)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("enter")
        await pilot.pause(0.4)
        view = app.screen.query_one(DetailView)
        text = "\n".join(line.plain for line in view.render().renderables)
        assert text.count(" avg ") == 4 and text.rstrip().count("now") >= 1 and "┄" in text
        assert view._span(100) > 0
        assert "this session" in text


def test_card_shows_encoder_sessions():
    (snap,) = MockBackend(1, seed=1).poll()
    card = GpuCard(0)
    card.update_snapshot = None  # not mounted: only the pure line builder is used
    card.snap = snap
    snap.enc_util, snap.enc_sessions, snap.enc_fps = 34.0, 2, 60
    assert "ENC 34% (2 sessions · 60 fps)" in card._detail_lines(100, False)[1].plain
    snap.enc_sessions = 0
    assert "session" not in card._detail_lines(100, False)[1].plain


def test_wsl_fallback_location(tmp_path, monkeypatch):
    smi = tmp_path / "nvidia-smi"
    smi.write_text("#!/bin/sh\n")
    smi.chmod(0o755)
    monkeypatch.delenv("NVPULSE_REAL_SMI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    monkeypatch.setattr(cli, "FALLBACK_SMI", (str(smi),))
    assert cli.find_real_nvidia_smi() == str(smi)
    smi.chmod(0o757)  # the fallback gets the same trust check as anything on PATH
    assert cli.find_real_nvidia_smi() is None


async def test_high_contrast_theme_marks_the_app():
    app = NvPulse(MockBackend(1, seed=1), interval=3600, theme="high-contrast")
    async with app.run_test(size=(120, 34)) as pilot:
        await pilot.pause(0.3)
        assert app.has_class("-hc")
        assert app.query_one("#procs").styles.border_top[1].hex.lower() == "#8b949e"


async def test_process_info_scrolls_when_the_command_is_taller_than_the_screen():
    app = NvPulse(Fixed([proc(pid=10, cmd="x" * 1024)]), interval=3600)
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause(0.4)
        await pilot.press("i")
        await pilot.pause(0.3)
        dialog = app.screen.query_one("#dialog")
        assert dialog.max_scroll_y > 0  # the rest of the command is reachable
        await pilot.press("end")
        await pilot.pause(0.2)
        dialog.scroll_end(animate=False)
        await pilot.pause(0.2)
        assert dialog.scroll_y == dialog.max_scroll_y
