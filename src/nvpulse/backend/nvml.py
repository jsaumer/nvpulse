"""NVML-backed collector.

Every NVML call goes through ``_safe`` so that a field a given GPU/driver doesn't
support (fans on datacenter cards, power on some laptops, process memory under
WSL, ...) simply comes back as ``None`` instead of crashing the dashboard.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

from .models import Backend, GpuSnapshot, ProcessInfo, SystemInfo

try:  # nvidia-ml-py exposes the module as ``pynvml``
    import pynvml as N
except ImportError:  # pragma: no cover - handled by cli
    N = None  # type: ignore[assignment]


def _safe(fn: Callable[..., Any], *args: Any, default: Any = None) -> Any:
    try:
        return fn(*args)
    except Exception:  # NVMLError_NotSupported, NoPermission, Unknown, ...
        return default


def _s(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


class NvmlUnavailable(RuntimeError):
    pass


class NvmlBackend(Backend):
    def __init__(self) -> None:
        if N is None:
            raise NvmlUnavailable("nvidia-ml-py is not installed (pip install nvidia-ml-py)")
        try:
            N.nvmlInit()
        except Exception as exc:  # driver missing, no GPU, container without libs
            raise NvmlUnavailable(f"NVML init failed: {exc}") from exc
        self._handles: dict[int, Any] = {}
        self._static: dict[int, dict[str, Any]] = {}

    # ------------------------------------------------------------------ system
    def system_info(self) -> SystemInfo:
        cuda = _safe(N.nvmlSystemGetCudaDriverVersion)
        cuda_str = f"{cuda // 1000}.{(cuda % 1000) // 10}" if isinstance(cuda, int) else "?"
        return SystemInfo(
            driver_version=_s(_safe(N.nvmlSystemGetDriverVersion, default="?")),
            cuda_version=cuda_str,
            nvml_version=_s(_safe(N.nvmlSystemGetNVMLVersion, default="?")),
            hostname=socket.gethostname(),
        )

    def device_count(self) -> int:
        return int(_safe(N.nvmlDeviceGetCount, default=0))

    # ----------------------------------------------------------------- devices
    def _handle(self, i: int) -> Any:
        if i not in self._handles:
            self._handles[i] = N.nvmlDeviceGetHandleByIndex(i)
        return self._handles[i]

    def _static_info(self, i: int, h: Any) -> dict[str, Any]:
        if i not in self._static:
            pci = _safe(N.nvmlDeviceGetPciInfo, h)
            self._static[i] = {
                "name": _s(_safe(N.nvmlDeviceGetName, h, default="Unknown GPU")),
                "uuid": _s(_safe(N.nvmlDeviceGetUUID, h, default="")),
                "bus_id": _s(pci.busId) if pci is not None else "",
                "temp_slowdown": _safe(N.nvmlDeviceGetTemperatureThreshold, h, N.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN),
                "temp_shutdown": _safe(N.nvmlDeviceGetTemperatureThreshold, h, N.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN),
                "clock_sm_max": _safe(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_SM),
                "clock_mem_max": _safe(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_MEM),
                "num_fans": _safe(N.nvmlDeviceGetNumFans, h, default=None),
            }
        return self._static[i]

    def _fans(self, h: Any, num_fans: int | None) -> list[float]:
        fans: list[float] = []
        if num_fans:
            for f in range(num_fans):
                v = _safe(N.nvmlDeviceGetFanSpeed_v2, h, f)
                if v is not None:
                    fans.append(float(v))
        if not fans:
            v = _safe(N.nvmlDeviceGetFanSpeed, h)
            if v is not None:
                fans.append(float(v))
        return fans

    def _processes(self, i: int, h: Any) -> list[ProcessInfo]:
        procs: dict[int, ProcessInfo] = {}
        for kind, getter in (
            ("C", N.nvmlDeviceGetComputeRunningProcesses),
            ("G", N.nvmlDeviceGetGraphicsRunningProcesses),
        ):
            for p in _safe(getter, h, default=[]) or []:
                mem = getattr(p, "usedGpuMemory", None)
                if isinstance(mem, int) and mem >= (1 << 63):  # NVML_VALUE_NOT_AVAILABLE
                    mem = None
                if p.pid in procs:
                    existing = procs[p.pid]
                    existing.kind = "C+G"
                    if existing.used_memory is None:
                        existing.used_memory = mem
                else:
                    procs[p.pid] = ProcessInfo(gpu_index=i, pid=p.pid, kind=kind, used_memory=mem)

        # Per-process SM / memory utilisation: NVML returns samples newer than the
        # given CPU timestamp (µs). Look back a couple of seconds, keep the newest.
        if procs:
            since = int(time.time() * 1e6) - 2_000_000
            samples = _safe(N.nvmlDeviceGetProcessUtilization, h, since, default=None) or []
            newest: dict[int, int] = {}
            for s in samples:
                ts = int(getattr(s, "timeStamp", 0))
                if s.pid in procs and ts >= newest.get(s.pid, -1):
                    newest[s.pid] = ts
                    procs[s.pid].sm_util = int(s.smUtil)
                    procs[s.pid].mem_util = int(s.memUtil)
        return list(procs.values())

    def poll(self, indices: list[int] | None = None) -> list[GpuSnapshot]:
        count = self.device_count()
        wanted = indices if indices is not None else list(range(count))
        out: list[GpuSnapshot] = []
        for i in wanted:
            if i >= count:
                continue
            h = _safe(self._handle, i)
            if h is None:
                continue
            st = self._static_info(i, h)
            util = _safe(N.nvmlDeviceGetUtilizationRates, h)
            mem = _safe(N.nvmlDeviceGetMemoryInfo, h)
            power_mw = _safe(N.nvmlDeviceGetPowerUsage, h)
            limit_mw = _safe(N.nvmlDeviceGetEnforcedPowerLimit, h)
            enc = _safe(N.nvmlDeviceGetEncoderUtilization, h)
            dec = _safe(N.nvmlDeviceGetDecoderUtilization, h)
            fans = self._fans(h, st["num_fans"])
            persistence = _safe(N.nvmlDeviceGetPersistenceMode, h)

            out.append(
                GpuSnapshot(
                    index=i,
                    name=st["name"],
                    uuid=st["uuid"],
                    bus_id=st["bus_id"],
                    util_gpu=float(util.gpu) if util is not None else None,
                    util_mem=float(util.memory) if util is not None else None,
                    mem_total=int(mem.total) if mem is not None else None,
                    mem_used=int(mem.used) if mem is not None else None,
                    temp=_safe(N.nvmlDeviceGetTemperature, h, N.NVML_TEMPERATURE_GPU),
                    temp_slowdown=st["temp_slowdown"],
                    temp_shutdown=st["temp_shutdown"],
                    fan=(sum(fans) / len(fans)) if fans else None,
                    fans=fans,
                    power=power_mw / 1000.0 if power_mw is not None else None,
                    power_limit=limit_mw / 1000.0 if limit_mw is not None else None,
                    clock_sm=_safe(N.nvmlDeviceGetClockInfo, h, N.NVML_CLOCK_SM),
                    clock_mem=_safe(N.nvmlDeviceGetClockInfo, h, N.NVML_CLOCK_MEM),
                    clock_sm_max=st["clock_sm_max"],
                    clock_mem_max=st["clock_mem_max"],
                    pstate=_safe(N.nvmlDeviceGetPerformanceState, h),
                    enc_util=float(enc[0]) if enc else None,
                    dec_util=float(dec[0]) if dec else None,
                    pcie_gen=_safe(N.nvmlDeviceGetCurrPcieLinkGeneration, h),
                    pcie_width=_safe(N.nvmlDeviceGetCurrPcieLinkWidth, h),
                    persistence=bool(persistence) if persistence is not None else None,
                    processes=self._processes(i, h),
                )
            )
        return out

    def close(self) -> None:
        _safe(N.nvmlShutdown)
