# Configuration

nvpulse works without any configuration. A settings file only saves you from
typing the same flags every time, and holds the few options that have no flag.

## Where it lives

`~/.config/nvpulse/config.toml`, or `$XDG_CONFIG_HOME/nvpulse/config.toml`.
Use `--config FILE` or `NVPULSE_CONFIG=FILE` for another location, and
`--no-config` to ignore the file for one run.

The file is only read, never written. It must be a regular file owned by you
(or root) that nobody else can write, group included; anything else is refused,
because the file can turn off command-line redaction and the read-only guard.
`chmod go-w ~/.config/nvpulse/config.toml` fixes it. A refused file that you
named stops nvpulse; a refused file at the default location is skipped with a
warning, so `sudo nvpulse` still starts when it finds your own file there.

## Precedence

Command-line flag, then the settings file, then the built-in default. A mistake
in the file (unknown key, wrong type, value out of range) stops the dashboard
with a message naming the problem; `--no-config` gets you past it.

## Every setting

```toml
interval = 1.0            # seconds between polls (0.1 to 3600)       flag: -n
fps = 20                  # animation frame rate (1 to 60)            flag: --fps
animate = true            # false = static display                    flags: --anim / --no-anim
layout = "auto"           # "auto", "compact" or "expanded"           flags: --compact / --expanded
sort = "vram"             # "vram", "sm", "pid", "gpu" or "unit"      key: s
theme = "default"         # "default", "high-contrast" or "mono"      flag: --theme
hide_graphics = false     # start with graphics-only processes hidden flags: --hide-graphics / --no-hide-graphics, key: g
read_only = false         # disable k / K                             flags: --read-only / --no-read-only
redact = true             # mask secrets in command lines             flags: --redact / --no-redact
hidden_columns = []       # any of: "gpu", "pid", "user", "type", "sm", "vram", "unit"

[alerts]
temp = 85                 # °C: badge the card and notify when reached
vram = 95                 # percent of VRAM in use
bell = true               # also ring the terminal bell

[energy]
cost_per_kwh = 0.30       # shows the cost of the energy used this session
currency = "$"            # up to 4 characters, printed before the amount
```

Leave out anything you don't want to change. Alerts are off unless you set a
limit. Every on/off setting has a flag for each direction, so one run can undo
what the file sets: with `read_only = true` in the file, `nvpulse --no-read-only`
re-enables `k` for that run. `hidden_columns`, `[alerts]` and `[energy]` have no
flags.

## Themes

- `default`: the dark theme in the screenshots.
- `high-contrast`: brighter secondary text, borders and gauge tracks, for
  projectors and washed-out panels.
- `mono`: no colour. Setting `NO_COLOR` in the environment selects it too.

## What `--once` and `--dump` use

`--once` honours `theme`, `redact`, `hide_graphics` and `[alerts]`. `--dump`
never reads the file, so a broken one can't get in the way of a bug report.

An explicit colour theme (`--theme default` or `high-contrast`, or `theme = …`
in the file) wins over `NO_COLOR`.
