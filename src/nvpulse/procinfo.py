"""Fill in user / name / command line for GPU processes (cached per PID).

Everything read here is untrusted (any local user controls their own argv), so it
is sanitised and length-capped before it is stored. See :mod:`nvpulse.sanitize`.
"""

from __future__ import annotations

import re

from .backend.models import ProcessInfo
from .sanitize import clean, redact

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

MAX_NAME = 64
MAX_USER = 32
MAX_CMDLINE = 1024
MAX_UNIT = 40
_MAX_PROC_READ = 64 * 1024  # bytes read from /proc/<pid>/cmdline in the fallback path
_MAX_CGROUP_READ = 8 * 1024

# pid -> (create_time, name, user, cmdline, unit), values already sanitised
_Entry = tuple[float | None, str, str, str, str]
_cache: dict[int, _Entry] = {}

# Container runtimes name their cgroups after the 64-hex container ID. The name is
# all we use: asking the runtime for a friendly name would need its (root-equivalent)
# socket.
_HEX = r"([0-9a-f]{64})"
_CONTAINER_RES = (
    ("docker", re.compile(rf"(?:/docker/|/docker-){_HEX}")),
    ("podman", re.compile(rf"/libpod-{_HEX}")),
    ("containerd", re.compile(rf"/cri-containerd-{_HEX}")),
    ("crio", re.compile(rf"/crio-{_HEX}")),
    ("k8s", re.compile(rf"/kubepods[^\n]*/{_HEX}")),
)
_LXC_RE = re.compile(r"/lxc(?:\.payload\.|/)([^/\n]+)")
_SERVICE_RE = re.compile(r"/([^/\n]+)\.service$")


def parse_cgroup(text: str) -> str:
    """Name the container or systemd service from the contents of ``/proc/<pid>/cgroup``.

    Returns e.g. ``docker:3f2a9c1b2d4e``, ``lxc:build01`` or ``ollama`` (for the
    system service ``ollama.service``), or "" for an ordinary session process.
    """
    paths = [line.split(":", 2)[2] for line in text.splitlines() if line.count(":") >= 2]
    for path in paths:
        for runtime, rx in _CONTAINER_RES:
            m = rx.search(path)
            if m:
                return f"{runtime}:{m.group(1)[:12]}"
        m = _LXC_RE.search(path)
        if m:
            return f"lxc:{m.group(1)}"
    for path in paths:
        # System services only. A desktop session runs every app as a user unit
        # (app-org.kde.konsole@….service), which would label everything.
        m = _SERVICE_RE.search(path)
        if m and "/user.slice/" not in path and not m.group(1).startswith("user@"):
            return m.group(1)
    return ""


def _unit(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cgroup", "rb") as fh:
            raw = fh.read(_MAX_CGROUP_READ)
    except OSError:
        return ""
    # cgroup names are chosen by whoever created them (any user, for user units)
    return clean(parse_cgroup(raw.decode(errors="replace")), MAX_UNIT)


def _lookup(pid: int) -> _Entry | None:
    if psutil is None:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw = fh.read(_MAX_PROC_READ)
            cmd = raw.replace(b"\0", b" ").decode(errors="replace").strip()
            name = cmd.split(" ", 1)[0].rsplit("/", 1)[-1] if cmd else "?"
            return None, name, "?", cmd, _unit(pid)
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
        entry = (created, clean(name, MAX_NAME), clean(user, MAX_USER), clean(cmd, MAX_CMDLINE), _unit(pid))
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
                proc.started, proc.name, proc.user, proc.cmdline, proc.unit = info
        # Always re-clean: backends (mock, future remote ones) may supply raw text.
        proc.name = clean(proc.name, MAX_NAME)
        proc.user = clean(proc.user, MAX_USER)
        proc.cmdline = clean(proc.cmdline, MAX_CMDLINE)
        proc.unit = clean(proc.unit, MAX_UNIT)
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
