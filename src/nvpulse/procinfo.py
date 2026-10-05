"""Fill in user / name / command line for GPU processes (cached per PID)."""

from __future__ import annotations

from .backend.models import ProcessInfo

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

_cache: dict[int, tuple[float, str, str, str]] = {}


def _lookup(pid: int) -> tuple[str, str, str] | None:
    if psutil is None:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode(errors="replace").strip()
            name = cmd.split(" ", 1)[0].rsplit("/", 1)[-1] if cmd else "?"
            return name, "?", cmd
        except OSError:
            return None
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            created = p.create_time()
            cached = _cache.get(pid)
            if cached and cached[0] == created:
                return cached[1], cached[2], cached[3]
            name = p.name()
            try:
                user = p.username()
            except Exception:
                user = "?"
            try:
                cmd = " ".join(p.cmdline()) or name
            except Exception:
                cmd = name
        _cache[pid] = (created, name, user, cmd)
        return name, user, cmd
    except Exception:  # NoSuchProcess, AccessDenied, pid in another namespace
        return None


def enrich(processes: list[ProcessInfo]) -> None:
    for proc in processes:
        if proc.name != "?" and proc.cmdline:
            continue  # backend already filled it (mock)
        info = _lookup(proc.pid)
        if info:
            proc.name, proc.user, proc.cmdline = info
    live = {p.pid for p in processes}
    for pid in list(_cache):
        if pid not in live:
            _cache.pop(pid, None)
