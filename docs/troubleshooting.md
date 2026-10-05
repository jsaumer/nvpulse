# Troubleshooting

### `nvpulse: NVML init failed: ...` / `NVML Shared Library Not Found`

nvpulse talks to the driver through NVML (`libnvidia-ml.so.1`), the same library
`nvidia-smi` uses.

- Check the driver works: `nvidia-smi` should print a table.
- If it does but nvpulse fails, look for the library: `ldconfig -p | grep nvidia-ml`.
- In **Docker**, run with the NVIDIA Container Toolkit (`--gpus all`) so the
  library is mounted into the container.
- To try the UI without a GPU: `nvpulse --mock 2`.

### Process names show `?`, or the process table is empty

- **Containers / PID namespaces:** NVML reports host PIDs. If nvpulse runs inside a
  container, `psutil` can't see them. Run it on the host, or with `--pid=host`.
- **Permissions:** another user's process details can be hidden (for example with
  `hidepid` on `/proc`). Try `sudo nvpulse`.
- **WSL2:** the driver often doesn't expose per-process information or memory,
  so the table may be empty or show "n/a". If `nvidia-smi` inside WSL shows the
  same, it's a driver limitation.

### Fan shows "passive" on a card that has fans

The driver didn't report a fan speed. This is common on laptops and some OEM
cards. Run `nvidia-smi -q -d FAN` to see what the driver exposes.

### Fan / bars look like dots or boxes

Your terminal font is missing **braille** (U+2800–U+28FF) or block-element glyphs.
Most Nerd Fonts, JetBrains Mono, Cascadia Code, Fira Code and DejaVu Sans Mono
include them. Over SSH, it's the *local* terminal's font that matters.

### Colours look wrong or washed out

nvpulse uses 24-bit colour. Make sure `COLORTERM=truecolor` is set. Inside
**tmux**, add:

```
set -g default-terminal "tmux-256color"
set -as terminal-features ",*:RGB"
```

### High CPU use

The animation runs at 20 fps by default. Lower it with `--fps 10`, or use
`--no-anim` (or press `a`) for a static display. Polling interval (`-n`) has
little effect on CPU.

### `nvpulse -q` (or another flag) didn't do what I expected

Flags nvpulse doesn't define are forwarded to the real `nvidia-smi`. If that
binary isn't on `PATH`, set `NVPULSE_REAL_SMI=/path/to/nvidia-smi`.
`nvpulse --help` lists the flags nvpulse handles itself.

### Can't kill a process

`k`/`K` send SIGTERM/SIGKILL as the user running nvpulse. Other users' processes
need `sudo`. Some processes (Xorg, compositors) will come back or take the
desktop down with them, so be careful.
