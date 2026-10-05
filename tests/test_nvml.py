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
    """Just enough of pynvml for NvmlBackend.

    A call the fake doesn't define raises NotSupported, like a driver that rejects
    it. Names in ``missing`` raise AttributeError instead, like bindings too old to
    have them: that happens on attribute lookup, before any ``try`` around the call.
    """

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

    missing: frozenset[str] = frozenset()

    def __getattribute__(self, name: str):
        if name in type(self).missing:
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str):
        if name in type(self).missing or not name.startswith("nvml"):
            raise AttributeError(name)

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
        return {
            self.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN: 96,
            self.NVML_TEMPERATURE_THRESHOLD_SHUTDOWN: 101,
            self.NVML_TEMPERATURE_THRESHOLD_GPU_MAX: 90,
            self.NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR: 84,
        }[which]

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

    # ---- v0.2: clock reasons, PCIe link, detail view
    NVML_TEMPERATURE_THRESHOLD_GPU_MAX = 3
    NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR = 5
    NVML_CLOCK_VIDEO = 3
    NVML_PCIE_UTIL_TX_BYTES = 0
    NVML_PCIE_UTIL_RX_BYTES = 1
    NVML_MEMORY_ERROR_TYPE_CORRECTED = 0
    NVML_MEMORY_ERROR_TYPE_UNCORRECTED = 1
    NVML_AGGREGATE_ECC = 1
    reasons = 0x4  # what the card reports at idle: "software power cap"

    def nvmlDeviceGetCurrentClocksEventReasons(self, h) -> int:
        return self.reasons

    def nvmlDeviceGetUUID(self, h) -> str:
        return "GPU-9d06d26f-4b35-dc7b-3fd7-4ef30ba3b554"

    def nvmlDeviceGetPciInfo(self, h):
        return NS(busId="00000000:2D:00.0")

    def nvmlDeviceGetCurrPcieLinkGeneration(self, h) -> int:
        return 1  # drops from 4 at idle

    def nvmlDeviceGetCurrPcieLinkWidth(self, h) -> int:
        return 16

    def nvmlDeviceGetMaxPcieLinkGeneration(self, h) -> int:
        return 4

    def nvmlDeviceGetGpuMaxPcieLinkGeneration(self, h) -> int:
        return 4

    def nvmlDeviceGetMaxPcieLinkWidth(self, h) -> int:
        return 16

    def nvmlDeviceGetVbiosVersion(self, h) -> str:
        return "95.04.69.00.90"

    def nvmlDeviceGetFanSpeedRPM(self, h) -> int:  # these bindings take no fan index
        return 0

    def nvmlDeviceGetTargetFanSpeed(self, h, fan: int) -> int:
        return 30

    def nvmlDeviceGetTotalEnergyConsumption(self, h) -> int:
        return 1_775_044_608  # mJ

    def nvmlDeviceGetPowerManagementDefaultLimit(self, h) -> int:
        return 220_000  # mW

    def nvmlDeviceGetClockInfo(self, h, which: int) -> int:
        return {self.NVML_CLOCK_VIDEO: 1185}[which]

    def nvmlDeviceGetMaxClockInfo(self, h, which: int) -> int:
        return {self.NVML_CLOCK_VIDEO: 2415}[which]

    def nvmlDeviceGetPcieThroughput(self, h, counter: int) -> int:
        return (1513, 7031)[counter]

    def nvmlDeviceGetPcieReplayCounter(self, h) -> int:
        return 0


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

        monkeypatch.setattr(FakeNvml, "missing", frozenset({"nvmlMemory_v2"}))
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
    assert snap.clock_sm is None and snap.pstate is None and snap.persistence is None


