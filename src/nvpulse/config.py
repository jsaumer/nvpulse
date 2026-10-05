"""Optional settings file: ``~/.config/nvpulse/config.toml``.

Most of it can also be given on the command line, and the command line wins.
The file is only ever read. A file that someone else could have written is refused,
since it can switch off redaction or the read-only guard.
"""

from __future__ import annotations

import math
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 in CI
    import tomli as tomllib

MAX_BYTES = 64 * 1024
LAYOUTS = ("auto", "compact", "expanded")
SORTS = ("vram", "sm", "pid", "gpu", "unit")
THEMES = ("default", "high-contrast", "mono")
COLUMNS = ("gpu", "pid", "user", "type", "sm", "vram", "unit")  # the command column always shows


class ConfigError(Exception):
    """The file exists but can't be used; the message is safe to print."""


class ConfigUntrusted(ConfigError):
    """The file could have been written by someone else, so its contents weren't read."""


@dataclass
class Config:
    interval: float | None = None
    fps: float | None = None
    animate: bool | None = None
    layout: str | None = None
    sort: str | None = None
    theme: str | None = None
    hide_graphics: bool | None = None
    read_only: bool | None = None
    redact: bool | None = None
    hidden_columns: list[str] = field(default_factory=list)
    alert_temp: float | None = None
    alert_vram: float | None = None
    alert_bell: bool = True
    cost_per_kwh: float | None = None
    currency: str = "$"


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if os.path.isabs(base) else Path.home() / ".config"
    return root / "nvpulse" / "config.toml"


def _number(value: Any, key: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{key} must be a number")
    if not lo <= value <= hi:
        raise ConfigError(f"{key} must be between {lo:g} and {hi:g}")
    return float(value)


def _flag(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


def _choice(value: Any, key: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ConfigError(f"{key} must be one of: {', '.join(choices)}")
    return value


def parse(data: dict[str, Any]) -> Config:
    """Validate a decoded TOML document. Unknown keys are errors, so typos surface."""
    cfg = Config()
    data = dict(data)
    alerts = data.pop("alerts", {})
    energy = data.pop("energy", {})
    for name, table in (("alerts", alerts), ("energy", energy)):
        if not isinstance(table, dict):
            raise ConfigError(f"[{name}] must be a table")

    simple = {
        "interval": lambda v: _number(v, "interval", 0.1, 3600),
        "fps": lambda v: _number(v, "fps", 1, 60),
        "animate": lambda v: _flag(v, "animate"),
        "layout": lambda v: _choice(v, "layout", LAYOUTS),
        "sort": lambda v: _choice(v, "sort", SORTS),
        "theme": lambda v: _choice(v, "theme", THEMES),
        "hide_graphics": lambda v: _flag(v, "hide_graphics"),
        "read_only": lambda v: _flag(v, "read_only"),
        "redact": lambda v: _flag(v, "redact"),
    }
    for key, check in simple.items():
        if key in data:
            setattr(cfg, key, check(data.pop(key)))
    if "hidden_columns" in data:
        cols = data.pop("hidden_columns")
        if not isinstance(cols, list) or any(c not in COLUMNS for c in cols):
            raise ConfigError(f"hidden_columns must be a list of: {', '.join(COLUMNS)}")
        cfg.hidden_columns = list(dict.fromkeys(cols))

    if "temp" in alerts:
        cfg.alert_temp = _number(alerts.pop("temp"), "alerts.temp", 0, 150)
    if "vram" in alerts:
        cfg.alert_vram = _number(alerts.pop("vram"), "alerts.vram", 0, 100)
    if "bell" in alerts:
        cfg.alert_bell = _flag(alerts.pop("bell"), "alerts.bell")
    if "cost_per_kwh" in energy:
        cfg.cost_per_kwh = _number(energy.pop("cost_per_kwh"), "energy.cost_per_kwh", 0, 1000)
    if "currency" in energy:
        cur = energy.pop("currency")
        if not isinstance(cur, str) or not 1 <= len(cur) <= 4 or not cur.isprintable():
            raise ConfigError("energy.currency must be 1 to 4 printable characters")
        cfg.currency = cur

    unknown = [*data, *(f"alerts.{k}" for k in alerts), *(f"energy.{k}" for k in energy)]
    if unknown:
        # repr(): key names come from the file and get printed to the terminal
        raise ConfigError("unknown setting(s): " + ", ".join(repr(str(k))[:40] for k in unknown[:8]))
    return cfg


def _trusted(st: os.stat_result) -> bool:
    """A regular file that is ours (or root's) and that nobody else can write.

    Group-writable counts as "somebody else": a group is other people.
    """
    uid = os.geteuid() if hasattr(os, "geteuid") else st.st_uid
    writable_by_others = st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    return stat.S_ISREG(st.st_mode) and st.st_uid in (uid, 0) and not writable_by_others


def load(path: str | os.PathLike[str] | None = None) -> Config:
    """Read the settings file. A missing default file is fine; a named one must exist."""
    explicit = path is not None
    target = Path(path) if explicit else default_path()
    try:
        with open(target, "rb") as fh:
            if not _trusted(os.fstat(fh.fileno())):
                raise ConfigUntrusted(
                    f"refusing {target}: it must be a regular file owned by you that no one else can write (chmod go-w)"
                )
            raw = fh.read(MAX_BYTES + 1)
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"{target}: no such file") from None
        return Config()
    except OSError as exc:
        raise ConfigError(f"{target}: {exc.strerror}") from None
    if len(raw) > MAX_BYTES:
        raise ConfigError(f"{target}: larger than {MAX_BYTES // 1024} KiB")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{target}: not valid TOML ({str(exc)[:120]})") from None
    try:
        return parse(data)
    except ConfigError as exc:
        raise ConfigError(f"{target}: {exc}") from None
