# Roadmap

Rough priorities, not promises. Open an issue if you'd like to push something up the list.

## v0.1: first release ✅
- Animated dashboard (fans, gauges, heat bar, sparklines), adaptive single/multi-GPU layout
- Process table with sort and kill
- nvidia-smi passthrough, mock backend, tests, CI

## v0.2: polish and real-hardware hardening
- [ ] Validate on a range of hardware. Covered so far: one consumer desktop card
      (RTX 4070 SUPER, zero-RPM idle fans). Still open: multi-GPU, laptop,
      workstation, datacenter, WSL
- [ ] `nvpulse --dump`: print one sanitised snapshot as JSON to stdout, for bug
      reports and as recorded fixtures for hardware we can't test on
- [ ] Hide or collapse graphics processes with one key (a desktop session lists
      dozens of clients using a few MiB each)
- [ ] Map `-i` UUIDs and PCI bus IDs to indices (nvidia-smi accepts both)
- [ ] Per-GPU detail view (`Enter` on a card): multi-row braille history graphs,
      every clock and throttle reason, fan RPM, max operating and target
      temperatures, energy counter, VBIOS version, PCIe TX/RX throughput (the NVML
      call takes about 20 ms per direction, so it stays out of the regular poll),
      ECC counters where the card has them
- [ ] Throttle-reason badges (thermal, power cap, HW slowdown) on the card border.
      The "idle" reason is not a throttle and must not raise a badge
- [ ] PCIe link-downgrade warning when the current generation or width is below
      what the card supports
- [ ] Clean exit on SIGTERM / SIGHUP over SSH
- [ ] Do the first poll in the worker thread, like every later one
- [ ] Polish: VRAM gauge colour on the selected row, help-screen key alignment,
      sparklines before the history fills, mock 4090 starting near full VRAM,
      smaller demo GIF
- [ ] PyPI release through trusted publishing, so `pipx install nvpulse` works

## v0.3: configuration and themes
- [ ] Config file (`~/.config/nvpulse/config.toml`): default interval, fps, sort,
      colour thresholds, hidden columns
- [ ] Theme presets (default, high-contrast, monochrome / `NO_COLOR`)
- [ ] Process filters (by user, by GPU)
- [ ] Process tree view / group by container (cgroup)

## v0.4: events and history
- [ ] XID error and throttle event log panel
- [ ] Optional CSV/JSONL recording (`--record file`) and replay (`--replay file`)
- [ ] MIG instance awareness (needs datacenter hardware or contributed dumps)

## Later / ideas
- [ ] Remote mode: poll several hosts over SSH and show them in one grid
- [ ] Prometheus / DCGM exporter as an alternative backend
- [ ] Packaging: AUR, Homebrew (Linuxbrew), standalone zipapp
