# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Sanitise all untrusted text (process names, users, command lines, NVML strings):
  control, bidi and invisible characters are shown as visible escapes, and lengths
  are capped. Previously, ESC sequences in another user's argv reached the terminal.
- Render untrusted text without markup. Previously, a process named `[/]` crashed
  the app when its kill dialog opened, and crafted names could forge dialog text.
- Kill hardening: pidfd pinning plus start-time check against PID reuse; refuse
  PID ≤ 1, self and parent; require the process to still be on the GPU; show the
  owner; root warning.
- Passthrough hardening: skip empty and relative `PATH` entries; refuse
  world-writable binaries and directories (and non-root-owned ones when root);
  validate `NVPULSE_REAL_SMI`; stop recursion loops; `allow_abbrev=False`.
- Mask likely secrets in command lines by default (`--no-redact` to disable).
- Clamp `--interval`, `--fps`, `--mock` and `-i`; reject NaN and infinity.
- Disable Textual's command palette.
- CI: least-privilege token, SHA-pinned actions, `persist-credentials: false`,
  `pip-audit` job, Dependabot.

### Fixed
- VRAM "used" now matches `nvidia-smi`. It included the memory the driver reserves
  for itself, which read a few hundred MiB high on real hardware.
- The process table no longer scrolls back to the selected row on every poll when
  you have scrolled away from it.

### Added
- `--read-only` flag, and **ROOT** / **READ-ONLY** header badges.
- `SECURITY.md` and `docs/security.md`.

### Changed
- Minimum Textual version raised to 4.0. Older versions fail at runtime.
- The process table updates changed cells in place instead of being rebuilt on
  every poll, which lowers CPU use at short poll intervals.

## [0.1.0] - 2026-10-04

### Added
- Textual dashboard with an adaptive layout: one large card for a single GPU, a
  responsive grid of compact cards for several.
- Braille fan animation driven by the real fan %, with motion blur; heatsink-fin
  art with heat shimmer for passive cards.
- Gradient gauges for utilisation, VRAM and power, with 1/8-cell precision and
  eased transitions.
- Temperature heat bar with the NVML slowdown-threshold marker and a hot-GPU pulse.
- Sparklines for utilisation, memory, power and temperature on wide cards.
- Process table with sort (VRAM / SM % / PID / GPU) and confirmed SIGTERM / SIGKILL.
- Header with driver and CUDA versions, host, and multi-GPU power and memory totals.
- NVML backend that treats unsupported fields as "n/a" instead of failing.
- Mock backend (`--mock N`) for demos, screenshots and tests.
- Passthrough to the real `nvidia-smi` for unknown flags, `--classic`, and non-TTY output.
- `nvpulse` command, with `nvidia-smi+` as an alias.

[Unreleased]: https://github.com/OWNER/nvpulse/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/nvpulse/releases/tag/v0.1.0
