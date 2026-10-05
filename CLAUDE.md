# CLAUDE.md: nvpulse

Animated, btop-style terminal dashboard for NVIDIA GPUs that launches like
`nvidia-smi`. Python 3.10+, Textual + Rich, NVML via `nvidia-ml-py`, `psutil`.
Repo: https://github.com/jsaumer/nvpulse (MIT). Commands: `nvpulse`, alias `nvidia-smi+`.

## Commands

```bash
pip install -e '.[dev]'          # dev install (venv recommended)
pytest -q                        # 213 tests; no GPU needed
ruff check . && ruff format --check .
nvpulse --mock 3                 # run with simulated GPUs
nvpulse                          # real hardware (needs NVIDIA driver / NVML)
nvpulse --dump                   # one anonymised JSON snapshot (good source for test fixtures)
nvpulse --once                   # one plain snapshot, no TUI (quick check without a terminal)
python scripts/hwcheck-drafts/compare_smi.py   # real-GPU checks (see that folder's README); drafts, not CI
python scripts/make_screenshots.py [--gif]   # regenerate docs/images (gif needs playwright + pillow; uses system Chrome if present)
```

CI (`.github/workflows/ci.yml`) runs lint, tests on 3.10–3.14, the same tests on
the oldest allowed dependency versions (`test-minimum`), `pip-audit --strict`
and a build. Keep it green. When a dependency floor in `pyproject.toml` changes,
change the pins in `test-minimum` to match. `release.yml` publishes to PyPI (trusted publishing)
but only when started by hand from a version tag; tags and GitHub releases never
trigger it. nvpulse is not on PyPI: people install from GitHub at a tag, and the
README's install line carries the current tag. Release steps are in `CONTRIBUTING.md`.

**The repository is private until further notice.** Don't publish to PyPI or run
the release workflow, and keep public-facing work under "If the project goes
public" in `docs/roadmap.md`.

**Where things stand (after v0.3.0).** The owner is running 0.3 to collect
feedback before more features. Fixes go out as 0.3.x. The next planned work is
the hardware check at the top of v0.4 in `docs/roadmap.md`. Much of v0.2 and
v0.3 has only been verified with mocks, fakes and headless renders on one
desktop GPU: treat reports from real use as likely real bugs.

## Layout

```
src/nvpulse/
  cli.py        argparse (allow_abbrev=False), passthrough to real nvidia-smi, value clamping, -i selectors,
                flag > settings file > default resolution
  config.py     optional ~/.config/nvpulse/config.toml: read-only, validated, trust-checked
  dump.py       --dump: anonymised JSON snapshot on stdout
  once.py       --once: one plain snapshot on stdout
  procinfo.py   pid -> user/name/cmdline/start time via psutil, container/service from cgroup;
                sanitises + redacts
  sanitize.py   clean() for untrusted text, redact() for secrets
  killer.py     safe signalling: pidfd pinning, start-time PID-reuse check, PID guards
  backend/      models.py (dataclasses + Backend iface), nvml.py (real), mock.py (simulated)
  ui/           render.py (pure Rich renderers), widgets.py, detail.py (GPU detail view),
                modals.py, app.py (Textual App)
tests/          test_render.py, test_cli_and_app.py, test_security.py, test_nvml.py (fake pynvml)
.github/        workflows/ci.yml, workflows/release.yml (PyPI), dependabot.yml
docs/           architecture.md, configuration.md, security.md, roadmap.md, troubleshooting.md, images/
```

Read `docs/architecture.md` before structural changes and `docs/security.md`
before touching anything that displays process data, signals processes or execs binaries.

## Architecture in brief

- **Two clocks.** The poll timer runs `backend.poll()` and `enrich()` in a thread
  worker, then `apply_snapshots()` on the UI thread. The animation timer (`--fps`)
  calls `GpuCard.tick(dt)`: tweening, fan phase, pulses. No I/O ever happens on
  the animation path. The first poll goes through the worker too.
- **Fast poll, slow detail.** `poll()` is what every card needs each tick.
  `Backend.detail()` (PCIe throughput, RPM, energy, ECC, VBIOS) is slower and only
  runs while the detail view is open (`app.detail_index`).
