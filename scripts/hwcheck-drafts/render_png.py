"""Render the headless app to a PNG, to look at a screen without a terminal.

usage: render_png.py OUT.png BACKEND SIZE WAIT [THEME] [KEY ...]
  BACKEND  "real", or "mockN" / "mockN:SEED"
  SIZE     columns x rows, e.g. 140x40
  WAIT     seconds to let history fill before pressing keys
  KEY      Textual key names (enter, slash, question_mark ...); "type:text" types text

Needs `pip install playwright` and an installed Chrome (or `playwright install chromium`).
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

from playwright.async_api import async_playwright

from nvpulse.ui import render

THEMES = ("default", "high-contrast", "mono")


async def main() -> None:
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    out, kind, size, wait, *rest = sys.argv[1:]
    theme = rest.pop(0) if rest and rest[0] in THEMES else "default"
    render.set_theme(theme)
    if theme == "mono":
        os.environ["NO_COLOR"] = "1"
    from nvpulse.ui.app import NvPulse  # after the theme is set

    if kind == "real":
        from nvpulse.backend.nvml import NvmlBackend

        backend = NvmlBackend()
    else:
        from nvpulse.backend.mock import MockBackend

        count, _, seed = kind.removeprefix("mock").partition(":")
        backend = MockBackend(int(count or 2), seed=int(seed or 7))
    columns, rows = map(int, size.split("x"))
    app = NvPulse(backend, interval=0.25, theme=theme)
    app.as_root = False
    with tempfile.TemporaryDirectory() as tmp:
        async with app.run_test(size=(columns, rows)) as pilot:
            await pilot.pause(float(wait))
            for key in rest:
                if key.startswith("type:"):
                    await pilot.press(*("colon" if ch == ":" else ch for ch in key[5:]))
                else:
                    await pilot.press(key)
                await pilot.pause(0.5)
            app.save_screenshot(filename="shot.svg", path=tmp)
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:  # no bundled Chromium: use the system Chrome
                browser = await p.chromium.launch(channel="chrome")
            page = await browser.new_page()
            await page.goto((pathlib.Path(tmp) / "shot.svg").as_uri())
            await page.wait_for_timeout(700)  # the SVG loads its font from a CDN
            await (await page.query_selector("svg")).screenshot(path=out)
            await browser.close()
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
