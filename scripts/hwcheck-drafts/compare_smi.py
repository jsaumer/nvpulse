"""Print what nvpulse reads next to what nvidia-smi reports, for every GPU."""

from __future__ import annotations

import dataclasses
import subprocess

from nvpulse.backend.nvml import NvmlBackend

MIB = 1 << 20
QUERY = (
    "index,name,pci.bus_id,utilization.gpu,utilization.memory,memory.total,memory.used,temperature.gpu,"
    "fan.speed,power.draw,enforced.power.limit,clocks.sm,clocks.mem,clocks.max.sm,clocks.max.mem,pstate,"
    "pcie.link.gen.current,pcie.link.width.current,persistence_mode,utilization.encoder,utilization.decoder"
)


def smi(*args: str) -> str:
    return subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, check=False).stdout


def main() -> None:
    backend = NvmlBackend()
    print("nvpulse system:", backend.system_info(), "| GPUs:", backend.device_count())
    backend.poll()  # the first poll primes NVML's per-process utilisation buffer
    snaps = backend.poll()
    rows = [line.split(", ") for line in smi(f"--query-gpu={QUERY}", "--format=csv,noheader").splitlines()]
    for snap, row in zip(snaps, rows, strict=False):
        mine = dataclasses.asdict(snap)
        procs = mine.pop("processes")
        print(f"\n=== GPU {snap.index}")
        for key, value in mine.items():
            if key in ("mem_total", "mem_used") and value is not None:
                value = f"{value / MIB:.0f} MiB"
            print(f"  nvpulse {key:<20} {value}")
        print("  nvidia-smi", dict(zip(QUERY.split(","), row, strict=False)))
        print(f"  nvpulse lists {len(procs)} processes")
        print(f"  clock reasons: {snap.clock_reason_names}; badges: {snap.throttle_badges}")
        print("  detail:", backend.detail(snap.index))
    listed = [line for line in smi("pmon", "-c", "1").splitlines() if line and not line.startswith("#")]
    print(f"\nnvidia-smi pmon lists {len(listed)} processes in total")
    print(smi("-q", "-d", "TEMPERATURE").split("Temperature", 1)[-1][:420])
    backend.close()


if __name__ == "__main__":
    main()
