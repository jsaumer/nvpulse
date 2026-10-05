# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-05

### Added
- **GPU detail view.** Press `Enter` (for the selected process's GPU) or click a
  card: tall history graphs for utilisation, memory, power and temperature, plus
  every clock, the active clock-limit reasons, per-fan speed, RPM and target,
  thermal thresholds, energy used, PCIe link and TX/RX throughput, ECC counters
  and VBIOS version. `←` / `→` switch GPU. The extra readings are only polled
  while the view is open.
- **Throttle badges** on the card border for thermal slowdown, hardware slowdown
  and power brake. Idle and the software power cap are not badged: a healthy
  card reports both routinely.
- **PCIe link warning** on the card border when the card runs on fewer lanes
  than it supports, or in a slot limited to an older PCIe generation.
- **`g` hides graphics-only processes** (`--hide-graphics` to start that way), so
  a desktop session's dozens of small clients don't bury the compute jobs.
- **`-i` accepts GPU UUIDs and PCI bus IDs** as well as indices, like `nvidia-smi`.
- **`nvpulse --dump`** prints one snapshot as JSON for bug reports. It contains
  no hostname, GPU UUID, PIDs, user names or command lines.
- The running version is shown in the header, next to the name, and on the help screen.
- A release workflow that publishes to PyPI through trusted publishing when a
  GitHub release is published.

### Changed
- SIGTERM and SIGHUP (a dropped SSH session) now exit cleanly: the terminal is
  restored and the driver connection closed. Previously the process was killed
  mid-frame, leaving the terminal in the alternate screen with mouse reporting on.
- The first poll runs in the worker thread like every later one, so a slow
  driver can't delay the first frame.
- The selected process row keeps each cell's own colours; the VRAM gauge on it
  is no longer washed out.
- Sparklines show a dotted lead-in until the history fills.
- The help screen's columns line up, and it lists the new keys.
- Mock GPUs no longer start with VRAM almost full, and have UUID-shaped IDs.
- The demo GIF is a fifth of its previous size.

### Fixed
- A crash on exit when the driver was shut down while a poll was still inside it.
- An error on exit when a poll finished after the screen was torn down.

### Security
- GPU names are drawn as plain text in card titles instead of escaped markup,
  which a name cut off mid-tag could break once badges follow it.

## [0.1.1] - 2026-10-04

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

[Unreleased]: https://github.com/jsaumer/nvpulse/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/jsaumer/nvpulse/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/jsaumer/nvpulse/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jsaumer/nvpulse/releases/tag/v0.1.0
