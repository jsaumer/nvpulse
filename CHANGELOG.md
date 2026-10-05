# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
