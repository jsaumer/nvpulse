"""Command-line entry point.

``nvpulse`` (also installed as ``nvidia-smi+``) with no arguments opens the dashboard.
Anything the dashboard doesn't understand is handed to the real ``nvidia-smi``
unchanged, so muscle memory and scripts keep working
(``nvpulse -q``, ``nvpulse --query-gpu=name --format=csv`` ...).
"""

from __future__ import annotations

import argparse
import math
import os
import re
import stat
import sys

from . import __version__

OWN_ONLY = {"--classic"}  # flags stripped before forwarding to nvidia-smi
LOOP_GUARD = "NVPULSE_PASSTHROUGH"  # set before exec; seeing it again means we'd recurse
MAX_MOCK = 64
MAX_INDICES = 64
THEMES = ("default", "high-contrast", "mono")
# Where the driver's own nvidia-smi lives when it isn't on PATH. Under WSL the one
# on PATH is often nvidia-smi.exe on a Windows mount, which shows as world-writable
# and is (rightly) refused; this Linux copy passes the same checks.
FALLBACK_SMI = ("/usr/lib/wsl/lib/nvidia-smi",)

# -i selectors other than a plain index, as nvidia-smi accepts them
_INDEX_RE = re.compile(r"[0-9]{1,6}\Z")
_UUID_RE = re.compile(r"GPU-[0-9A-Fa-f-]{8,60}\Z")
_BUS_RE = re.compile(r"(?:([0-9A-Fa-f]{1,8}):)?([0-9A-Fa-f]{1,2}):([0-9A-Fa-f]{1,2})\.([0-9A-Fa-f])\Z")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nvpulse",
        description=(
            "nvpulse: animated, btop-style terminal dashboard for NVIDIA GPUs. "
            "Unknown flags are forwarded to nvidia-smi."
        ),
        epilog="examples:  nvpulse   |   nvpulse -i 0,1   |   nvpulse --mock 4   |   nvpulse -q   |   nvpulse --once",
        # No prefix matching: an abbreviated nvidia-smi flag must never be captured
        # by one of ours (it should be forwarded untouched).
        allow_abbrev=False,
    )
    p.add_argument("-i", "--id", metavar="GPU[,GPU]", help="only show these GPUs (index, UUID or PCI bus ID)")
    p.add_argument("-n", "--interval", type=float, metavar="SEC", help="poll interval (default 1.0)")
    p.add_argument("--fps", type=float, help="animation frame rate, 1-60 (default 20)")
    # On/off pairs, so a flag can also undo what the settings file turned on.
    onoff = argparse.BooleanOptionalAction
    p.add_argument("--anim", action=onoff, help="animate (default); --no-anim is static with minimal CPU")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--compact", dest="compact", action="store_true", default=None, help="force compact cards")
    g.add_argument("--expanded", dest="compact", action="store_false", help="force expanded cards")
    p.add_argument("--read-only", action=onoff, help="disable signalling processes (k/K)")
    p.add_argument("--hide-graphics", action=onoff, help="start with graphics-only processes hidden (g toggles)")
    p.add_argument(
        "--redact",
        action=onoff,
        help="mask --password=… and the like in command lines (default); --no-redact shows them",
    )
    p.add_argument(
        "--mock", type=int, nargs="?", const=2, metavar="N", help="simulate N GPUs (default 2), no hardware needed"
    )
    p.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    p.add_argument("--theme", choices=THEMES, help="colour theme (NO_COLOR in the environment also selects mono)")
    c = p.add_mutually_exclusive_group()
    c.add_argument("--config", metavar="FILE", help="settings file (default ~/.config/nvpulse/config.toml)")
    c.add_argument("--no-config", action="store_true", help="ignore the settings file")
    p.add_argument("--classic", action="store_true", help="run the real nvidia-smi instead")
    p.add_argument("--once", action="store_true", help="print one snapshot and exit (works in pipes and over SSH)")
    p.add_argument(
        "--dump", action="store_true", help="print one snapshot as JSON and exit (no names or IDs; for bug reports)"
    )
    p.add_argument("-V", "--version", action="version", version=f"nvpulse {__version__}")
    return p


# ------------------------------------------------------------- passthrough
def _trusted_executable(path: str) -> bool:
    """Absolute, regular, executable, and not writable by other users.

    When running as root, also require the binary (and its directory) to be owned
    by root, so an unprivileged user can't plant an ``nvidia-smi`` that root execs.
    """
    if not os.path.isabs(path):
        return False
    try:
        st = os.stat(path)
        dst = os.stat(os.path.dirname(path) or "/")
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode) or not os.access(path, os.X_OK):
        return False
    if st.st_mode & stat.S_IWOTH:
        return False
    # world-writable directory without the sticky bit: anyone could swap the file
    if dst.st_mode & stat.S_IWOTH and not dst.st_mode & stat.S_ISVTX:
        return False
    running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
    return not (running_as_root and (st.st_uid != 0 or dst.st_uid != 0 or st.st_mode & stat.S_IWGRP))


