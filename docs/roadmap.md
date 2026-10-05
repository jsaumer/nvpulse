# Roadmap

Rough priorities, not promises. Open an issue if you'd like to push something up the list.

## v0.1: first release ✅
- Animated dashboard (fans, gauges, heat bar, sparklines), adaptive single/multi-GPU layout
- Process table with sort and kill
- nvidia-smi passthrough, mock backend, tests, CI

## v0.2: polish and real-hardware hardening ✅
- `nvpulse --dump`: one sanitised snapshot as JSON, for bug reports and fixtures
- Hide graphics processes with one key
- `-i` takes UUIDs and PCI bus IDs
- Per-GPU detail view (`Enter` on a process row, or click a card)
- Throttle badges and a PCIe link-downgrade warning on the card border
- Clean exit on SIGTERM / SIGHUP; first poll in the worker thread
- Polish: selected-row colours, help screen, sparkline lead-in, mock VRAM, smaller GIF
- Release workflow for PyPI (trusted publishing)

## v0.3: reach, configuration and themes
- [ ] Validate on more hardware. Covered so far: one consumer desktop card
      (RTX 4070 SUPER, zero-RPM idle fans). Still open: multi-GPU, laptop,
      workstation, datacenter, WSL. `--dump` output from any of these helps
- [ ] Decide whether to publish on PyPI. Installing from GitHub at a tag works
      today; PyPI would add `pipx install nvpulse` and `pipx upgrade`. The
      workflow exists and is manual-only
- [ ] Config file (`~/.config/nvpulse/config.toml`): default interval, fps, sort,
      colour thresholds, hidden columns
- [ ] Theme presets (default, high-contrast, monochrome / `NO_COLOR`)
- [ ] Process filters (by user, by GPU)
- [ ] Process tree view / group by container (cgroup)
- [ ] Skip card repaints when nothing visible changed (idle cards with stopped fans)

## v0.4: events and history
- [ ] XID error and throttle event log panel
- [ ] Optional CSV/JSONL recording (`--record file`) and replay (`--replay file`)
- [ ] MIG instance awareness (needs datacenter hardware or contributed dumps)

## Later / ideas
- [ ] Remote mode: poll several hosts over SSH and show them in one grid
- [ ] Prometheus / DCGM exporter as an alternative backend
- [ ] Packaging: AUR, Homebrew (Linuxbrew), standalone zipapp
