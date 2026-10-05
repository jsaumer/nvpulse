"""Settings file: parsing, validation, trust check, and how the CLI layers it."""

from __future__ import annotations

import os

import pytest

from nvpulse import cli, config
from nvpulse.config import Config, ConfigError

GOOD = """
interval = 0.5
fps = 30
animate = false
layout = "compact"
sort = "unit"
theme = "high-contrast"
hide_graphics = true
read_only = true
redact = false
hidden_columns = ["user", "sm", "user"]

[alerts]
temp = 85
vram = 95.5
bell = false

[energy]
cost_per_kwh = 0.31
currency = "€"
"""


def write(tmp_path, text, mode=0o600):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_load_reads_every_setting(tmp_path):
    cfg = config.load(write(tmp_path, GOOD))
    assert (cfg.interval, cfg.fps, cfg.animate, cfg.layout, cfg.sort) == (0.5, 30.0, False, "compact", "unit")
    assert (cfg.theme, cfg.hide_graphics, cfg.read_only, cfg.redact) == ("high-contrast", True, True, False)
    assert cfg.hidden_columns == ["user", "sm"]  # duplicates dropped, order kept
    assert (cfg.alert_temp, cfg.alert_vram, cfg.alert_bell) == (85.0, 95.5, False)
    assert (cfg.cost_per_kwh, cfg.currency) == (0.31, "€")