def _self_paths() -> set[str]:
    return {os.path.realpath(p) for p in (sys.argv[0] if sys.argv else "", sys.executable) if p}


def find_real_nvidia_smi() -> str | None:
    override = os.environ.get("NVPULSE_REAL_SMI")
    if override:
        if _trusted_executable(override):
            return override
        print(
            f"nvpulse: ignoring NVPULSE_REAL_SMI={override!r} (must be an absolute path to an executable "
            "that other users can't modify)",
            file=sys.stderr,
        )
        return None
    me = _self_paths()
    names = ["nvidia-smi", "nvidia-smi.exe"]  # .exe: WSL with Windows PATH entries
    for d in os.environ.get("PATH", "").split(os.pathsep):
        # Empty or relative PATH entries mean "the current directory": never exec from there.
        if not d or not os.path.isabs(d):
            continue
        for name in names:
            cand = os.path.join(d, name)
            if os.path.realpath(cand) in me:
                continue
            if _trusted_executable(cand):
                return cand
    for cand in FALLBACK_SMI:
        if os.path.realpath(cand) not in me and _trusted_executable(cand):
            return cand
    return None


def passthrough(argv: list[str]) -> int:
    if os.environ.get(LOOP_GUARD):
        print(
            "nvpulse: passthrough loop detected (the 'real' nvidia-smi on PATH runs nvpulse again); "
            "set NVPULSE_REAL_SMI to the driver's binary, e.g. /usr/bin/nvidia-smi",
            file=sys.stderr,
        )
        return 2
    real = find_real_nvidia_smi()
    if real is None:
        print("nvpulse: real nvidia-smi not found on PATH (set NVPULSE_REAL_SMI)", file=sys.stderr)
        return 127
    args = [a for a in argv if a not in OWN_ONLY]
    if sys.stdout is not None:
        sys.stdout.flush()
    env = dict(os.environ, **{LOOP_GUARD: "1"})
    try:
        os.execve(real, [real, *args], env)  # no shell involved; args are passed verbatim
    except OSError as exc:  # pragma: no cover
        print(f"nvpulse: failed to run {real}: {exc}", file=sys.stderr)
        return 126
    return 0  # pragma: no cover


# ------------------------------------------------------------- validation
def parse_indices(spec: str | None) -> list[int | str] | None:
    """Split ``-i``: indices come back as sorted ints, UUIDs and bus IDs as strings."""
    if not spec:
        return None
    tokens = [x.strip() for x in spec.split(",") if x.strip()]
    if len(tokens) > MAX_INDICES:
        raise SystemExit(f"nvpulse: -i takes at most {MAX_INDICES} GPUs")
    idx: set[int] = set()
    named: list[str] = []
    for tok in tokens:
        if _INDEX_RE.match(tok):
            idx.add(int(tok))
        elif _UUID_RE.match(tok) or _BUS_RE.match(tok):
            if tok not in named:
                named.append(tok)
        else:
            raise SystemExit(
                "nvpulse: -i takes GPU indices, UUIDs (GPU-…) or PCI bus IDs (0000:01:00.0) in dashboard mode"
            )
    return [*sorted(idx), *named]


def _bus_key(bus_id: str) -> tuple[int, ...] | None:
    """Comparable form of a bus ID: nvidia-smi prints an 8-digit domain, lspci 4 or none."""
    m = _BUS_RE.match(bus_id.strip())
    return tuple(int(part or "0", 16) for part in m.groups()) if m else None


def resolve_indices(selectors: list[int | str] | None, identities: list[tuple[int, str, str]]) -> list[int] | None:
    """Turn parsed ``-i`` selectors into GPU indices using ``Backend.identify()``."""
    if selectors is None:
        return None
    out = {s for s in selectors if isinstance(s, int)}
    for sel in (s for s in selectors if isinstance(s, str)):
        key = _bus_key(sel)
        hits = [i for i, uuid, bus in identities if uuid.lower() == sel.lower() or (key and _bus_key(bus) == key)]
        if not hits:
            raise SystemExit(f"nvpulse: no GPU matches -i {sel}")  # sel passed the regexes: plain ASCII
        out.update(hits)
    return sorted(out)


def clamp(value: float, lo: float, hi: float, name: str) -> float:
    if not math.isfinite(value):
        raise SystemExit(f"nvpulse: {name} must be a finite number")
    return min(hi, max(lo, value))


