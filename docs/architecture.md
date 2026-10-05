# Architecture

nvpulse is a small Python app built from three layers: a **backend** that
produces snapshots, a set of **pure renderers** that turn numbers into styled
text, and a **Textual app** that schedules polling and animation and lays
everything out.

```
             ┌──────────────┐   argv / TTY check   ┌─────────────────────┐
  user ────▶ │   cli.py     │ ───────────────────▶ │ real nvidia-smi     │  (passthrough: os.execv)
             └──────┬───────┘                      └─────────────────────┘
                    │ dashboard mode
                    ▼
      ┌─────────────────────────┐        ┌────────────────────────────┐
      │ backend (Backend iface) │        │ procinfo.enrich()          │
      │  • NvmlBackend  (NVML)  │──snap─▶│  pid → user/name/cmdline   │
      │  • MockBackend  (sim)   │        └─────────────┬──────────────┘
      └─────────────────────────┘                      │ list[GpuSnapshot]
                    ▲ poll() in a thread worker        ▼
      ┌─────────────┴────────────────────────────────────────────────┐
      │ ui/app.py  NvPulse (Textual App)                             │
      │   poll clock  (interval, default 1 s)  → apply_snapshots()   │
      │   anim clock  (fps, default 20)        → card.tick(dt)       │
      │   relayout() on resize / GPU count                           │
      │                                                              │
      │   HeaderBar   GpuCard × N (grid)   ProcessTable   Footer     │
      └──────────────────────────┬───────────────────────────────────┘
                                 │ render()
                                 ▼
                      ui/render.py (pure functions → rich.Text)
             gauge · heat_bar · sparkline · fan_art · heatsink_art · Tween
```

## CLI routing (`cli.py`)

`decide(argv, isatty)` returns `"dashboard"` or `"passthrough"`:

| Condition | Result |
|---|---|
| `--dump` | print one JSON snapshot and exit (TTY or not); an error if mixed with nvidia-smi flags |
| Any argument nvpulse doesn't define (`-q`, `-L`, `--query-gpu=…`, `-l 5` …) | passthrough with the original argv |
| `--classic` | passthrough (flag stripped) |
| stdout is not a TTY and no `--mock` | passthrough |
| otherwise | dashboard |

The real binary is located by walking `PATH` for `nvidia-smi` and skipping any
entry that resolves to the running script. `NVPULSE_REAL_SMI` overrides this. The
dashboard's own `-i` overlaps with nvidia-smi's on purpose: `nvpulse -i 0` filters
the dashboard, while `nvpulse -q -i 0` is forwarded intact. Like nvidia-smi's, it
takes indices, `GPU-…` UUIDs and PCI bus IDs; the last two are resolved once at
startup through `Backend.identify()`.

`--dump` (`dump.py`) polls once, adds `Backend.detail()` for each GPU and prints
JSON. What it leaves out, and why, is in [security.md](security.md).

## Backends (`backend/`)

`Backend` has six methods: `system_info()`, `device_count()`,
`poll(indices) -> list[GpuSnapshot]`, `detail(index) -> GpuDetail | None`,
`identify()` and `close()`.

`poll()` returns what every card needs on every tick and stays fast (about 5 ms
for one GPU). `detail()` returns the slower or rarely needed readings (per-fan
RPM, energy counter, PCIe throughput, ECC counters, VBIOS) and is only called
while the detail view is open: PCIe throughput alone takes about 20 ms per
direction, because the driver samples the link before answering.

**`NvmlBackend`** wraps every NVML call in `_safe()`, so an unsupported query
(no fan on an A100, no power reading on some laptops, no per-process memory under
WSL) becomes `None` rather than an exception. Static facts (name, UUID, bus ID,
thermal thresholds, max clocks, fan count, maximum PCIe link) are cached per device
on first poll.
Per-process SM/memory utilisation comes from `nvmlDeviceGetProcessUtilization`
with a two-second look-back.

**`MockBackend`** simulates several GPU profiles (consumer cards with fans and
passive datacenter cards). Workload follows slow sine waves with bursts,
temperature lags utilisation, fans chase temperature, and processes spawn and
exit over time. It takes a `seed` (deterministic tests) and a `clock` (inject
time).

`procinfo.enrich()` fills in user, name, command line and start time through
`psutil`, with results cached per PID and keyed on create-time so recycled PIDs
aren't mislabelled. Every string is passed through `sanitize.clean()` (and
`redact()` unless `--no-redact`) before it leaves this function. Kills go through
`killer.py`. Both are described in [security.md](security.md).

### Clock reasons and the PCIe link

