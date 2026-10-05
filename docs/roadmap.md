# Roadmap

Rough priorities, not promises. Open an issue if you'd like to push something up the list.

## v0.1: first release ✅
- Animated dashboard (fans, gauges, heat bar, sparklines), adaptive single/multi-GPU layout
- Process table with sort and kill
- nvidia-smi passthrough, mock backend, tests, CI

## v0.2: polish and real-hardware hardening
- [ ] Validate on a range of hardware (consumer, workstation, datacenter, laptop, WSL)
- [ ] Map `-i` UUIDs and PCI bus IDs to indices (nvidia-smi accepts both)
- [ ] Per-GPU detail view (`Enter` on a card): multi-row braille history graphs,
      every clock and throttle reason, ECC counters
- [ ] PCIe TX/RX throughput row (sampled at a lower rate, since the NVML call is slow)
- [ ] Throttle-reason badges (thermal, power cap, HW slowdown) on the card border
- [ ] Clean exit on SIGTERM / SIGHUP over SSH

## v0.3: configuration and themes
- [ ] Config file (`~/.config/nvpulse/config.toml`): default interval, fps, sort,
      colour thresholds, hidden columns
- [ ] Theme presets (default, high-contrast, monochrome / `NO_COLOR`)
- [ ] Process filters (by user, by GPU, hide graphics processes)
- [ ] Process tree view / group by container (cgroup)

## v0.4: events and history
- [ ] XID error and throttle event log panel
- [ ] Optional CSV/JSONL recording (`--record file`) and replay (`--replay file`)
- [ ] MIG instance awareness

## Later / ideas
- [ ] Remote mode: poll several hosts over SSH and show them in one grid
- [ ] Prometheus / DCGM exporter as an alternative backend
- [ ] Packaging: PyPI release, AUR, Homebrew (Linuxbrew), standalone zipapp