def decide(argv: list[str], isatty: bool) -> tuple[str, argparse.Namespace | None]:
    """Return ("dashboard", args), ("dump", args) or ("passthrough", None)."""
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    for mode in ("dump", "once"):
        if getattr(args, mode):
            if args.classic or unknown or (args.dump and args.once):
                raise SystemExit(f"nvpulse: --{mode} can't be combined with nvidia-smi flags or another mode")
            return mode, args  # meant to be piped, so no TTY check
    if args.classic or unknown:
        return "passthrough", None
    if not isatty and not args.mock:
        return "passthrough", None
    return "dashboard", args


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # sys.stdout is None when fd 1 is closed (`nvpulse >&-`)
    mode, args = decide(argv, bool(sys.stdout and sys.stdout.isatty()))
    if mode == "passthrough":
        return passthrough(argv)
    assert args is not None

    from .config import Config, ConfigError, ConfigUntrusted, load

    named = args.config or os.environ.get("NVPULSE_CONFIG") or None
    try:
        # --dump uses no settings, and a broken file must not block a bug report
        cfg = Config() if args.no_config or mode == "dump" else load(named)
    except ConfigUntrusted as exc:
        if named:
            print(f"nvpulse: {exc}", file=sys.stderr)
            return 2
        # The default file wasn't asked for (think `sudo` with your HOME): carry on without it.
        print(f"nvpulse: {exc}; continuing without it", file=sys.stderr)
        cfg = Config()
    except ConfigError as exc:
        print(f"nvpulse: {exc}", file=sys.stderr)
        print("  fix the file, or start with --no-config", file=sys.stderr)
        return 2

    def pick(cli_value, cfg_value, default):
        """Command line first, then the settings file, then the built-in default."""
        return cli_value if cli_value is not None else (cfg_value if cfg_value is not None else default)

    interval = clamp(pick(args.interval, cfg.interval, 1.0), 0.1, 3600.0, "--interval")
    fps = clamp(pick(args.fps, cfg.fps, 20.0), 1.0, 60.0, "--fps")
    theme = pick(args.theme, cfg.theme, "mono" if os.environ.get("NO_COLOR") else "default")
    redact = pick(args.redact, cfg.redact, True)
    hide_graphics = pick(args.hide_graphics, cfg.hide_graphics, False)
    # An explicit colour theme beats NO_COLOR; both Rich and Textual read the variable.
    if theme == "mono":
        os.environ["NO_COLOR"] = "1"
    else:
        os.environ.pop("NO_COLOR", None)
    selectors = parse_indices(args.id)
    mock = int(clamp(args.mock, 1, MAX_MOCK, "--mock")) if args.mock is not None else None

    from .backend import make_backend

    try:
        backend = make_backend(mock=mock, seed=args.seed)
    except Exception as exc:
        print(f"nvpulse: {exc}", file=sys.stderr)
        print("  try `nvpulse --mock` to preview the dashboard without a GPU", file=sys.stderr)
        return 1

    try:
        # only UUIDs and bus IDs need the backend to resolve them
        named = selectors is not None and any(isinstance(s, str) for s in selectors)
        indices = resolve_indices(selectors, backend.identify() if named else [])
        if mode == "dump":
            from .dump import dumps

            print(dumps(backend, indices))
        elif mode == "once":
            from .backend.models import Alerts
            from .once import print_once
            from .ui import render

            render.set_theme(theme)
            print_once(
                backend,
                indices,
                redact=redact,
                hide_graphics=hide_graphics,
                alerts=Alerts(cfg.alert_temp, cfg.alert_vram, cfg.alert_bell),
            )
        if mode in ("dump", "once") and sys.stdout is not None:
            sys.stdout.flush()
    except BrokenPipeError:  # `nvpulse --once | head`: the reader left, which is fine
        backend.close()
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())  # keep exit-time flush quiet
        return 0
    except BaseException:
        backend.close()
        raise
    if mode in ("dump", "once"):
        backend.close()
        return 0

    from .backend.models import Alerts
    from .ui import render
    from .ui.app import NvPulse

    render.set_theme(theme)
    layout = {"compact": True, "expanded": False}.get(cfg.layout or "auto")

    app = NvPulse(
        backend,
        interval=interval,
        fps=fps,
        indices=indices,
        animate=pick(args.anim, cfg.animate, True),
        compact=pick(args.compact, layout, None),
        redact=redact,
        read_only=pick(args.read_only, cfg.read_only, False),
        hide_graphics=hide_graphics,
        sort=cfg.sort or "vram",
        hidden_columns=cfg.hidden_columns,
        alerts=Alerts(cfg.alert_temp, cfg.alert_vram, cfg.alert_bell),
        cost_per_kwh=cfg.cost_per_kwh,
        currency=cfg.currency,
        theme=theme,
    )
    app.run()
    return app.return_code or 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