NVML reports one bitmask of "clocks event reasons" (older drivers call them
throttle reasons). `models.CLOCK_REASONS` decodes it. Only thermal slowdown,
hardware slowdown and power brake become badges on the card; idle, the software
power cap and the clock-setting bits are routine and appear only in the detail
view. That split comes from real hardware: an idle desktop card reports the
software power cap continuously.

`GpuSnapshot.pcie_downgrade` compares static facts only: current width against
maximum width, and the slot's best generation against the card's. The *current*
generation is ignored, because drivers drop it at idle to save power.

## Two clocks

| Clock | Rate | Work |
|---|---|---|
| **Poll** | `--interval` (0.25–10 s, `+`/`-` to change) | Thread worker calls `backend.poll()` (plus `system_info()` the first time and `detail()` while the detail view is open) and `enrich()`, then `call_from_thread(apply_snapshots)`. A `_polling` flag prevents overlapping polls if NVML is slow. |
| **Animation** | `--fps` (default 20; 2 with `--no-anim`) | `card.tick(dt)` advances `Tween` easing, fan phase and pulse time, then refreshes. No I/O. |

Keeping these separate means a slow or hung NVML call can't stall the animation,
and animation smoothness doesn't depend on how often you poll. Nothing touches
the backend on the UI thread, including the very first poll: the app starts
empty and fills in when the worker returns.

### Shutdown

Every backend call in the worker happens under `_backend_lock`, and `on_unmount`
takes the same lock (for up to 2 s) before `backend.close()`. Shutting NVML down
while another thread is still inside the driver crashes the process. A poll that
finishes after the screen is gone is dropped by `apply_snapshots()`.

SIGTERM and SIGHUP are routed to `App.exit()` through the event loop, so the
terminal is restored and the backend closed. The exit code is 128 + the signal,
except after a hang-up whose terminal is already gone, where Python reports the
dead stdout instead.

### Tweening

`Tween` holds a target and a displayed value for each metric. Every frame:

```
value += (target - value) * (1 - exp(-rate * dt))
```

This is frame-rate-independent exponential easing. A `None` target snaps to
`None` right away, so "n/a" never animates.

## Rendering (`ui/render.py`)

Every function here is pure and returns `rich.text.Text`, which makes them easy to
unit-test and reuse.

- **Gradients:** multi-stop hex gradients, quantised to 1/64 and LRU-cached, so
  Rich's style cache stays small.
- **`gauge`:** per-cell gradient colouring plus a partial eighth-block (`▏▎▍▌▋▊▉`)
  head for sub-cell precision. `solid=True` draws filled cells as foreground `█`,
  because `DataTable` repaints cell backgrounds.
- **`heat_bar`:** cells are coloured by *absolute* temperature position, not by fill
  fraction, so a hot GPU shows red at the head. Includes a slowdown marker and a
  `glow` parameter for the pulse.
- **`fan_art`:** a braille canvas (2×4 dots per cell, which gives roughly square
  dots). Polar coordinates for each dot are precomputed per canvas size. Each frame
  tests `(θ - phase + curve·r) mod sector < blade_width` to draw curved blades.
  At speed, extra sub-phase samples smear the blades. Angular speed is capped at
  7 rad/s so the per-frame step stays well under half a blade sector, which avoids
  wagon-wheel aliasing.
- **`heatsink_art`:** vertical fins with a deterministic sparkle field that drifts
  upward; its density scales with temperature.
- **`history_graph`:** a multi-row braille area graph for the detail view, two
  samples per cell across and four levels per row, coloured by row.

A card frame (fan, four bars, sparklines) costs about 1.3 ms in CPython, so eight
GPUs at 20 fps uses about 20 % of one core at worst. `--no-anim` cuts that to nearly
nothing.

## Layout (`ui/app.py`)

- **One GPU:** an expanded card (14×7-cell fan, four metric rows, three detail rows).
- **Two or more GPUs, or a terminal shorter than 30 rows:** compact cards (8×4 fan,
  four metric rows, one detail row) in a CSS grid. Columns = `width // 62` (compact)
  or `width // 96` (expanded).
- `c` overrides the automatic choice. The GPU area is capped at 70 % of the height
  and scrolls; the process table takes the rest.
- Card border colour blends from grey toward the utilisation gradient, so the busiest
  GPU stands out in a grid.

## Detail view (`ui/detail.py`)

`GpuDetailScreen` is a modal holding one `DetailView`. It owns no data: the app
pushes the current snapshot, the latest `GpuDetail` and the card's history
deques into it after every poll (`feed_detail()`), and sets `detail_index` so the
worker knows which GPU to fetch details for. Closing the view clears
`detail_index`, and the extra NVML calls stop. Because it is modal, the main
screen's keys (`k`, `s`, …) don't reach the process table hidden behind it.
