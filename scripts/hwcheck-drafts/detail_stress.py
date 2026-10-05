"""Open the detail view and quit at slightly different moments, many times.

Shutting NVML down while a poll was still inside the driver used to segfault.
"""

from __future__ import annotations

import asyncio

from nvpulse.backend.nvml import NvmlBackend
from nvpulse.ui.app import NvPulse

CYCLES = 25


async def once(i: int) -> None:
    app = NvPulse(NvmlBackend(), interval=0.1)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.25 + 0.013 * i)


if __name__ == "__main__":
    for cycle in range(CYCLES):
        asyncio.run(once(cycle))
    print(f"{CYCLES} open/close cycles with detail polling: ok")
