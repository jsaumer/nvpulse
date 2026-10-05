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

from ..sanitize import clean
from .models import Backend, GpuDetail, GpuSnapshot, ProcessInfo, SystemInfo

try:  # nvidia-ml-py exposes the module as ``pynvml``
    import pynvml as N
except ImportError:  # pragma: no cover - handled by cli
    N = None  # type: ignore[assignment]


def _safe(fn: Callable[..., Any], *args: Any, default: Any = None) -> Any:
    try:
        return fn(*args)
    except Exception:  # NVMLError_NotSupported, NoPermission, Unknown, ...
        return default


def _call(name: str, *args: Any, default: Any = None) -> Any:
    """``_safe`` by name, for calls newer than the oldest bindings we support.

    Looking ``N.<name>`` up directly raises AttributeError outside ``_safe`` when the
    installed nvidia-ml-py predates the call. A ``None`` argument means a constant
    was missing the same way (see ``_const``), so the call is skipped as well.
    """
    fn = getattr(N, name, None)
    if fn is None or any(a is None for a in args):
        return default
    return _safe(fn, *args, default=default)


def _const(name: str) -> Any:
    return getattr(N, name, None)


def _s(value: Any, max_len: int = 128) -> str:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return clean(value, max_len)


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
            hostname=clean(socket.gethostname(), 64),
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
                "pcie_gen_max": _call("nvmlDeviceGetMaxPcieLinkGeneration", h),
                "pcie_gen_device_max": _call("nvmlDeviceGetGpuMaxPcieLinkGeneration", h),
                "pcie_width_max": _call("nvmlDeviceGetMaxPcieLinkWidth", h),
            }
        return self._static[i]

    def identify(self) -> list[tuple[int, str, str]]:
        out = []
        for i in range(self.device_count()):
            h = _safe(self._handle, i)
            if h is not None:
                st = self._static_info(i, h)
                out.append((i, st["uuid"], st["bus_id"]))
        return out

    def _clock_reasons(self, h: Any) -> int | None:
        # Renamed from "throttle reasons" in newer drivers; the bits are the same.
        for name in ("nvmlDeviceGetCurrentClocksEventReasons", "nvmlDeviceGetCurrentClocksThrottleReasons"):
            mask = _call(name, h)
            if mask is not None:
                return int(mask)
        return None

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

    def _memory(self, h: Any) -> Any:
        # The v1 struct folds driver-reserved memory into "used" (a few hundred MiB
        # more than nvidia-smi shows); v2 reports it separately. Older drivers and
        # bindings only have v1.
        v2 = getattr(N, "nvmlMemory_v2", None)
        mem = _safe(N.nvmlDeviceGetMemoryInfo, h, v2) if v2 is not None else None
        return mem if mem is not None else _safe(N.nvmlDeviceGetMemoryInfo, h)

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
            mem = self._memory(h)
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
                    pcie_gen_max=st["pcie_gen_max"],
                    pcie_gen_device_max=st["pcie_gen_device_max"],
                    pcie_width_max=st["pcie_width_max"],
                    persistence=bool(persistence) if persistence is not None else None,
                    clock_reasons=self._clock_reasons(h),
                    processes=self._processes(i, h),
                )
            )
        return out

    # ------------------------------------------------------------------ detail
    def _detail_static(self, i: int, h: Any) -> dict[str, Any]:
        st = self._static_info(i, h)
        if "vbios" not in st:
            limit_mw = _call("nvmlDeviceGetPowerManagementDefaultLimit", h)
            threshold = "nvmlDeviceGetTemperatureThreshold"
            st.update(
                vbios=_s(_call("nvmlDeviceGetVbiosVersion", h, default=""), 48),
                temp_target=_call(threshold, h, _const("NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR")),
                temp_max_operating=_call(threshold, h, _const("NVML_TEMPERATURE_THRESHOLD_GPU_MAX")),
                power_default_limit=limit_mw / 1000.0 if limit_mw is not None else None,
                clock_video_max=_call("nvmlDeviceGetMaxClockInfo", h, _const("NVML_CLOCK_VIDEO")),
            )
        return st

    def _fan_rpm(self, h: Any, num_fans: int | None) -> list[int]:
        rpm = []
        for f in range(num_fans or 0):
            v = _call("nvmlDeviceGetFanSpeedRPM", h, f)
            if v is None:
                break
            rpm.append(int(v))
        if not rpm:  # bindings whose call takes no fan index report the first fan only
            v = _call("nvmlDeviceGetFanSpeedRPM", h)
            if v is not None:
                rpm.append(int(v))
        return rpm

    def detail(self, index: int) -> GpuDetail | None:
        if index >= self.device_count():
            return None
        h = _safe(self._handle, index)
        if h is None:
            return None
        st = self._detail_static(index, h)
        energy_mj = _call("nvmlDeviceGetTotalEnergyConsumption", h)
        targets = [_call("nvmlDeviceGetTargetFanSpeed", h, f) for f in range(st["num_fans"] or 0)]

        def ecc(kind: str) -> int | None:
            return _call("nvmlDeviceGetTotalEccErrors", h, _const(kind), _const("NVML_AGGREGATE_ECC"))

        return GpuDetail(
            index=index,
            vbios=st["vbios"],
            fan_rpm=self._fan_rpm(h, st["num_fans"]),
            fan_target=[float(t) if t is not None else None for t in targets],  # index = fan number
            temp_target=st["temp_target"],
            temp_max_operating=st["temp_max_operating"],
            power_default_limit=st["power_default_limit"],
            energy=energy_mj / 1000.0 if energy_mj is not None else None,
            clock_video=_call("nvmlDeviceGetClockInfo", h, _const("NVML_CLOCK_VIDEO")),
            clock_video_max=st["clock_video_max"],
            # ~20 ms each: the driver samples the link for that long before answering
            pcie_tx=_call("nvmlDeviceGetPcieThroughput", h, _const("NVML_PCIE_UTIL_TX_BYTES")),
            pcie_rx=_call("nvmlDeviceGetPcieThroughput", h, _const("NVML_PCIE_UTIL_RX_BYTES")),
            pcie_replay=_call("nvmlDeviceGetPcieReplayCounter", h),
            ecc_corrected=ecc("NVML_MEMORY_ERROR_TYPE_CORRECTED"),
            ecc_uncorrected=ecc("NVML_MEMORY_ERROR_TYPE_UNCORRECTED"),
        )

    def close(self) -> None:
        _safe(N.nvmlShutdown)
