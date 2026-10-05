import pytest

from nvpulse import cli
from nvpulse.backend.mock import MockBackend
from nvpulse.ui.app import NvPulse
from nvpulse.ui.widgets import GpuCard, ProcessTable


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