def test_processes_merge_and_take_newest_utilisation_sample(fake):
    (snap,) = NvmlBackend().poll()
    procs = {p.pid: p for p in snap.processes}
    assert set(procs) == {2636, 75768, 1886}
    assert procs[2636].kind == "C+G" and procs[75768].kind == "C" and procs[1886].kind == "G"
    assert procs[1886].used_memory is None  # NVML_VALUE_NOT_AVAILABLE
    assert (procs[2636].sm_util, procs[2636].mem_util) == (7, 1)
    assert procs[75768].sm_util is None


# ------------------------------------------------------------------- v0.2
def test_idle_power_cap_is_not_a_throttle_badge(fake):
    (snap,) = NvmlBackend().poll()
    assert snap.clock_reasons == 0x4
    assert snap.clock_reason_names == ["software power cap"]
    assert snap.throttle_badges == []  # a healthy idle desktop card reports this all day
    fake.reasons = 0x1
    assert NvmlBackend().poll()[0].throttle_badges == []  # idle


def test_real_throttles_get_badges(fake):
    fake.reasons = 0x20 | 0x40 | 0x08 | 0x01
    (snap,) = NvmlBackend().poll()
    assert snap.throttle_badges == ["THERMAL", "HW SLOWDOWN"]  # both thermal bits share one badge
    assert "idle" in snap.clock_reason_names


def test_clock_reasons_fall_back_to_the_old_call_name(fake, monkeypatch):
    new, old = "nvmlDeviceGetCurrentClocksEventReasons", "nvmlDeviceGetCurrentClocksThrottleReasons"
    monkeypatch.setattr(FakeNvml, "missing", frozenset({new}))  # older bindings: the name doesn't exist
    monkeypatch.setattr(fake, old, lambda h: 0x40, raising=False)
    assert NvmlBackend().poll()[0].throttle_badges == ["THERMAL"]
    monkeypatch.setattr(FakeNvml, "missing", frozenset({new, old}))
    (snap,) = NvmlBackend().poll()
    assert snap.clock_reasons is None and snap.clock_reason_names is None and snap.throttle_badges == []


def test_idle_link_speed_drop_is_not_a_downgrade(fake):
    (snap,) = NvmlBackend().poll()
    assert (snap.pcie_gen, snap.pcie_gen_max, snap.pcie_width_max) == (1, 4, 16)
    assert snap.pcie_downgrade is None  # Gen 1 at idle is power saving, not a fault


@pytest.mark.parametrize(
    "patch, expected",
    [
        ({"nvmlDeviceGetCurrPcieLinkWidth": 8}, "4.0 x16"),  # x16 card negotiated x8
        ({"nvmlDeviceGetMaxPcieLinkGeneration": 3}, "4.0 x16"),  # Gen 4 card in a Gen 3 slot
        ({"nvmlDeviceGetMaxPcieLinkWidth": None}, None),  # unknown maximum: say nothing
    ],
)
def test_pcie_downgrade(fake, monkeypatch, patch, expected):
    for name, value in patch.items():
        if value is None:
            monkeypatch.delattr(FakeNvml, name)
        else:
            monkeypatch.setattr(fake, name, lambda h, v=value: v, raising=False)
    assert NvmlBackend().poll()[0].pcie_downgrade == expected


def test_identify(fake):
    assert NvmlBackend().identify() == [(0, "GPU-9d06d26f-4b35-dc7b-3fd7-4ef30ba3b554", "00000000:2D:00.0")]


def test_detail(fake):
    d = NvmlBackend().detail(0)
    assert d.vbios == "95.04.69.00.90"
    assert d.fan_rpm == [0] and d.fan_target == [30.0, 30.0]  # RPM for the first fan only on these bindings
    assert (d.temp_target, d.temp_max_operating) == (84, 90)
    assert d.power_default_limit == 220.0
    assert d.energy == pytest.approx(1_775_044.608)
    assert (d.clock_video, d.clock_video_max) == (1185, 2415)
    assert (d.pcie_tx, d.pcie_rx, d.pcie_replay) == (1513, 7031, 0)
    assert d.ecc_corrected is None and d.ecc_uncorrected is None  # consumer card: no ECC
    assert NvmlBackend().detail(3) is None


