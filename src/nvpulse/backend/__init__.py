from .models import Backend, GpuDetail, GpuSnapshot, ProcessInfo, SystemInfo

__all__ = ["Backend", "GpuDetail", "GpuSnapshot", "ProcessInfo", "SystemInfo", "make_backend"]


def make_backend(mock: int | None = None, seed: int | None = None) -> Backend:
    """Return a mock backend when asked, otherwise NVML (raises NvmlUnavailable)."""
    if mock:
        from .mock import MockBackend

        return MockBackend(count=mock, seed=seed)
    from .nvml import NvmlBackend

    return NvmlBackend()
