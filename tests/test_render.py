from nvpulse.ui import render as R


def test_gauge_width_and_precision():
    for pct in (0, 3.3, 50, 99.9, 100, 140, -5):
        t = R.gauge(20, pct, R.UTIL_GRAD)
        assert t.cell_len == 20
    assert R.gauge(10, None, R.UTIL_GRAD).plain == "╌" * 10
    # 1/8-cell precision: 50% of 3 cells = 1.5 cells -> one full cell then a half block
    assert R.gauge(3, 50, R.UTIL_GRAD).plain == " ▌ "
    assert R.gauge(3, 50, R.UTIL_GRAD, solid=True).plain == "█▌█"


def test_heat_bar_marker_and_width():
    t = R.heat_bar(30, 40, slowdown=88)
    assert t.cell_len == 30
    assert "┃" in t.plain
    assert R.heat_bar(30, 99, slowdown=88).plain.count("┃") == 0  # covered by fill


def test_sparkline_pads_and_handles_none():
    t = R.sparkline([0, 50, None, 100], 8, R.UTIL_GRAD)
    assert t.cell_len == 8
    assert t.plain.endswith("·█")
    assert R.sparkline(range(100), 5, R.UTIL_GRAD).cell_len == 5


def test_gradient_endpoints_and_mix():
    assert R.gradient(R.UTIL_GRAD, 0) == "#2dd4bf"
    assert R.gradient(R.UTIL_GRAD, 1) == "#ef4444"
    assert R.mix("#000000", "#ffffff", 0.5) == "#808080"


def test_fan_art_shape_and_rotation_changes_frame():
    a = R.fan_art(14, 7, 0.0)
    b = R.fan_art(14, 7, 0.4)
    assert len(a) == 7 and all(line.cell_len == 14 for line in a)
    assert [x.plain for x in a] != [x.plain for x in b]
    # full rotation by one blade sector reproduces the frame
    import math

    c = R.fan_art(14, 7, math.tau / 7)
    assert [x.plain for x in a] == [x.plain for x in c]


def test_heatsink_art_shape():
    lines = R.heatsink_art(8, 4, 1.0, 0.8, "#ff0000")
    assert len(lines) == 4 and all(line.cell_len == 8 for line in lines)


def test_tween_converges():
    tw = R.Tween(rate=10)
    tw.set("x", 0)
    tw.set("x", 100)
    for _ in range(60):
        tw.step(0.05)
    assert abs(tw["x"] - 100) < 0.1
    tw.set("x", None)
    assert tw["x"] is None


def test_formatting():
    assert R.fmt_mem_pair(12 * 1024**3, 24 * 1024**3) == "12.0/24G"
    assert R.fmt_mem_pair(None, 1) == "n/a"
    assert R.fmt_bytes(915 * 1024**2) == "915 MiB"


def test_history_graph_shape_and_levels():
    lines = R.history_graph([0, 50, 100, None], 6, 3, R.UTIL_GRAD)
    assert len(lines) == 3 and all(line.cell_len == 6 for line in lines)
    top, _mid, bottom = (line.plain for line in lines)
    assert top.strip() == "⢸" or top.strip() == "⡇"  # only the 100 % sample reaches the top row
    assert bottom.startswith("⣀⣀⣀⣀")  # no history yet: faint baseline
    assert R.history_graph([], 4, 2, R.UTIL_GRAD)[1].plain == "⣀⣀⣀⣀"
    assert R.history_graph([1], 0, 3, R.UTIL_GRAD) == []
    # newest sample sits in the right-hand column; a zero still draws the baseline dot
    assert R.history_graph([0], 2, 1, R.UTIL_GRAD)[0].plain == "⣀⢀"


def test_sparkline_lead_in_is_dotted():
    assert R.sparkline([100], 4, R.UTIL_GRAD).plain == "···█"


def test_rate_and_energy_formatting():
    assert R.fmt_rate(None) == "n/a"
    assert R.fmt_rate(512) == "512 KB/s"
    assert R.fmt_rate(7031) == "7.0 MB/s"
    assert R.fmt_rate(2_500_000) == "2.50 GB/s"
    assert R.fmt_energy(1_775_044) == "0.49 kWh"
    assert R.fmt_energy(7200) == "2.0 Wh"


def test_time_axis_and_stats():
    axis = R.time_axis(60, 240)
    assert axis.cell_len == 60
    assert axis.plain.startswith("-4m ") and " -2m " in axis.plain and axis.plain.endswith(" now")
    assert R.time_axis(10, 240).plain.strip() == "now"  # too narrow for the full ruler
    assert R.time_axis(40, 0).plain.strip() == "now"  # no history yet
    assert R.time_axis(0, 60).plain == ""
    assert R.stats([None, 10, 30, None]) == (10, 20, 30)
    assert R.stats([None]) is None


def test_duration_and_session_energy_formatting():
    assert [R.fmt_duration(s) for s in (0, 59, 60, 95, 3600, 3725)] == ["0s", "59s", "1m", "1m35s", "1h00m", "1h02m"]
    assert R.fmt_session_energy(None) == "n/a"
    assert R.fmt_session_energy(12.34) == "12.3 Wh"
    assert R.fmt_session_energy(2500) == "2.50 kWh"
    assert R.fmt_session_energy(2500, 0.30, "€") == "2.50 kWh (€0.75)"


def test_tween_lands_on_its_target_and_reports_rest():
    tw = R.Tween(rate=6)
    tw.set("x", 0)
    assert tw.step(0.05) is False  # nothing to do
    tw.set("x", 100)
    steps = 0
    while tw.step(0.05):
        steps += 1
        assert steps < 200
    assert tw["x"] == 100  # exactly, not asymptotically
    tw.set("none", None)
    assert tw.step(0.05) is False


def test_themes_switch_the_neutral_palette_and_back():
    default = (R.TRACK, R.DIM, R.LABEL, R.TEXT, R.BORDER)
    try:
        R.set_theme("high-contrast")
        assert (R.TEXT, R.BORDER) == ("#ffffff", "#8b949e") and default[1] != R.DIM
        R.set_theme("mono")
        assert default == (R.TRACK, R.DIM, R.LABEL, R.TEXT, R.BORDER)
    finally:
        R.set_theme("default")
    assert default == (R.TRACK, R.DIM, R.LABEL, R.TEXT, R.BORDER)