def test_detail_with_per_fan_rpm_bindings(fake, monkeypatch):
    monkeypatch.setattr(fake, "nvmlDeviceGetFanSpeedRPM", lambda h, fan: (900, 1100)[fan], raising=False)
    assert NvmlBackend().detail(0).fan_rpm == [900, 1100]


def test_detail_survives_a_card_that_supports_none_of_it(monkeypatch):
    bare = FakeNvml()
    keep = {"nvmlDeviceGetCount", "nvmlDeviceGetHandleByIndex"}
    for name in [n for n in vars(FakeNvml) if n.startswith("nvmlDeviceGet") and n not in keep]:
        monkeypatch.delattr(FakeNvml, name)
    monkeypatch.setattr(nvml, "N", bare)
    d = NvmlBackend().detail(0)
    assert d.vbios == "" and d.fan_rpm == [] and d.energy is None and d.pcie_tx is None


V02_NAMES = frozenset(
    {
        # nvmlDeviceGetFanSpeedRPM really is absent from nvidia-ml-py 12.535, our floor
        "nvmlDeviceGetFanSpeedRPM",
        "nvmlDeviceGetTargetFanSpeed",
        "nvmlDeviceGetTotalEnergyConsumption",
        "nvmlDeviceGetPowerManagementDefaultLimit",
        "nvmlDeviceGetVbiosVersion",
        "nvmlDeviceGetPcieThroughput",
        "nvmlDeviceGetPcieReplayCounter",
        "nvmlDeviceGetTotalEccErrors",
        "nvmlDeviceGetMaxPcieLinkGeneration",
        "nvmlDeviceGetGpuMaxPcieLinkGeneration",
        "nvmlDeviceGetMaxPcieLinkWidth",
        "nvmlDeviceGetCurrentClocksEventReasons",
        "nvmlDeviceGetCurrentClocksThrottleReasons",
        "NVML_TEMPERATURE_THRESHOLD_GPU_MAX",
        "NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR",
        "NVML_CLOCK_VIDEO",
        "NVML_PCIE_UTIL_TX_BYTES",
        "NVML_PCIE_UTIL_RX_BYTES",
        "NVML_MEMORY_ERROR_TYPE_CORRECTED",
        "NVML_MEMORY_ERROR_TYPE_UNCORRECTED",
        "NVML_AGGREGATE_ECC",
    }
)


@pytest.mark.parametrize("gone", [frozenset({"nvmlDeviceGetFanSpeedRPM"}), V02_NAMES])
def test_old_bindings_without_the_newer_calls(fake, monkeypatch, gone):
    """Names missing from the module raise on lookup, outside ``_safe``: must not escape."""
    monkeypatch.setattr(FakeNvml, "missing", gone)
    with pytest.raises(AttributeError):
        fake.nvmlDeviceGetFanSpeedRPM  # noqa: B018 - the fake behaves like the real module
    backend = NvmlBackend()
    (snap,) = backend.poll()
    d = backend.detail(0)
    assert d.fan_rpm == []
    if gone is V02_NAMES:
        assert snap.clock_reasons is None and snap.pcie_gen_max is None and snap.pcie_downgrade is None
        assert d.vbios == "" and d.energy is None and d.pcie_tx is None and d.temp_target is None
        assert d.clock_video is None and d.ecc_corrected is None and d.fan_target == [None, None]
    else:
        assert d.vbios == "95.04.69.00.90" and d.fan_target == [30.0, 30.0]


def test_fan_targets_stay_aligned_with_fan_numbers(fake, monkeypatch):
    def target(h, fan):
        if fan == 0:
            raise NotSupported
        return 45

    monkeypatch.setattr(fake, "nvmlDeviceGetTargetFanSpeed", target, raising=False)
    assert NvmlBackend().detail(0).fan_target == [None, 45.0]
