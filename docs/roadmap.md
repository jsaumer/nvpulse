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

## v0.3: everyday use on real boxes ✅
- Settings file (`~/.config/nvpulse/config.toml`), themes and `NO_COLOR`
- `nvpulse --once`
- UNIT column: container or systemd service per process; sort by it
- `/` filter, `i` process details, command column fitted to the terminal
- Alerts on temperature and VRAM limits; energy and cost this session
- Encoder sessions; time axis and ranges in the detail view
- Idle cards skip repaints
- CI on the oldest supported versions and on Python 3.14
- WSL: passthrough looks in `/usr/lib/wsl/lib` (untested on real WSL)

## v0.4: more hardware, events and history
- [ ] Validate on more hardware we can reach. Covered so far: one consumer
      desktop card (RTX 4070 SUPER, zero-RPM idle fans). Still open: multi-GPU,
      workstation, datacenter, a real container host (the UNIT column is only
      tested against documented cgroup layouts), and two with known risks:
      - WSL: confirm passthrough finds `/usr/lib/wsl/lib/nvidia-smi`, and that
        the dashboard copes with what the WSL driver doesn't report
      - laptops with hybrid graphics: polling may keep the GPU from sleeping
- [ ] Process tree view (parent / child rows)
- [ ] XID error and throttle event log panel
- [ ] Optional CSV/JSONL recording (`--record file`) and replay (`--replay file`)
- [ ] MIG instance awareness (needs datacenter hardware or contributed dumps)
- [ ] Alerts on more readings (power, utilisation, fan failure)
- [ ] Drop Python 3.10 once it is out of support (lets `tomli` go)

## Later / ideas
- [ ] Remote mode: poll several hosts over SSH and show them in one grid
- [ ] Prometheus / DCGM exporter as an alternative backend

## If the project goes public
The repository is private for now, and people with access install from GitHub
at a tag. These only matter if that changes:
- Turn on GitHub's private vulnerability reporting (`SECURITY.md` points to it)
  and branch protection on `main`
- Decide on PyPI. The release workflow exists and only runs by hand
- Packaging: AUR, Homebrew (Linuxbrew), standalone zipapp
- An issue template that asks for `nvpulse --dump` output
