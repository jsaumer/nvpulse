# Contributing to nvpulse

Thanks for your interest! This is a small project, so the process is light.

## Dev setup

```bash
git clone <repo-url> nvpulse && cd nvpulse
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

You don't need a GPU. Everything works against the mock backend:

```bash
nvpulse --mock 3
```

For logging and debugging, use Textual's dev console:

```bash
pip install textual-dev
textual console                      # terminal 1: shows log() output and errors
TEXTUAL=devtools nvpulse --mock 2    # terminal 2
```

## Checks

Run these before opening a PR. CI runs the same ones.

```bash
ruff check .
ruff format --check .
pytest
```

- `tests/test_render.py` covers the pure rendering helpers (gauges, sparklines, fan art).
- `tests/test_cli_and_app.py` covers the CLI routing and drives the full app headless
  with Textual's `run_test()` pilot.
- `tests/test_nvml.py` runs the NVML backend against a fake `pynvml` that replays
  values recorded from real hardware. Output from `nvpulse --dump` is a good
  source for more of these.
- `tests/test_security.py` holds a regression test for every hardening measure.

If you change anything visual, regenerate the screenshots and include them in the PR:

```bash
python scripts/make_screenshots.py          # SVG stills
python scripts/make_screenshots.py --gif    # + demo.gif (needs playwright + pillow, and Chrome or Playwright's Chromium)
```

## Project layout

```
src/nvpulse/
  cli.py              argument parsing, nvidia-smi passthrough, backend selection
  dump.py             --dump: one anonymised JSON snapshot on stdout
  procinfo.py         PID -> user / name / cmdline enrichment (psutil)
  sanitize.py         untrusted-text cleaning + secret redaction
  killer.py           safe signalling (pidfd pinning, PID-reuse checks)
  backend/
    models.py         GpuSnapshot / GpuDetail / ProcessInfo / SystemInfo + Backend interface
    nvml.py           real hardware via NVML (nvidia-ml-py)
    mock.py           simulated GPUs
  ui/
    render.py         pure Rich renderers: gradients, gauges, heat bar, sparkline, fan art
    widgets.py        HeaderBar, GpuCard, ProcessTable
    detail.py         per-GPU detail view (modal)
    modals.py         kill confirmation + help screens
    app.py            Textual App: poll worker, animation clock, layout
tests/                pytest suite
scripts/              maintenance scripts (screenshots)
docs/                 architecture, roadmap, troubleshooting, images
```

See [docs/architecture.md](docs/architecture.md) for how data and animation flow.

## Conventions

- **Python 3.10+**, type hints everywhere, `from __future__ import annotations`.
- **Ruff** handles linting and formatting (config in `pyproject.toml`, line length 120).
- **Keep rendering pure.** Put drawing logic in `ui/render.py` as functions that
  return `rich.text.Text`, so it stays unit-testable. Widgets only lay out.
- **Treat process data as hostile.** Anything from `/proc`, psutil or NVML must go
  through `sanitize.clean()` before display, and must never be rendered as
  markup: use `rich.text.Text` (also for border titles) or `markup=False`. For
  notifications use `App._say()`. See [docs/security.md](docs/security.md).
- **Never let a missing metric crash the UI.** Backends return `None` for anything
  unsupported, and the UI shows "n/a".
- **Keep NVML off the UI thread.** All backend polling goes through the threaded worker.
- **Commits:** short imperative subject (`Add PCIe throughput row`), with detail in
  the body if needed.
- **Changelog:** add a line under `## [Unreleased]` in `CHANGELOG.md` for any
  user-visible change.

## Adding a metric

1. Add the field to `GpuSnapshot` in `backend/models.py` (default `None`).
2. Populate it in `backend/nvml.py` through `_safe(...)`, and in `backend/mock.py`.
3. Render it in `GpuCard` (and add a `Tween` key if it should animate).
4. Add a test.

If the NVML call is slow (more than a millisecond or two) or only interesting
when someone goes looking, put it in `GpuDetail` / `Backend.detail()` instead,
and render it in `ui/detail.py`. It is then only polled while the detail view is open.

## Releasing

1. Bump `__version__` in `src/nvpulse/__init__.py`, and turn `[Unreleased]` in
   `CHANGELOG.md` into the new version with a fresh empty `[Unreleased]` above it.
2. Update the tag in the README's `pipx install git+https://…@vX.Y.Z` line.
3. Commit, then `git tag -a vX.Y.Z -m "vX.Y.Z"` and push the commit and the tag.
4. Publish a GitHub release for the tag, with the changelog section as its notes.

People install from GitHub at a tag; nvpulse is not on PyPI. A PyPI upload makes
the source public whatever the repository's visibility, and a version number can
never be reused, so it is a separate, deliberate step: `.github/workflows/release.yml`
only runs when started by hand from a version tag (Actions → Release → Run workflow).
It uses [trusted publishing](https://docs.pypi.org/trusted-publishers/), so there
is no token to manage, but it needs a one-time setup by the project owner first:
on PyPI, add a (pending) trusted publisher for owner `jsaumer`, repository
`nvpulse`, workflow `release.yml`, environment `pypi`.

## Reporting security issues

Please don't use public issues. See [SECURITY.md](SECURITY.md).

## Reporting bugs

Please include the output of `nvpulse --version` and `nvidia-smi -L`, your
driver version, your terminal emulator, and a screenshot if it's visual.
