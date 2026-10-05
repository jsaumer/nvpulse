# CLAUDE.md: nvpulse

Animated, btop-style terminal dashboard for NVIDIA GPUs that launches like
`nvidia-smi`. Python 3.10+, Textual + Rich, NVML via `nvidia-ml-py`, `psutil`.
Repo: https://github.com/jsaumer/nvpulse (MIT). Commands: `nvpulse`, alias `nvidia-smi+`.

## Commands

```bash
pip install -e '.[dev]'          # dev install (venv recommended)
pytest -q                        # 75 tests; no GPU needed
ruff check . && ruff format --check .
nvpulse --mock 3                 # run with simulated GPUs
nvpulse                          # real hardware (needs NVIDIA driver / NVML)
python scripts/make_screenshots.py [--gif]   # regenerate docs/images (gif needs playwright + pillow)
```

CI (`.github/workflows/ci.yml`) runs lint, tests on 3.10–3.13, `pip-audit --strict`
and a build. Keep it green.

## Layout

```
src/nvpulse/
  cli.py        argparse (allow_abbrev=False), passthrough to real nvidia-smi, value clamping
  procinfo.py   pid -> user/name/cmdline/start time via psutil; sanitises + redacts
  sanitize.py   clean() for untrusted text, redact() for secrets
  killer.py     safe signalling: pidfd pinning, start-time PID-reuse check, PID guards
  backend/      models.py (dataclasses + Backend iface), nvml.py (real), mock.py (simulated)
  ui/           render.py (pure Rich renderers), widgets.py, modals.py, app.py (Textual App)
tests/          test_render.py, test_cli_and_app.py, test_security.py, test_nvml.py (fake pynvml)
docs/           architecture.md, security.md, roadmap.md, troubleshooting.md, images/
```

Read `docs/architecture.md` before structural changes and `docs/security.md`
before touching anything that displays process data, signals processes or execs binaries.

## Architecture in brief

- **Two clocks.** The poll timer runs `backend.poll()` and `enrich()` in a thread
  worker, then `apply_snapshots()` on the UI thread. The animation timer (`--fps`)
  calls `GpuCard.tick(dt)`: tweening, fan phase, pulses. No I/O ever happens on
  the animation path.
- **Backends return `None` for anything unsupported.** Every NVML call goes through
  `_safe()`. The UI shows "n/a".
- **Rendering is pure.** Drawing logic lives in `ui/render.py` as functions returning
  `rich.text.Text`, and is unit-tested. Widgets only lay out.
- **Layout.** 1 GPU gives an expanded card; 2+ GPUs, or a terminal under 30 rows,
  gives a compact grid. `c` toggles.

## Rules (non-negotiable)

1. **Process data is hostile.** Anything from `/proc`, psutil or NVML must pass
   through `sanitize.clean()` before display. Never render it as markup: use
   `rich.text.Text`, `Static(..., markup=False)`, or `textual.markup.escape` (border
   titles are always parsed as markup). Use `App._say()` for notifications, never
   `notify()` with interpolated data.
2. **All signals go through `killer.py`** (`prepare()` when the dialog opens, then
   `send()`). Never call `os.kill` directly. Mock mode must never touch real PIDs.
3. **No shell.** Exec via argument lists only (`os.execve`). Passthrough binaries must
   pass `_trusted_executable()`.
4. **Keep NVML off the UI thread.**
5. **No network access, telemetry or persistent writes** without an explicit decision
   recorded in `docs/security.md`.
6. **GitHub Actions stay pinned to full commit SHAs** with a `# vX.Y.Z` comment.
   Workflow `permissions` stay at `contents: read` unless a job truly needs more.
7. Every user-visible change gets a line under `## [Unreleased]` in `CHANGELOG.md`.
   Visual changes mean regenerating screenshots.
8. Add or adjust tests with every behaviour change. Security fixes get a regression
   test in `tests/test_security.py`.

## Gotchas

- **Textual ≥ 4.0 is required.** `notify(markup=False)` and `textual.markup` don't
  exist in older versions. The tests were verified on 4.0 and 8.2.
- **Textual strips only BEL/BS/VT/FF/CR** from output. ESC and C1 pass through,
  which is why `sanitize.clean()` exists.
- **`DataTable` repaints cell backgrounds,** so gauges inside it use `gauge(..., solid=True)`.
- **`ModalScreen` CSS must go in `App.CSS`** (via `MODAL_CSS`). `DEFAULT_CSS` on a
  screen subclass is scoped and won't apply.
- **Tests drive the real app headless** with `app.run_test()` and `pilot`. Use
  `MockBackend(n, seed=…)` for determinism. `MockBackend.kill()` exists only on
  the mock, and the app uses it to detect mock mode.
- **Containers and CI often run as root,** which shows the ROOT badge. The screenshot
  script forces `app.as_root = False`. Root-specific branches in `_trusted_executable`
  only run when `geteuid() == 0`.
- **Fan animation speed is capped** (`OMEGA_MAX = 7` rad/s at 20 fps) to stay under
  the wagon-wheel aliasing limit. Don't raise it without checking per-frame step
  < half a blade sector.
- **`ENABLE_COMMAND_PALETTE = False` is deliberate** (see security.md §6).

## Style

Ruff (line length 120, config in `pyproject.toml`), type hints everywhere,
`from __future__ import annotations`, short imperative commit subjects.
