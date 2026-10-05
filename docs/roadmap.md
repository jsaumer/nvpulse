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

## Now: run 0.3 and collect feedback
Three releases landed in quick succession, and most of the newer screens have
only been checked through headless renders and simulated data. Before more
features: use 0.3 day to day, note what feels wrong, and try it on whatever other
machines are within reach. Fixes from that go out as 0.3.x.

## v0.4: prove it, then record it
In this order:
- [ ] **Hardware check.** One command that prints a pass / fail report on any
      machine, so validating a new box takes minutes. It should: compare every
      reading with `nvidia-smi` (versions, memory, power, temperature, clocks,
      fans, thresholds, process list); start a throwaway GPU process and
      SIGTERM / SIGKILL it through the dashboard's own kill path; open and
      close the detail view repeatedly under fast polling; send SIGTERM and
      SIGHUP and confirm the terminal is restored; exercise passthrough,
      including a wrapper `nvidia-smi` on `PATH`; and measure CPU at the default
      settings, `--no-anim` and a short poll interval. Rough scripts for most of
      this are in `scripts/hwcheck-drafts/`
- [ ] Run that check on more hardware. Covered so far: one consumer desktop card
      (RTX 4070 SUPER, zero-RPM idle fans). Still open: multi-GPU, workstation,
      datacenter, a real container host (the UNIT column is only tested against
      documented cgroup layouts), and two with known risks:
      - WSL: confirm passthrough finds `/usr/lib/wsl/lib/nvidia-smi`, and that
        the dashboard copes with what the WSL driver doesn't report
      - laptops with hybrid graphics: polling may keep the GPU from sleeping.
        Check the device's runtime power state before touching NVML, and show
        "suspended" instead of waking it
- [ ] **Recording and replay** (`--record file`, `--replay file`). A recording
      made on another machine replays here, which makes it a way to reproduce
      bugs and a source of realistic test data. Recordings follow the `--dump`
      rules: no hostnames, UUIDs, PIDs, user names or command lines
- [ ] **Event log panel**: XID errors, throttling and alerts with timestamps, so
      what happened while nobody was watching is still there
- [ ] Totals per user and per unit: who, or which container, holds the VRAM
- [ ] `nvpulse --once --json`: machine-readable output with process names, for
      scripts and cron (`--dump` leaves names out on purpose)
- [ ] Alerts on more readings: a fan that is stopped while the card is hot,
      power, utilisation
- [ ] Friendly container names, opt-in. Needs a decision first: names come from
      running `docker ps` or from root-only files, and nvpulse does neither today
- [ ] Drop Python 3.10 once it is out of support (lets `tomli` go)
- [ ] A release script that updates the version, the changelog and the README's
      install line together

## Later / ideas
- [ ] MIG instance awareness (needs datacenter hardware or a recording)

## Not planned
- **Anything that uses the network.** nvpulse is local only: it shows the
  machine it runs on, and never connects to or listens for anything else.
- **Process tree view.** Parent / child rows rarely mean much for GPU processes,
  and totals per user and per unit answer the useful part.

## If the project goes public
The repository is private for now, and people with access install from GitHub
at a tag. These only matter if that changes:
- Turn on GitHub's private vulnerability reporting (`SECURITY.md` points to it)
  and branch protection on `main`
- Decide on PyPI. The release workflow exists and only runs by hand
- Packaging: AUR, Homebrew (Linuxbrew), standalone zipapp
- An issue template that asks for `nvpulse --dump` output
- Rewrite the reporting section of `SECURITY.md` for public use
