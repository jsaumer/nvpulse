# nvpulse

**An animated, btop-style terminal dashboard for NVIDIA GPUs that launches like `nvidia-smi`.**

![nvpulse demo](docs/images/demo.gif)

`nvpulse` gives you a live view of every GPU in the box: fans that spin at the
card's real fan speed, gradient gauges that ease between samples, a heat bar that
pulses as you approach thermal slowdown, and a sortable process table you can act on.

It also works as a drop-in front end for `nvidia-smi`. Pass it a flag it doesn't
own (`-q`, `-L`, `--query-gpu=…`) or pipe its output, and it hands off to the real
`nvidia-smi` unchanged, so scripts and muscle memory keep working.

> **Status:** alpha (v0.2). Validated on one consumer desktop card so far. Reports
> from laptops, multi-GPU boxes, datacenter cards and WSL are very welcome:
> `nvpulse --dump` prints a snapshot that is safe to paste into an issue.

## Features

- **Animated fans**, drawn procedurally on a braille canvas. Rotation speed tracks
  the reported fan %, with motion blur at high RPM. Passive datacenter cards (A100,
  H100, L40S …) show heatsink fins with rising heat shimmer instead.
- **Gradient gauges** for GPU utilisation, VRAM and power, with 1/8-cell precision
  and eased animation between polls.
- **Heat bar** coloured by absolute temperature, with the driver's slowdown
  threshold marked and a pulsing glow within 10 °C of it.
- **Sparklines** of recent utilisation, memory, power and temperature on wide cards.
- **Process table**: GPU, PID, user, type (C/G), SM %, VRAM bar and command line.
  Sortable, with confirmed SIGTERM / SIGKILL, and one key to hide the dozens of
  small graphics clients a desktop session creates.
- **GPU detail view** (`Enter`): tall history graphs and every reading the card
  offers, from per-fan RPM and thermal thresholds to PCIe throughput and ECC counters.
- **Warnings where they matter**: a badge on the card when it is thermally or
  hardware throttled, and a note when it sits in a slot that limits its PCIe link.
- **Adaptive layout**: a large card for a single GPU, a responsive grid for many.
- **nvidia-smi passthrough** for anything non-interactive.
- **Mock mode** (`--mock N`) to try it with no GPU at all.
- **Safe with hostile input**: other users' process names can't inject terminal
  escape sequences, secrets in command lines are masked, and kills are pinned
  to the exact process with a pidfd.

| Single GPU | Multi-GPU |
|---|---|
| ![single GPU](docs/images/single-gpu.svg) | ![four GPUs](docs/images/multi-gpu.svg) |

| GPU detail view |
|---|
| ![GPU detail view](docs/images/detail.svg) |

## Install

Requirements: Linux, Python 3.10+, and an NVIDIA driver (provides NVML /
`libnvidia-ml.so`). You also need a terminal with 24-bit colour and a font that
has braille glyphs; most modern terminals qualify.

```bash
# from a clone of this repo
pipx install .

# or, for development
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

This installs two commands: `nvpulse`, and `nvidia-smi+` as an alias.

## Usage

```bash
nvpulse                    # dashboard
nvpulse -i 0,2             # only GPUs 0 and 2 (UUIDs and PCI bus IDs work too)
nvpulse -n 0.5             # poll every 0.5 s (default 1 s)
nvpulse --compact          # force compact cards (--expanded for the large layout)
nvpulse --no-anim          # static, low-CPU mode
nvpulse --fps 30           # smoother animation (default 20)
nvpulse --mock 4           # four simulated GPUs, no hardware needed
nvpulse --read-only        # disable k/K (good for shared screens or sudo)
nvpulse --no-redact        # show command lines verbatim (secrets are masked by default)
nvpulse --hide-graphics    # start with graphics-only processes hidden
nvpulse --dump             # one snapshot as JSON, for bug reports (no names or IDs)
```

### Passthrough to nvidia-smi

```bash
nvpulse -q                                              # forwarded
nvpulse --query-gpu=name,temperature.gpu --format=csv   # forwarded
nvpulse | cat                                           # stdout not a TTY: forwarded
nvpulse --classic                                       # plain nvidia-smi table
```

The real binary is found on `PATH`, skipping nvpulse itself. To point at a
specific binary, set `NVPULSE_REAL_SMI=/usr/bin/nvidia-smi`.

If you want nvpulse to *be* `nvidia-smi` in your interactive shell:

```bash
alias nvidia-smi='nvpulse'
```

### Keys

| Key | Action |
|---|---|
| `q` | Quit |
| `p` / `space` | Pause or resume polling |
| `+` / `-` | Poll faster / slower |
| `c` | Toggle compact / expanded cards |
| `a` | Toggle animation |
| `s` | Cycle process sort: VRAM → SM % → PID → GPU |
| `g` | Hide or show graphics-only processes |
| `Enter` | GPU detail view for the selected process's GPU (or click a card); `←` `→` switch GPU, `Esc` closes |
| `k` / `K` | SIGTERM / SIGKILL the selected process (asks first) |
| `↑` `↓` | Move in the process table |
| `?` | Help |

You can only signal processes you're allowed to signal. nvpulse doesn't need root,
and running it as root is discouraged; if you do, the header shows a **ROOT**
badge and `--read-only` is a good idea. See [Security](docs/security.md).

## Documentation

- [Architecture](docs/architecture.md): how the pieces fit together
- [Roadmap](docs/roadmap.md): what's planned next
- [Troubleshooting](docs/troubleshooting.md): NVML errors, containers, WSL, fonts
- [Security model](docs/security.md): threat model and hardening ([report a vulnerability](SECURITY.md))
- [Contributing](CONTRIBUTING.md): dev setup, tests and conventions
- [Changelog](CHANGELOG.md)

## Related projects

nvpulse sits alongside some excellent tools. If you want something battle-tested
today, try one of these:

- [nvitop](https://github.com/XuehaiPan/nvitop): full-featured interactive NVIDIA process viewer
- [nvtop](https://github.com/Syllo/nvtop): htop-style monitor for NVIDIA, AMD and Intel GPUs
- [gpustat](https://github.com/wookayin/gpustat): compact one-shot GPU status
- [btop](https://github.com/aristocratos/btop): system monitor with GPU panels

nvpulse focuses on animated visuals and on acting as a drop-in `nvidia-smi` front end.

## License

[MIT](LICENSE). NVIDIA, CUDA and nvidia-smi are trademarks of NVIDIA Corporation.
This project is independent and is not affiliated with or endorsed by NVIDIA.
