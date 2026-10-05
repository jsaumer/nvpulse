# Hardware check drafts

Rough scripts used to validate nvpulse on a real GPU while v0.1.1 to v0.3.0 were
built. They are the starting point for the single "hardware check" command at
the top of v0.4 in [the roadmap](../../docs/roadmap.md), not finished tools:
each prints raw results and leaves the judging to you.

Run them from the repository root with the dev virtualenv, on a machine with an
NVIDIA driver:

```bash
.venv/bin/python scripts/hwcheck-drafts/compare_smi.py
```

| Script | What it checks | Needs |
|---|---|---|
| `compare_smi.py` | Every reading nvpulse takes, side by side with `nvidia-smi` | `nvidia-smi` |
| `kill_path.py` | `k` and `K` end a throwaway GPU process through the dashboard's own kill path, and cancelling leaves it alive | `ffmpeg` with NVENC |
| `detail_stress.py` | Opening the detail view and quitting mid-poll, 25 times, doesn't crash the driver connection | |
| `signals.py` | SIGTERM, SIGHUP and a vanished terminal all end nvpulse promptly, with the terminal restored | |
| `cpu_usage.py` | CPU share and terminal output rate at the default settings, `--no-anim`, a fast poll, `--hide-graphics` | |
| `profile_poll.py` | Where the time goes in one poll and one table update | |
| `render_png.py` | Renders the headless app to a PNG, for looking at a screen without a terminal | `playwright`, Chrome |

What to expect, from the RTX 4070 SUPER these were written on:

- `compare_smi.py`: memory within a few MiB, everything else equal. Clocks, P-state
  and PCIe generation move between the two readings on an idle card; that is normal.
- `kill_path.py`: `pidfd pinned: True`, ffmpeg exit 255 for SIGTERM and -9 for
  SIGKILL, the row gone afterwards, and "still alive" after cancelling.
- `signals.py`: exit codes 143 and 129 with the alternate screen restored; a
  closed terminal exits within a second (code 120, nothing left to restore).
- `cpu_usage.py`: about 19 % of one core by default, 7 % with `--no-anim`.

`kill_path.py` only ever signals ffmpeg processes it started itself.
