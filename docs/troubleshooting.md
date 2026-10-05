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
  `hidepid` on `/proc`). Running as root shows them, but read
  [docs/security.md](security.md) first and consider `sudo nvpulse --read-only`.
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

The animation runs at 20 fps by default, and each frame repaints every card
that is changing (a card with stopped fans and steady readings is left alone).
Lower it with `--fps 10`, or use `--no-anim` (or press `a`) for a static display.
Short poll intervals cost CPU too, more so on a desktop where dozens of graphics
clients fill the process table.

Measured on an RTX 4070 SUPER desktop (one GPU, 41 GPU processes, 150x46
terminal), as a share of one core:

| Flags | CPU |
| --- | --- |
| default (20 fps, 1 s poll) | 19% |
| `--fps 10` | 12% |
| `--no-anim` | 7% |
| `--fps 60` | 44% |
| `-n 0.25` | 35% |

### Memory, fan or clock readings differ from `nvidia-smi`

- **Memory used** should agree with `nvidia-smi` to within a poll. On old drivers
  nvpulse can read a few hundred MiB higher, because
  those only report "used" with the driver's own reserved memory included.
- **Fan 0% while the card is warm** is normal on cards with a zero-RPM idle mode.
  The fan art stays still until the fans start. `nvidia-smi` prints one fan
  figure; nvpulse lists each fan.
- **`SM` clock jumps around at idle.** The driver drops the core clock between
  bursts of work, so two readings a moment apart can differ a lot.
- The process table lists every graphics client (`G`), most of them using a few
  MiB. Press `g` to hide them, or start with `--hide-graphics`. `/` narrows the
  list further, and `i` shows a row's full command line.
- **PCIe shows Gen 1 or 2 on a Gen 4 card.** The driver drops the link speed at
  idle to save power and raises it under load. `nvidia-smi` shows the same.

### A red badge on a card (THERMAL, HW SLOWDOWN, POWER BRAKE)

The driver is holding the GPU's clocks down. THERMAL means it is too hot: check
airflow, dust and the fan curve. HW SLOWDOWN and POWER BRAKE usually point at
power delivery (PSU, cables) or an external power limit. The detail view
(`Enter`) lists every active reason on its "Clock cap" row.

You won't see a badge for "idle" or "software power cap". Both are routine: the
card used for testing reports the software power cap for hours while idling at
11 W. They still appear in the detail view, as they do in `nvidia-smi -q`.

### "PCIe … ▼ card supports …" on a card

The link has fewer lanes than the card can use, or the slot only offers an older
PCIe generation. Common causes: a slot that is x16 in size but wired x8 or x4,
lanes shared with an M.2 slot, a riser cable, or a BIOS setting. It only costs
performance when a workload moves a lot of data to and from the card.

### The detail view shows `…` for some values

Those readings are fetched only while the view is open and arrive with the next
poll. If they stay `…`, polling is failing: look for a "poll failed" notice.
"n/a" means the card or driver doesn't report that value (ECC counters on
consumer cards, for example).

### The UNIT column is missing, empty, or shows an ID instead of a name

The column appears only when at least one GPU process belongs to a container
or a system service, and it steps aside on a narrow terminal. Containers show
as `docker:3f2a9c1b2d4e` (the short ID `docker ps` prints), because looking up
the friendly name would need the runtime's root-equivalent socket. Match it with:

```bash
docker ps --no-trunc | grep 3f2a9c1b2d4e
```

Ordinary desktop apps have no unit: a desktop session runs every app as its own
user unit, and labelling them all would just be noise. If nvpulse itself runs
inside a container, it can't see the host's cgroups and the column stays empty.

### `nvpulse: ... config.toml: ...` at startup

The settings file has a problem, and the message says which: an unknown key
(often a typo), a value of the wrong type or out of range, or a file that
someone else can write (`chmod go-w` it; group-writable counts). `nvpulse
--no-config` starts without it. All settings are listed in
[configuration.md](configuration.md).

`refusing …; continuing without it` is a warning, not an error: the file at the
default location belongs to someone else (typically yours, seen by `sudo
nvpulse`), so it was skipped.

### Alerts don't fire, or fire once and go quiet

Alerts are off until you set `temp` or `vram` under `[alerts]` in the settings
file. A limit is announced once when a GPU reaches it, and again only after it
has dropped below and come back; the badge on the card stays for as long as the
GPU is over the limit.

### "session" energy looks too low

It counts from when nvpulse started, adds up the power readings poll by poll,
and skips long gaps (paused, or the machine was asleep). The detail view also
shows the driver's own counter, "since driver load", when the card has one.

### Passthrough under WSL says the real nvidia-smi was not found

Windows drives mounted in WSL show every file as writable by everyone, so
`nvidia-smi.exe` under `/mnt/c` fails the check that keeps nvpulse from
executing a binary someone else could have replaced. nvpulse looks for WSL's
own Linux copy in `/usr/lib/wsl/lib` instead. If it is somewhere else, point
`NVPULSE_REAL_SMI` at it. (This path has not been tested on a real WSL install yet.)

### No colour, or colour where you don't want it

`--once` uses colour only when writing to a terminal. The dashboard follows
`--theme`; `--theme mono` or `NO_COLOR=1` removes colour, and
`--theme high-contrast` brightens the dim parts. Naming a colour theme
overrides `NO_COLOR`.

### `--once` prints `?` instead of bars over SSH

The terminal's locale can't encode the block characters (`LANG=C`, for
example). nvpulse replaces what it can't print rather than failing. Use a UTF-8
locale to get the bars: `LANG=C.UTF-8 nvpulse --once`.

### Reporting a hardware quirk

Attach the output of `nvpulse --dump` to the issue. It holds the driver and
library versions and every reading nvpulse takes, and leaves out the hostname,
GPU UUID, PIDs, user names and command lines.

### `nvpulse -q` (or another flag) didn't do what I expected

Flags nvpulse doesn't define are forwarded to the real `nvidia-smi`. If that
binary isn't on `PATH`, set `NVPULSE_REAL_SMI=/path/to/nvidia-smi`.
`nvpulse --help` lists the flags nvpulse handles itself.

### Can't kill a process

`k`/`K` send SIGTERM/SIGKILL as the user running nvpulse, so other users'
processes need root. nvpulse also refuses on purpose when:

- the PID is 0 or 1, or belongs to nvpulse or its parent shell
- the PID was reused by a different process since the last poll
- the process is no longer using that GPU
- you started nvpulse with `--read-only`

Some processes (Xorg, compositors) will come back or take the desktop down with
them, so be careful.

### Parts of a command line show as `•••` or `\x1b`

That's deliberate. Values that look like secrets (`--password=…`, `HF_TOKEN=…`,
`user:pass@` in URLs) are masked; use `--no-redact` to see them. Control and
invisible characters are shown as escapes so they can't affect your terminal or
disguise a process. See [security.md](security.md).

### `passthrough loop detected` / `ignoring NVPULSE_REAL_SMI`

Your `nvidia-smi` on `PATH` is a wrapper that runs nvpulse, or the override points
somewhere unsafe. Set `NVPULSE_REAL_SMI` to the driver's binary, usually
`/usr/bin/nvidia-smi`: an absolute path that isn't writable by other users (and
is owned by root if you run nvpulse as root).
