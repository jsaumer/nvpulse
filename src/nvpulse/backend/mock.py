"""Synthetic GPUs for demos, screenshots and tests (no NVIDIA hardware needed)."""

from __future__ import annotations

import math
import random
import socket
import time
from dataclasses import dataclass, field

from .models import Backend, GpuDetail, GpuSnapshot, ProcessInfo, SystemInfo

GiB = 1024**3

# name, VRAM GiB, power limit W, idle W, fan count (0 = passive), slowdown °C
PROFILES = [
    ("NVIDIA GeForce RTX 4090", 24, 450, 22, 2, 88),
    ("NVIDIA A100-SXM4-80GB", 80, 400, 55, 0, 85),
    ("NVIDIA GeForce RTX 3090", 24, 350, 28, 2, 90),
    ("NVIDIA L40S", 48, 350, 35, 0, 87),
    ("NVIDIA GeForce RTX 4070 Ti SUPER", 16, 285, 12, 2, 90),
    ("NVIDIA RTX A6000", 48, 300, 25, 1, 88),
    ("NVIDIA H100 80GB HBM3", 80, 700, 70, 0, 85),
    ("NVIDIA GeForce RTX 3060", 12, 170, 10, 2, 93),
]

PROC_POOL = [
    ("python3", "python3 train.py --model llama-8b --bf16", "C", 9.5),
    ("ollama", "/usr/local/bin/ollama runner --model qwen2.5:14b", "C", 11.0),
    ("Xorg", "/usr/lib/xorg/Xorg vt2 -displayfd 3", "G", 0.4),
    ("gnome-shell", "/usr/bin/gnome-shell", "G", 0.3),
    ("ffmpeg", "ffmpeg -hwaccel cuda -i in.mkv -c:v hevc_nvenc out.mkv", "C", 0.8),
    ("Tdarr_Node", "/app/Tdarr_Node/Tdarr_Node", "C", 1.2),
    ("blender", "blender -b scene.blend -E CYCLES -a", "C+G", 6.0),
    ("jupyter", "python -m ipykernel_launcher -f kernel-42.json", "C", 3.5),
    ("comfyui", "python main.py --listen 0.0.0.0", "C", 7.8),
    ("vllm", "python -m vllm.entrypoints.openai.api_server", "C", 18.0),
]
USERS = ["saumz", "root", "jellyfin", "ollama"]


@dataclass
class _Proc:
    pid: int
    name: str
    cmd: str
    kind: str
    mem_gib: float
    user: str
    born: float
    ttl: float


@dataclass
class _Gpu:
    index: int
    profile: tuple
    phase: float
    speed: float
    temp: float = 38.0
    fan: float = 30.0
    procs: list[_Proc] = field(default_factory=list)


def _uuid(index: int) -> str:
    return f"GPU-6d6f636b-0000-4000-8000-{index:012x}"  # "mock" in hex, so it parses like a real UUID


def _bus_id(index: int) -> str:
    return f"00000000:{0x01 + index * 0x20:02X}:00.0"


