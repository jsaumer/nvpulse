"""Plain data containers passed from a backend to the UI."""

from __future__ import annotations

from dataclasses import dataclass, field

# Bits of NVML's "clocks event reasons" mask (formerly "throttle reasons"), copied
# here so the UI and the mock don't need pynvml: (bit, card badge, description).
# Only reasons that mean the GPU is being held back by a problem get a badge. The
# rest share the mask but are routine: "idle", user and display clock settings, and
# the software power cap, which a healthy desktop card reports all day at 11 W.
CLOCK_REASONS: tuple[tuple[int, str, str], ...] = (
    (0x040, "THERMAL", "hardware thermal slowdown"),
    (0x020, "THERMAL", "software thermal slowdown"),
    (0x008, "HW SLOWDOWN", "hardware slowdown"),
    (0x080, "POWER BRAKE", "external power brake"),
    (0x004, "", "software power cap"),
    (0x200, "", "board limit"),
    (0x400, "", "reliability limit"),
    (0x010, "", "sync boost"),
    (0x002, "", "application clock setting"),
    (0x100, "", "display clock setting"),
    (0x001, "", "idle"),
)


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
    started: float | None = None  # process create time (epoch s), used to detect PID reuse
    unit: str = ""  # container ("docker:3f2a9c1b2d4e") or systemd service that owns the process


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
    enc_sessions: int | None = None  # active NVENC sessions
    enc_fps: int | None = None  # their average frame rate
    pcie_gen: int | None = None
    pcie_width: int | None = None
    pcie_gen_max: int | None = None  # best this GPU can do in this slot
    pcie_gen_device_max: int | None = None  # best the GPU itself supports
    pcie_width_max: int | None = None
    persistence: bool | None = None
    clock_reasons: int | None = None  # CLOCK_REASONS bitmask

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

    @property
    def throttle_badges(self) -> list[str]:
        """Short labels for the active reasons that point at a problem."""
        mask = self.clock_reasons or 0
        out: list[str] = []
        for bit, badge, _desc in CLOCK_REASONS:
            if badge and mask & bit and badge not in out:
                out.append(badge)
        return out

    @property
    def clock_reason_names(self) -> list[str] | None:
        """Every active reason, including the harmless ones. None when not reported."""
        if self.clock_reasons is None:
            return None
        return [desc for bit, _badge, desc in CLOCK_REASONS if self.clock_reasons & bit]

    @property
    def pcie_downgrade(self) -> str | None:
        """What the link should be when it runs below what the card supports, else None.

        Only static facts are compared. The current *generation* is ignored on
        purpose: drivers drop it at idle to save power, which is not a fault.
        """
        narrow = self.pcie_width and self.pcie_width_max and self.pcie_width < self.pcie_width_max
        slow = self.pcie_gen_max and self.pcie_gen_device_max and self.pcie_gen_max < self.pcie_gen_device_max
        if not (narrow or slow):
            return None
        gen = self.pcie_gen_device_max or self.pcie_gen_max
        width = self.pcie_width_max or self.pcie_width
        return " ".join(b for b in (f"{gen}.0" if gen else "", f"x{width}" if width else "") if b)


@dataclass(slots=True)
class Alerts:
    """User-configured limits. None means "don't watch this"."""

    temp: float | None = None  # °C
    vram: float | None = None  # percent of total
    bell: bool = True

    def active(self, s: GpuSnapshot) -> list[str]:
        """Badge labels for the limits this snapshot has reached."""
        out = []
        if self.temp is not None and s.temp is not None and s.temp >= self.temp:
            out.append("HOT")
        if self.vram is not None and s.mem_pct is not None and s.mem_pct >= self.vram:
            out.append("VRAM")
        return out


@dataclass(slots=True)
class GpuDetail:
    """Slower or rarely needed readings, fetched only while the detail view is open."""

    index: int
    vbios: str = ""
    fan_rpm: list[int] = field(default_factory=list)
    fan_target: list[float | None] = field(default_factory=list)  # percent, one entry per fan
    temp_target: float | None = None  # °C the fan curve aims for
    temp_max_operating: float | None = None
    power_default_limit: float | None = None  # watts
    energy: float | None = None  # joules since the driver loaded
    clock_video: int | None = None  # MHz
    clock_video_max: int | None = None
    pcie_tx: int | None = None  # KB/s
    pcie_rx: int | None = None
    pcie_replay: int | None = None  # link-level retransmissions
    ecc_corrected: int | None = None  # lifetime counts; None without ECC memory
    ecc_uncorrected: int | None = None


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

    def detail(self, index: int) -> GpuDetail | None:
        """Extra readings for one GPU. May be slow; never called on the UI thread."""
        return None

    def identify(self) -> list[tuple[int, str, str]]:
        """(index, UUID, PCI bus ID) of every GPU, for resolving ``-i`` selectors."""
        return [(s.index, s.uuid, s.bus_id) for s in self.poll()]

    def close(self) -> None:
        pass
