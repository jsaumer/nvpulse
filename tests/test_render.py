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
