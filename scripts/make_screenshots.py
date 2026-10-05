#!/usr/bin/env python3
"""Regenerate the README screenshots (and optionally an animated demo GIF).

Runs the app headless against the mock backend, so no GPU is needed.

    python scripts/make_screenshots.py            # SVG stills -> docs/images/
    python scripts/make_screenshots.py --gif      # also docs/images/demo.gif

The GIF path needs extra tools: ``pip install playwright pillow`` and a Chromium
that Playwright can launch.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from nvpulse.backend.mock import MockBackend
from nvpulse.ui.app import NvPulse

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"

SHOTS = [
    # name, gpu count, terminal size, keys to press before capture
    ("single-gpu", 1, (130, 36), []),
    ("multi-gpu", 4, (150, 40), []),
    ("eight-gpu", 8, (200, 50), []),
    ("kill-confirm", 1, (130, 36), ["k"]),
    ("help", 2, (120, 34), ["question_mark"]),
]


async def stills() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, n, size, keys in SHOTS:
        app = NvPulse(MockBackend(n, seed=7), interval=0.25)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(4.0)  # let history and sparklines fill a little
            for key in keys:
                await pilot.press(key)
                await pilot.pause(0.4)
            app.save_screenshot(filename=f"{name}.svg", path=str(OUT))
        print("wrote", OUT / f"{name}.svg")


async def gif(frames: int = 36, fps: int = 12) -> None:
    from PIL import Image
    from playwright.async_api import async_playwright

    with tempfile.TemporaryDirectory() as tmp:
        svgs = []
        app = NvPulse(MockBackend(2, seed=11), interval=0.25, fps=fps)
        async with app.run_test(size=(130, 30)) as pilot:
            await pilot.pause(4.0)
            for i in range(frames):
                path = Path(tmp) / f"f{i:03d}.svg"
                app.save_screenshot(filename=path.name, path=tmp)
                svgs.append(path)
                await pilot.pause(1 / fps)

        pngs = []
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            for svg in svgs:
                await page.goto(svg.as_uri())
                png = svg.with_suffix(".png")
                await (await page.query_selector("svg")).screenshot(path=str(png))
                pngs.append(png)
            await browser.close()

        images = [Image.open(p).convert("P", palette=Image.Palette.ADAPTIVE) for p in pngs]
        images[0].save(
            OUT / "demo.gif", save_all=True, append_images=images[1:], duration=int(1000 / fps), loop=0, optimize=True
        )
    print("wrote", OUT / "demo.gif")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gif", action="store_true", help="also render docs/images/demo.gif")
    args = ap.parse_args()
    asyncio.run(stills())
    if args.gif:
        asyncio.run(gif())


if __name__ == "__main__":
    main()