class MockBackend(Backend):
    def __init__(self, count: int = 1, seed: int | None = None, clock=time.monotonic) -> None:
        self._rng = random.Random(seed)
        self._clock = clock
        self._t0 = clock()
        self._next_pid = 2400
        self._gpus = [
            _Gpu(
                index=i,
                profile=PROFILES[i % len(PROFILES)],
                phase=self._rng.uniform(0, math.tau),
                speed=self._rng.uniform(0.08, 0.25),
            )
            for i in range(max(1, count))
        ]
        for g in self._gpus:
            for _ in range(self._rng.randint(1, 3)):
                if sum(p.mem_gib for p in g.procs) < g.profile[1] * 0.6:
                    self._spawn(g)

    def _spawn(self, g: _Gpu) -> None:
        # only workloads that fit: a 24 GiB card shouldn't open on a 23 GiB process
        room = g.profile[1] * 0.85 - sum(p.mem_gib for p in g.procs)
        fits = [p for p in PROC_POOL if p[3] * 1.3 <= room]
        if not fits:
            return
        name, cmd, kind, mem = self._rng.choice(fits)
        self._next_pid += self._rng.randint(3, 900)
        g.procs.append(
            _Proc(
                pid=self._next_pid,
                name=name,
                cmd=cmd,
                kind=kind,
                mem_gib=mem * self._rng.uniform(0.6, 1.3),
                user=self._rng.choice(USERS),
                born=self._clock(),
                ttl=self._rng.uniform(20, 120),
            )
        )

    def kill(self, gpu_index: int, pid: int) -> bool:
        for g in self._gpus:
            if g.index == gpu_index:
                before = len(g.procs)
                g.procs = [p for p in g.procs if p.pid != pid]
                return len(g.procs) != before
        return False

    def system_info(self) -> SystemInfo:
        return SystemInfo(
            driver_version="560.35.03 (mock)",
            cuda_version="12.6",
            nvml_version="12.560.35.03",
            hostname=socket.gethostname(),
        )

    def device_count(self) -> int:
        return len(self._gpus)

    def identify(self) -> list[tuple[int, str, str]]:
        return [(g.index, _uuid(g.index), _bus_id(g.index)) for g in self._gpus]

    def detail(self, index: int) -> GpuDetail | None:
        g = next((g for g in self._gpus if g.index == index), None)
        if g is None:
            return None
        _name, _vram, plimit, idle, nfans, slowdown = g.profile
        t = self._clock() - self._t0
        busy = max(0.0, g.temp - 38) / 50
        return GpuDetail(
            index=index,
            vbios=f"95.02.{0x3C + index:02X}.00.{0x90 + index:02X}",
            fan_rpm=[int(g.fan * 32) for _ in range(nfans)],
            fan_target=[round(g.fan) for _ in range(nfans)],
            temp_target=slowdown - 6.0,
            temp_max_operating=slowdown - 1.0,
            power_default_limit=float(plimit),
            energy=(86_400 + t) * (idle + (plimit - idle) * 0.3),
            clock_video=int(1185 + busy * 765),
            clock_video_max=1950,
            pcie_tx=int(self._rng.uniform(200, 900) + busy * 180_000),
            pcie_rx=int(self._rng.uniform(400, 2_000) + busy * 420_000),
            pcie_replay=0,
            ecc_corrected=None if nfans else 0,  # consumer cards have no ECC
            ecc_uncorrected=None if nfans else 0,
        )

    def poll(self, indices: list[int] | None = None) -> list[GpuSnapshot]:
        now = self._clock()
        t = now - self._t0
        out = []
        for g in self._gpus:
            if indices is not None and g.index not in indices:
                continue
            name, vram, plimit, idle, nfans, slowdown = g.profile

            # process churn
            g.procs = [p for p in g.procs if now - p.born < p.ttl]
            mem_now = sum(p.mem_gib for p in g.procs)
            if len(g.procs) < 4 and mem_now < vram * 0.6 and self._rng.random() < 0.06:
                self._spawn(g)
            if not g.procs and self._rng.random() < 0.3:
                self._spawn(g)

            compute = [p for p in g.procs if "C" in p.kind]
            base = 50 + 45 * math.sin(t * g.speed + g.phase) * math.sin(t * g.speed * 0.37 + 1)
            burst = 25 if self._rng.random() < 0.08 else 0
            util = 0.0 if not compute else max(0.0, min(100.0, base + burst + self._rng.gauss(0, 4)))

            # thermals lag utilisation, fans chase temperature
            target_t = 34 + util * 0.52
            g.temp += (target_t - g.temp) * 0.15
            target_f = 0 if (nfans and g.temp < 45) else 30 + max(0.0, g.temp - 45) * 2.0
            g.fan += (min(100.0, target_f) - g.fan) * 0.2

            used = sum(p.mem_gib for p in g.procs) * GiB + 0.35 * GiB
            used = min(used, vram * GiB * 0.98)
            power = idle + (plimit - idle) * (util / 100) ** 1.2 * self._rng.uniform(0.92, 1.0)

            procs = [
                ProcessInfo(
                    gpu_index=g.index,
                    pid=p.pid,
                    kind=p.kind,
                    used_memory=int(p.mem_gib * GiB),
                    sm_util=int(util * self._rng.uniform(0.2, 1.0)) if "C" in p.kind else None,
                    mem_util=int(util * 0.4 * self._rng.uniform(0.3, 1.0)) if "C" in p.kind else None,
                    name=p.name,
                    user=p.user,
                    cmdline=p.cmd,
                )
                for p in g.procs
            ]
            fans = [max(0.0, round(g.fan + self._rng.uniform(-1, 1), 0)) if g.fan >= 1 else 0.0 for _ in range(nfans)]
            reasons = 0x001 if util < 2 else (0x004 if util > 92 else 0)
            if g.temp >= slowdown - 2:
                reasons |= 0x020
            out.append(
                GpuSnapshot(
                    index=g.index,
                    name=name,
                    uuid=_uuid(g.index),
                    bus_id=_bus_id(g.index),
                    util_gpu=round(util),
                    util_mem=round(util * 0.45),
                    mem_total=vram * GiB,
                    mem_used=int(used),
                    temp=round(g.temp),
                    temp_slowdown=slowdown,
                    temp_shutdown=slowdown + 8,
                    fan=(sum(fans) / len(fans)) if fans else None,
                    fans=fans,
                    power=round(power, 1),
                    power_limit=float(plimit),
                    clock_sm=int(210 + util / 100 * 2310),
                    clock_mem=10501 if util > 5 else 405,
                    clock_sm_max=2520,
                    clock_mem_max=10501,
                    pstate=2 if util > 10 else 8,
                    enc_util=float(self._rng.choice([0, 0, 0, 12, 34])),
                    dec_util=float(self._rng.choice([0, 0, 8, 21])),
                    pcie_gen=4 if util > 5 else 1,
                    pcie_width=8 if g.index % len(PROFILES) == 5 else 16,  # one card in a narrow slot
                    pcie_gen_max=4,
                    pcie_gen_device_max=4,
                    pcie_width_max=16,
                    persistence=True,
                    clock_reasons=reasons,
                    processes=procs,
                )
            )
        return out