- **Backend lock.** Every backend call in the worker holds `_backend_lock`, and
  shutdown takes it before `backend.close()`. Closing NVML under a running poll
  segfaults.
- **Backends return `None` for anything unsupported.** Every NVML call goes through
  `_safe()`. The UI shows "n/a".
- **Rendering is pure.** Drawing logic lives in `ui/render.py` as functions returning
  `rich.text.Text`, and is unit-tested. Widgets only lay out.
- **Layout.** 1 GPU gives an expanded card; 2+ GPUs, or a terminal under 30 rows,
  gives a compact grid. `c` toggles.
- **The process table plans its columns every update** (`ProcessTable._plan()`):
  hidden columns, UNIT only when something has one, command width fitted so the
  table never scrolls sideways. A changed plan rebuilds; otherwise cells update in place.
- **Cards repaint only when something moves.** `Tween.step()` settles and reports
  motion; `GpuCard.tick()` skips the refresh for a settled card with stopped fans.
  Anything new that animates by time alone must be added to `GpuCard._pulsing()`.

## Rules (non-negotiable)

1. **Process data is hostile.** Anything from `/proc`, psutil or NVML must pass
   through `sanitize.clean()` before display. Never render it as markup: use
   `rich.text.Text` or `Static(..., markup=False)`. Border titles given as `str`
   are parsed as markup, so set them as `Text` (`textual.markup.escape` only
   covers complete `[tags]` and is not enough). Use `App._say()` for
   notifications, never `notify()` with interpolated data.
2. **All signals go through `killer.py`** (`prepare()` when the dialog opens, then
   `send()`). Never call `os.kill` directly. Mock mode must never touch real PIDs.
3. **No shell.** Exec via argument lists only (`os.execve`). Passthrough binaries must
   pass `_trusted_executable()`.
4. **Keep NVML off the UI thread.**
5. **No network access, telemetry or persistent writes** without an explicit decision
   recorded in `docs/security.md`. nvpulse is local only by the owner's decision:
   it shows the machine it runs on and never connects to or listens for anything
   else. Don't propose features that would, and don't describe it as usable that way. `--dump` writes to stdout only and must stay
   free of hostnames, UUIDs, PIDs, user names and command lines. The settings
   file is read, never written, and no setting may run or name a program.
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
- **Bindings older than a call raise on lookup.** `N.nvmlDeviceGetX` fails with
  AttributeError before `_safe()` runs when nvidia-ml-py predates the call (the
  12.535 floor lacks `nvmlDeviceGetFanSpeedRPM`). Use `_call("name", …)` and
  `_const("NAME")` in `nvml.py` for anything newer than the floor. The fake in
  `tests/test_nvml.py` models this with its `missing` set.
- **Palette colours are read at draw time.** `render.set_theme()` rebinds
  `R.TEXT`, `R.DIM` and friends, so write `Style(color=R.DIM)` inside the function
  that draws, never as a module-level constant, and never `from .render import DIM`.
- **Rich turns a closed pipe into exit status 1** (`Console.on_broken_pipe`).
  `once.print_once()` captures and writes in one go so `nvpulse --once | head`
  ends cleanly; keep it that way.
- **An `Input` with focus swallows letter keys,** which is what keeps `k` and `q`
  from firing while the filter is being typed. App bindings for non-printing
  keys (`escape`) still reach the app.
- **Desktop sessions run every app as a systemd user unit.** `parse_cgroup()`
  labels containers and system services only, or the UNIT column fills with noise.
- **Real hardware lies about throttling.** An idle desktop card reports "software
  power cap" continuously and drops its PCIe link to Gen 1. Neither is a fault,
  so neither raises a badge or warning (`models.CLOCK_REASONS`, `pcie_downgrade`).
- **Polls can land after teardown.** `apply_snapshots()` and `feed_detail()` use
  `query()` and bail out when their widgets are gone; `query_one()` there raises
  on exit.
- **App bindings don't fire under a modal,** which is what keeps `k` from acting
  on a hidden row while the detail view is open. `DataTable` binds `enter` itself;
  `ProcessTable` rebinds it to open the detail view.

## Style

Ruff (line length 120, config in `pyproject.toml`), type hints everywhere,
`from __future__ import annotations`, short imperative commit subjects.
