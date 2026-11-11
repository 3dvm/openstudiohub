"""Unit tests for the shared adaptive duration formatting."""

from src.interfaces.qt.ui_format import format_duration, format_rate


def test_duration_uses_seconds_minutes_and_hours():
    assert format_duration(0) == "0s"
    assert format_duration(5) == "5s"
    assert format_duration(59.6) == "1m"
    assert format_duration(61) == "1m 1s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(3600) == "1h"
    assert format_duration(3661) == "1h 1m 1s"
    assert format_duration(5400) == "1h 30m"


def test_duration_switches_to_days_weeks_months_and_years():
    day = 86400
    week = 7 * day

    assert format_duration(day) == "1d"
    assert format_duration(day + 3600) == "1d 1h"
    assert format_duration(day + 3661) == "1d 1h 1m"
    assert format_duration(week) == "7d"
    assert format_duration(week + 1) == "1w"
    assert format_duration(week + day) == "1w 1d"
    assert format_duration(29 * day) == "4w 1d"
    assert format_duration(30 * day) == "1mo"
    assert format_duration(31 * day) == "1mo 1d"
    assert format_duration(365 * day) == "1y"
    assert format_duration(400 * day) == "1y 1mo 5d"


def test_duration_handles_invalid_values_and_placeholders():
    assert format_duration(None) == "--"
    assert format_duration("nope") == "--"
    assert format_duration(-3) == "--"
    assert format_duration(None, placeholder="--:--") == "--:--"


def test_rate_preserves_fractional_seconds_below_a_minute():
    assert format_rate(0.04) == "<0.1s"
    assert format_rate(0.4) == "0.4s"
    assert format_rate(1.25) == "1.2s"
    assert format_rate(45.6) == "45.6s"
    assert format_rate(59.96) == "1m"
    assert format_rate(90) == "1m 30s"
    assert format_rate(None) == "--"


def test_format_bytes_uses_decimal_units():
    from src.interfaces.qt.ui_format import format_bytes

    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(31_517_997) == "31.5 MB"
    assert format_bytes(116_582_529) == "116.6 MB"
    assert format_bytes(36_907_445_437) == "36.9 GB"
    assert format_bytes(None) == "--"
    assert format_bytes(-1) == "--"
