"""Command-line entry point.

``nvpulse`` (also installed as ``nvidia-smi+``) with no arguments opens the dashboard.
Anything the dashboard doesn't understand is handed to the real ``nvidia-smi``
unchanged, so muscle memory and scripts keep working
(``nvpulse -q``, ``nvpulse --query-gpu=name --format=csv`` ...).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from . import __version__

OWN_ONLY = {"--classic"}  # flags stripped before forwarding to nvidia-smi


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nvpulse",
        description=(
            "nvpulse: animated, btop-style terminal dashboard for NVIDIA GPUs. "
            "Unknown flags are forwarded to nvidia-smi."
        ),
        epilog="examples:  nvpulse   |   nvpulse -i 0,1   |   nvpulse --mock 4   |   nvpulse -q",
    )
    p.add_argument("-i", "--id", metavar="IDX[,IDX]", help="only show these GPU indices")
    p.add_argument("-n", "--interval", type=float, default=1.0, metavar="SEC", help="poll interval (default 1.0)")
    p.add_argument("--fps", type=float, default=20.0, help="animation frame rate (default 20)")
    p.add_argument("--no-anim", action="store_true", help="static display, minimal CPU")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--compact", dest="compact", action="store_true", default=None, help="force compact cards")
    g.add_argument("--expanded", dest="compact", action="store_false", help="force expanded cards")
    p.add_argument(
        "--mock", type=int, nargs="?", const=2, metavar="N", help="simulate N GPUs (default 2), no hardware needed"
    )
    p.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    p.add_argument("--classic", action="store_true", help="run the real nvidia-smi instead")
    p.add_argument("-V", "--version", action="version", version=f"nvpulse {__version__}")
    return p


def find_real_nvidia_smi() -> str | None:
    override = os.environ.get("NVPULSE_REAL_SMI")
    if override:
        return override
    me = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, "nvidia-smi")
        if os.path.isfile(cand) and os.access(cand, os.X_OK) and os.path.realpath(cand) != me:
            return cand
    exe = shutil.which("nvidia-smi.exe")  # WSL / Windows
    return exe


def passthrough(argv: list[str]) -> int:
    real = find_real_nvidia_smi()
    if real is None:
        print("nvpulse: real nvidia-smi not found on PATH (set NVPULSE_REAL_SMI)", file=sys.stderr)
        return 127
    args = [a for a in argv if a not in OWN_ONLY]
    sys.stdout.flush()
    try:
        os.execv(real, [real, *args])
    except OSError as exc:  # pragma: no cover
        print(f"nvpulse: failed to run {real}: {exc}", file=sys.stderr)
        return 126
    return 0  # pragma: no cover


def parse_indices(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    try:
        return sorted({int(x) for x in spec.split(",") if x.strip()})
    except ValueError:
        raise SystemExit("nvpulse: -i takes comma-separated GPU indices in dashboard mode") from None


def decide(argv: list[str], isatty: bool) -> tuple[str, argparse.Namespace | None]:
    """Return ("dashboard", args) or ("passthrough", None)."""
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    if args.classic or unknown:
        return "passthrough", None
    if not isatty and not args.mock:
        return "passthrough", None
    return "dashboard", args


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode, args = decide(argv, sys.stdout.isatty())
    if mode == "passthrough":
        return passthrough(argv)
    assert args is not None

    from .backend import make_backend

    try:
        backend = make_backend(mock=args.mock, seed=args.seed)
    except Exception as exc:
        print(f"nvpulse: {exc}", file=sys.stderr)
        print("  try `nvpulse --mock` to preview the dashboard without a GPU", file=sys.stderr)
        return 1

    from .ui.app import NvPulse

    app = NvPulse(
        backend,
        interval=max(0.1, args.interval),
        fps=args.fps,
        indices=parse_indices(args.id),
        animate=not args.no_anim,
        compact=args.compact,
    )
    app.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
