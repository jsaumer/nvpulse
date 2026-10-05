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

## v0.3: everyday use on real boxes
- [ ] CI job on the oldest supported versions (Textual 4.0, nvidia-ml-py 12.535):
      a bug that only showed there got past CI in v0.2. Add Python 3.14 to the
      matrix; drop 3.10 once it is out of support
- [ ] Validate on more hardware we can reach. Covered so far: one consumer
      desktop card (RTX 4070 SUPER, zero-RPM idle fans). Still open: multi-GPU,
      workstation, datacenter, and two with known risks:
      - WSL: passthrough will reject `nvidia-smi.exe` on a Windows mount (those
        files show as world-writable). Decide on a narrow, documented exception
      - laptops with hybrid graphics: polling may keep the GPU from sleeping
- [ ] Container column: which Docker / Podman container or systemd unit owns a
      process, read from `/proc/<pid>/cgroup` (no access to the Docker socket)
- [ ] `nvpulse --once`: print one coloured snapshot and exit, for SSH one-liners
      and login banners
- [ ] Shorter command lines: fit the column (no horizontal scrollbar), full line
      on demand
- [ ] `/` to filter processes by name; filters by user and by GPU
- [ ] Detail view: a time scale and min / avg / max on the history graphs
- [ ] Encoder sessions: count and frame rate of active NVENC sessions
- [ ] Config file (`~/.config/nvpulse/config.toml`): default interval, fps, sort,
      colour thresholds, hidden columns
- [ ] Threshold alerts: highlight or ring the bell when temperature or VRAM
      crosses a configured limit
- [ ] Energy used since start, with an optional cost per kWh from the config
- [ ] Theme presets (default, high-contrast, monochrome / `NO_COLOR`)
- [ ] Process tree view / group by container (cgroup)
- [ ] Skip card repaints when nothing visible changed (idle cards with stopped fans)

## v0.4: events and history
- [ ] XID error and throttle event log panel
- [ ] Optional CSV/JSONL recording (`--record file`) and replay (`--replay file`)
- [ ] MIG instance awareness (needs datacenter hardware or contributed dumps)

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
