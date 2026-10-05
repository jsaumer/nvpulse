"""Drive the real app headless against real NVML and kill throwaway ffmpeg NVENC processes.

Only processes started here are ever signalled.
"""

from __future__ import annotations

import asyncio
import subprocess
import time

from nvpulse.backend.nvml import NvmlBackend
from nvpulse.ui.app import NvPulse
from nvpulse.ui.modals import ConfirmKill

FFMPEG = [
    *("ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi"),
    *("-i", "testsrc2=size=1920x1080:rate=60", "-c:v", "h264_nvenc", "-f", "null", "-"),
]


async def wait_for_row(app: NvPulse, pilot, key: str, present: bool, timeout: float = 8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.request_poll()
        await pilot.pause(0.4)
        found = key in [k.value for k in app.table.rows]
        if found == present:
            return True
    return False


async def main() -> None:
    app = NvPulse(NvmlBackend(), interval=0.5)
    async with app.run_test(size=(150, 46)) as pilot:
        await pilot.pause(1.5)
        print("rows:", app.table.row_count)
        for key, force in (("k", False), ("K", True)):
            ffmpeg = subprocess.Popen(FFMPEG, stdin=subprocess.DEVNULL)
            row = f"0:{ffmpeg.pid}"
            appeared = await wait_for_row(app, pilot, row, True)
            print(f"\n== {key}: ffmpeg pid {ffmpeg.pid} appeared in the table: {appeared}")
            if not appeared:
                ffmpeg.kill()
                continue
            await pilot.pause(2.5)  # let the 2 s utilisation look-back fill
            proc = next(p for s in app._snaps for p in s.processes if p.pid == ffmpeg.pid)
            snap = app._snaps[0]
            print(f"   process: {proc.kind} {(proc.used_memory or 0) >> 20} MiB sm={proc.sm_util} user={proc.user}")
            print(f"   gpu: util={snap.util_gpu} enc={snap.enc_util} sessions={snap.enc_sessions} fps={snap.enc_fps}")
            app.table.move_cursor(row=app.table.get_row_index(row), animate=False)
            await pilot.pause(0.1)
            await pilot.press(key)
            await pilot.pause(0.2)
            screen = app.screen
            assert isinstance(screen, ConfirmKill), type(screen).__name__
            print("   dialog open, pidfd pinned:", screen.target.pidfd is not None, "| force:", force)
            await pilot.press("y")
            await pilot.pause(0.3)
            try:
                code: int | str = ffmpeg.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = "STILL ALIVE"
                ffmpeg.kill()
            print("   ffmpeg exit:", code, "(255 or -15 for SIGTERM, -9 for SIGKILL)")
            print("   row removed:", await wait_for_row(app, pilot, row, False))

        ffmpeg = subprocess.Popen(FFMPEG, stdin=subprocess.DEVNULL)
        row = f"0:{ffmpeg.pid}"
        if await wait_for_row(app, pilot, row, True):
            app.table.move_cursor(row=app.table.get_row_index(row), animate=False)
            await pilot.press("k")
            await pilot.pause(0.2)
            await pilot.press("n")
            await pilot.pause(0.5)
            print("\n== cancel: ffmpeg still alive after 'n':", ffmpeg.poll() is None)
        ffmpeg.kill()
        ffmpeg.wait()


if __name__ == "__main__":
    asyncio.run(main())
