"""Plain data containers passed from a backend to the UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProcessInfo:
    gpu_index: int
    pid: int
    kind: str  # "C" compute, "G" graphics, "C+G" both
    used_memory: int | None  # bytes, None when the driver can't report it
    sm_util: int | None = None  # percent
    mem_util: int | None = None  # percent
    name: str = "?"
    user: str = "?"
    cmdline: str = ""


@dataclass(slots=True)
class GpuSnapshot:
    index: int
    name: str
    uuid: str = ""
    bus_id: str = ""

    util_gpu: float | None = None  # percent
    util_mem: float | None = None  # memory-controller busy percent

    mem_total: int | None = None  # bytes
    mem_used: int | None = None

    temp: float | None = None  # °C
    temp_slowdown: float | None = None
    temp_shutdown: float | None = None

    fan: float | None = None  # percent; None = no fan / not reported
    fans: list[float] = field(default_factory=list)

    power: float | None = None  # watts
    power_limit: float | None = None

    clock_sm: int | None = None  # MHz
    clock_mem: int | None = None
    clock_sm_max: int | None = None
    clock_mem_max: int | None = None

    pstate: int | None = None
    enc_util: float | None = None
    dec_util: float | None = None
    pcie_gen: int | None = None
    pcie_width: int | None = None
    persistence: bool | None = None

    processes: list[ProcessInfo] = field(default_factory=list)

    @property
    def mem_pct(self) -> float | None:
        if not self.mem_total or self.mem_used is None:
            return None
        return 100.0 * self.mem_used / self.mem_total

    @property
    def power_pct(self) -> float | None:
        if not self.power_limit or self.power is None:
            return None
        return 100.0 * self.power / self.power_limit


@dataclass(slots=True)
class SystemInfo:
    driver_version: str = "?"
    cuda_version: str = "?"
    nvml_version: str = "?"
    hostname: str = ""


class Backend:
    """Interface every data source implements."""

    def system_info(self) -> SystemInfo:  # pragma: no cover - interface
        raise NotImplementedError

    def device_count(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def poll(self, indices: list[int] | None = None) -> list[GpuSnapshot]:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:
        pass
