"""Time the pieces of one poll on real hardware, then profile a few table updates."""

from __future__ import annotations

import asyncio
import cProfile
import io
import pstats
import time

from nvpulse.backend.nvml import NvmlBackend
from nvpulse.procinfo import enrich
from nvpulse.ui.app import NvPulse


def avg_ms(fn, runs: int = 20) -> float:
    start = time.perf_counter()
    for _ in range(runs):
        fn()
    return (time.perf_counter() - start) / runs * 1000


async def main() -> None:
    backend = NvmlBackend()
    backend.poll()
    print(f"poll                 {avg_ms(backend.poll):6.2f} ms")
    print(f"poll + enrich        {avg_ms(lambda: enrich(backend.poll()[0].processes)):6.2f} ms")
    print(f"detail (GPU 0)       {avg_ms(lambda: backend.detail(0), 5):6.2f} ms")

    app = NvPulse(backend, interval=3600)
    async with app.run_test(size=(150, 46)) as pilot:
        await pilot.pause(0.5)
        snaps = app._snaps
        print(f"apply_snapshots      {avg_ms(lambda: app.apply_snapshots(snaps)):6.2f} ms")
        profile = cProfile.Profile()
        profile.enable()
        for _ in range(8):
            app.apply_snapshots(snaps)
            await pilot.pause(0.25)
        profile.disable()
        out = io.StringIO()
        pstats.Stats(profile, stream=out).sort_stats("cumulative").print_stats(25)
        print("\n".join(line[:150] for line in out.getvalue().splitlines()[:45]))


if __name__ == "__main__":
    asyncio.run(main())
