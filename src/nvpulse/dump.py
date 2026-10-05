"""``nvpulse --dump``: one snapshot as JSON on stdout, for bug reports and test fixtures.

The output is meant to be pasted into a public issue, so it leaves out anything
that identifies the machine or its users: no hostname, no GPU UUID, and for
processes only the type and the numbers (no PID, name, user or command line).
Nothing is written anywhere except stdout.
"""

from __future__ import annotations

import dataclasses
import json
import platform
from importlib import metadata
from typing import Any

from . import __version__
from .backend.models import Backend

SCHEMA = 1
PROCESS_FIELDS = ("kind", "used_memory", "sm_util", "mem_util")


def _bindings_version() -> str | None:
    try:
        return metadata.version("nvidia-ml-py")
    except metadata.PackageNotFoundError:
        return None


def build(backend: Backend, indices: list[int] | None = None) -> dict[str, Any]:
    info = backend.system_info()
    gpus = []
    for snap in backend.poll(indices):
        gpu = dataclasses.asdict(snap)
        gpu["uuid"] = "GPU-<redacted>" if snap.uuid else ""
        gpu["processes"] = [{k: getattr(p, k) for k in PROCESS_FIELDS} for p in snap.processes]
        try:
            detail = backend.detail(snap.index)
        except Exception:  # a dump with the basics beats a traceback
            detail = None
        gpu["detail"] = dataclasses.asdict(detail) if detail is not None else None
        gpus.append(gpu)
    return {
        "schema": SCHEMA,
        "nvpulse": __version__,
        "backend": type(backend).__name__,
        "system": {
            "driver_version": info.driver_version,
            "cuda_version": info.cuda_version,
            "nvml_version": info.nvml_version,
            "nvidia_ml_py": _bindings_version(),
            "python": platform.python_version(),
            "kernel": f"{platform.system()} {platform.release()}",
        },
        "gpus": gpus,
    }


def dumps(backend: Backend, indices: list[int] | None = None) -> str:
    # ensure_ascii: whatever a driver string contains, only printable ASCII reaches the terminal
    return json.dumps(build(backend, indices), indent=2, ensure_ascii=True)
