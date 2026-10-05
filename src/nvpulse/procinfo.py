"""Fill in user / name / command line for GPU processes (cached per PID).

Everything read here is untrusted (any local user controls their own argv), so it
is sanitised and length-capped before it is stored. See :mod:`nvpulse.sanitize`.
"""

from __future__ import annotations

from .backend.models import ProcessInfo
from .sanitize import clean, redact

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

MAX_NAME = 64
MAX_USER = 32
MAX_CMDLINE = 1024
_MAX_PROC_READ = 64 * 1024  # bytes read from /proc/<pid>/cmdline in the fallback path

# pid -> (create_time, name, user, cmdline), values already sanitised
_cache: dict[int, tuple[float | None, str, str, str]] = {}


def _lookup(pid: int) -> tuple[float | None, str, str, str] | None:
    if psutil is None:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw = fh.read(_MAX_PROC_READ)
            cmd = raw.replace(b"\0", b" ").decode(errors="replace").strip()
            name = cmd.split(" ", 1)[0].rsplit("/", 1)[-1] if cmd else "?"
            return None, name, "?", cmd
        except OSError:
            return None
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            created = p.create_time()
            cached = _cache.get(pid)
            if cached and cached[0] == created:
                return cached
            name = p.name()
            try:
                user = p.username()
            except Exception:
                user = "?"
            try:
                cmd = " ".join(p.cmdline()) or name
            except Exception:
                cmd = name
        entry = (created, clean(name, MAX_NAME), clean(user, MAX_USER), clean(cmd, MAX_CMDLINE))
        _cache[pid] = entry
        return entry
    except Exception:  # NoSuchProcess, AccessDenied, pid in another namespace
        return None


def enrich(processes: list[ProcessInfo], *, redact_secrets: bool = True) -> None:
    """Populate name/user/cmdline/started in place; sanitise whatever the backend set."""
    for proc in processes:
        if proc.name == "?" or not proc.cmdline:
            info = _lookup(proc.pid)
            if info:
                proc.started, proc.name, proc.user, proc.cmdline = info
        # Always re-clean: backends (mock, future remote ones) may supply raw text.
        proc.name = clean(proc.name, MAX_NAME)
        proc.user = clean(proc.user, MAX_USER)
        proc.cmdline = clean(proc.cmdline, MAX_CMDLINE)
        if redact_secrets:
            proc.cmdline = redact(proc.cmdline)
    live = {p.pid for p in processes}
    for pid in list(_cache):
        if pid not in live:
            _cache.pop(pid, None)


def process_start_time(pid: int) -> float | None:
    """Kernel start time of ``pid`` (used to detect PID reuse), or None if unknown."""
    if psutil is None:
        return None
    try:
        return psutil.Process(pid).create_time()
    except Exception:
        return None
