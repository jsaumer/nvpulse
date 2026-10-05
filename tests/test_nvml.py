"""NvmlBackend against a fake ``pynvml`` replaying values recorded from real hardware.

The numbers are from an RTX 4070 SUPER on driver 615.71.09 (desktop, fans stopped at idle).
"""

from __future__ import annotations

import time
from types import SimpleNamespace as NS

import pytest

from nvpulse.backend import nvml
from nvpulse.backend.nvml import NvmlBackend

MIB = 1 << 20
NOT_AVAILABLE = (1 << 64) - 1  # NVML_VALUE_NOT_AVAILABLE for usedGpuMemory


class NotSupported(Exception):
    pass


class FakeNvml:
    """Just enough of pynvml for NvmlBackend. Anything not defined raises NotSupported."""

    NVML_TEMPERATURE_GPU = 0
    NVML_TEMPERATURE_THRESHOLD_SHUTDOWN = 0
    NVML_TEMPERATURE_THRESHOLD_SLOWDOWN = 1
    NVML_CLOCK_SM = 1
    NVML_CLOCK_MEM = 2
    nvmlMemory_v2 = 0x02000028

    def __init__(self) -> None:
        self.fan_speeds = [0, 0]
        self.compute = [NS(pid=2636, usedGpuMemory=206 * MIB), NS(pid=75768, usedGpuMemory=294 * MIB)]
        self.graphics = [NS(pid=2636, usedGpuMemory=206 * MIB), NS(pid=1886, usedGpuMemory=NOT_AVAILABLE)]
        now = int(time.time() * 1e6)
        self.samples = [
            NS(pid=2636, smUtil=3, memUtil=0, timeStamp=now - 900_000),
            NS(pid=2636, smUtil=7, memUtil=1, timeStamp=now - 100_000),
            NS(pid=4242, smUtil=50, memUtil=9, timeStamp=now),  # not on this GPU's process list
        ]

    def __getattr__(self, name: str):
        def unsupported(*_a, **_k):
            raise NotSupported(name)

        return unsupported

    def nvmlInit(self) -> None:
        pass

    def nvmlSystemGetDriverVersion(self) -> str:
        return "615.71.09"

    def nvmlSystemGetCudaDriverVersion(self) -> int:
        return 13040

    def nvmlSystemGetNVMLVersion(self) -> str:
        return "13.615.71.09"

    def nvmlDeviceGetCount(self) -> int:
        return 1

    def nvmlDeviceGetHandleByIndex(self, i: int) -> int:
        return i

    def nvmlDeviceGetName(self, h) -> str:
        return "NVIDIA GeForce RTX 4070 SUPER"

    def nvmlDeviceGetMemoryInfo(self, h, version=None):
        total, reserved, used = 12282 * MIB, 348 * MIB, 2290 * MIB
        if version:
            return NS(total=total, reserved=reserved, used=used, free=total - used - reserved)
        return NS(total=total, used=used + reserved, free=total - used - reserved)

    def nvmlDeviceGetTemperatureThreshold(self, h, which: int) -> int:
        return {self.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN: 96, self.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN: 101}[which]

    def nvmlDeviceGetNumFans(self, h) -> int:
        return len(self.fan_speeds)

    def nvmlDeviceGetFanSpeed_v2(self, h, fan: int) -> int:
        return self.fan_speeds[fan]

    def nvmlDeviceGetComputeRunningProcesses(self, h):
        return self.compute

    def nvmlDeviceGetGraphicsRunningProcesses(self, h):
        return self.graphics

    def nvmlDeviceGetProcessUtilization(self, h, since: int):
        return [s for s in self.samples if s.timeStamp > since]


@pytest.fixture
def fake(monkeypatch) -> FakeNvml:
    fake = FakeNvml()
    monkeypatch.setattr(nvml, "N", fake)
    return fake


def test_system_info(fake):
    info = NvmlBackend().system_info()
    assert (info.driver_version, info.cuda_version) == ("615.71.09", "13.4")


def test_memory_used_excludes_reserved_like_nvidia_smi(fake):
    (snap,) = NvmlBackend().poll()
    assert snap.mem_total == 12282 * MIB
    assert snap.mem_used == 2290 * MIB  # not 2638: v1 would add the 348 MiB the driver reserves


@pytest.mark.parametrize("old", ["driver", "bindings"])
def test_memory_falls_back_to_v1(fake, monkeypatch, old):
    v1 = FakeNvml.nvmlDeviceGetMemoryInfo
    if old == "driver":  # library has no nvmlDeviceGetMemoryInfo_v2

        def meminfo(h, version=None):
            if version:
                raise NotSupported
            return v1(fake, h)
    else:  # nvidia-ml-py without the version argument

        def meminfo(h):
            return v1(fake, h)

        monkeypatch.delattr(FakeNvml, "nvmlMemory_v2")
    monkeypatch.setattr(fake, "nvmlDeviceGetMemoryInfo", meminfo, raising=False)
    (snap,) = NvmlBackend().poll()
    assert snap.mem_used == (2290 + 348) * MIB


def test_stopped_fans_are_zero_not_missing(fake):
    (snap,) = NvmlBackend().poll()
    assert snap.fans == [0.0, 0.0] and snap.fan == 0.0  # zero-RPM idle is not "passive"
    fake.fan_speeds = [30, 42]
    (snap,) = NvmlBackend().poll()
    assert snap.fans == [30.0, 42.0] and snap.fan == 36.0


def test_slowdown_and_shutdown_thresholds(fake):
    (snap,) = NvmlBackend().poll()
    assert (snap.temp_slowdown, snap.temp_shutdown) == (96, 101)


def test_unsupported_fields_are_none(fake):
    (snap,) = NvmlBackend().poll()
    assert snap.util_gpu is None and snap.power is None and snap.temp is None
    assert snap.clock_sm is None and snap.pstate is None and snap.bus_id == ""


def test_processes_merge_and_take_newest_utilisation_sample(fake):
    (snap,) = NvmlBackend().poll()
    procs = {p.pid: p for p in snap.processes}
    assert set(procs) == {2636, 75768, 1886}
    assert procs[2636].kind == "C+G" and procs[75768].kind == "C" and procs[1886].kind == "G"
    assert procs[1886].used_memory is None  # NVML_VALUE_NOT_AVAILABLE
    assert (procs[2636].sm_util, procs[2636].mem_util) == (7, 1)
    assert procs[75768].sm_util is None