@pytest.mark.parametrize(
    "text, message",
    [
        ("intervl = 2", "unknown setting"),
        ("[alerts]\ntemperature = 80", "alerts.temperature"),
        ('fps = "fast"', "fps must be a number"),
        ("interval = true", "interval must be a number"),
        ("interval = 0", "between"),
        ("interval = nan", "interval must be a number"),
        ("fps = inf", "fps must be a number"),
        ('theme = "neon"', "theme must be one of"),
        ('sort = "name"', "sort must be one of"),
        ('layout = "wide"', "layout must be one of"),
        ('animate = "yes"', "true or false"),
        ("alerts = 3", "[alerts] must be a table"),
        ("[alerts]\ntemp = 500", "between"),
        ("[alerts]\nvram = 101", "between"),
        ('hidden_columns = ["cmd"]', "hidden_columns"),
        ('hidden_columns = "user"', "hidden_columns"),
        ('[energy]\ncurrency = ""', "currency"),
        ('[energy]\ncurrency = "dollars"', "currency"),
        ("this is not toml", "not valid TOML"),
    ],
)
def test_bad_settings_are_named(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[")):
        config.load(write(tmp_path, text))


def test_missing_default_file_is_fine_but_a_named_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.default_path() == tmp_path / "nvpulse" / "config.toml"
    assert config.load() == Config()
    with pytest.raises(ConfigError, match="no such file"):
        config.load(tmp_path / "nope.toml")


def test_relative_xdg_config_home_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/dir")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.default_path() == tmp_path / ".config" / "nvpulse" / "config.toml"


def test_oversized_and_non_utf8_files(tmp_path):
    with pytest.raises(ConfigError, match="larger than"):
        config.load(write(tmp_path, "# " + "x" * (config.MAX_BYTES + 10)))
    path = tmp_path / "latin.toml"
    path.write_bytes(b'theme = "\xff"')
    path.chmod(0o600)
    with pytest.raises(ConfigError, match="not valid TOML"):
        config.load(path)


# ------------------------------------------------------------------ CLI layering
class FakeApp:
    seen: dict = {}

    def __init__(self, backend, **kw):
        FakeApp.seen = kw
        self.return_code = 0

    def run(self):
        pass


@pytest.fixture
def run_cli(monkeypatch, tmp_path):
    from nvpulse.ui import app as app_module
    from nvpulse.ui import render

    monkeypatch.setattr(app_module, "NvPulse", FakeApp)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.delenv("NVPULSE_CONFIG", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)

    def run(*argv):
        code = cli.main(["--mock", "1", *argv])
        return code, FakeApp.seen

    yield run
    render.set_theme("default")
    os.environ.pop("NO_COLOR", None)


def test_defaults_without_a_file(run_cli):
    code, kw = run_cli()
    assert code == 0
    assert (kw["interval"], kw["fps"], kw["animate"], kw["compact"], kw["redact"]) == (1.0, 20.0, True, None, True)
    assert (kw["read_only"], kw["hide_graphics"], kw["sort"], kw["theme"]) == (False, False, "vram", "default")
    assert kw["alerts"].temp is None and kw["cost_per_kwh"] is None


def test_file_sets_defaults_and_flags_win(run_cli, tmp_path):
    path = write(tmp_path, GOOD)
    _, kw = run_cli("--config", str(path))
    assert (kw["interval"], kw["fps"], kw["animate"], kw["compact"]) == (0.5, 30.0, False, True)
    assert (kw["redact"], kw["read_only"], kw["hide_graphics"], kw["sort"]) == (False, True, True, "unit")
    assert kw["theme"] == "high-contrast" and kw["hidden_columns"] == ["user", "sm"]
    assert (kw["alerts"].temp, kw["alerts"].bell, kw["cost_per_kwh"], kw["currency"]) == (85.0, False, 0.31, "€")

    _, kw = run_cli("--config", str(path), "-n", "2", "--fps", "5", "--expanded", "--theme", "default")
    assert (kw["interval"], kw["fps"], kw["compact"], kw["theme"]) == (2.0, 5.0, False, "default")


def test_env_var_names_the_file_and_no_config_skips_it(run_cli, tmp_path, monkeypatch):
    monkeypatch.setenv("NVPULSE_CONFIG", str(write(tmp_path, "interval = 5")))
    assert run_cli()[1]["interval"] == 5.0
    assert run_cli("--no-config")[1]["interval"] == 1.0


def test_broken_file_stops_the_dashboard_with_a_message(run_cli, tmp_path, capsys):
    code, _ = run_cli("--config", str(write(tmp_path, "intervl = 1")))
    assert code == 2
    assert "unknown setting" in capsys.readouterr().err


def test_no_color_selects_mono_unless_a_colour_theme_is_asked_for(run_cli, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert run_cli()[1]["theme"] == "mono" and os.environ.get("NO_COLOR") == "1"
    monkeypatch.setenv("NO_COLOR", "1")
    assert run_cli("--theme", "high-contrast")[1]["theme"] == "high-contrast"
    assert "NO_COLOR" not in os.environ  # or Textual would grey out the theme just asked for
    assert run_cli("--theme", "mono")[1]["theme"] == "mono" and os.environ.get("NO_COLOR") == "1"


def test_every_switch_in_the_file_can_be_undone_by_a_flag(run_cli, tmp_path):
    path = str(write(tmp_path, "animate = false\nread_only = true\nhide_graphics = true\nredact = false\n"))
    _, kw = run_cli("--config", path)
    assert (kw["animate"], kw["read_only"], kw["hide_graphics"], kw["redact"]) == (False, True, True, False)
    _, kw = run_cli("--config", path, "--anim", "--no-read-only", "--no-hide-graphics", "--redact")
    assert (kw["animate"], kw["read_only"], kw["hide_graphics"], kw["redact"]) == (True, False, False, True)
    _, kw = run_cli("--no-anim", "--read-only", "--hide-graphics", "--no-redact")  # the original spellings
    assert (kw["animate"], kw["read_only"], kw["hide_graphics"], kw["redact"]) == (False, True, True, False)


def test_untrusted_default_file_is_skipped_but_a_named_one_stops(run_cli, tmp_path, monkeypatch, capsys):
    cfg_dir = tmp_path / "xdg" / "nvpulse"
    cfg_dir.mkdir(parents=True)
    default = cfg_dir / "config.toml"
    default.write_text("interval = 7\n")
    default.chmod(0o666)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    code, kw = run_cli()  # nobody asked for this file: warn and carry on
    assert code == 0 and kw["interval"] == 1.0
    assert "continuing without it" in capsys.readouterr().err
    code, _ = run_cli("--config", str(default))  # asked for by name: stop
    assert code == 2


def test_dump_ignores_a_broken_settings_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NVPULSE_CONFIG", str(write(tmp_path, "intervl = 1")))
    assert cli.main(["--dump", "--mock", "1"]) == 0
    assert capsys.readouterr().out.lstrip().startswith("{")
