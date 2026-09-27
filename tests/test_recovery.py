"""The endpoint re-arrival decision that drives auto-recovery, plus the
worker's argument round trip."""

import argparse

from mic_monitor.worker import (
    add_settings_args,
    endpoints_changed,
    settings_from_args,
    settings_to_args,
)

MIC, HS = "Microphone (Yeti)", "Headset Earphone (CORSAIR)"


def test_same_arrival_is_not_a_change():
    assert not endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: 200})


def test_newer_arrival_is_a_change():
    assert endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: 999})


def test_still_absent_is_not_a_change():
    # headset still off: a reopen would fail, keep waiting
    assert not endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: None})


def test_unwatched_endpoint_never_triggers():
    assert not endpoints_changed({MIC: None, HS: None}, {MIC: 5, HS: 6})
    assert not endpoints_changed({}, {MIC: 5})


def test_settings_round_trip_through_argv():
    settings = {"in": "Yeti", "out": "CORSAIR", "gain": 0.5, "blocksize": 128, "samplerate": None}
    argv = settings_to_args(settings)
    assert "--samplerate" not in argv  # None is omitted, not passed as "None"
    ap = argparse.ArgumentParser()
    add_settings_args(ap)
    assert settings_from_args(ap.parse_args(argv)) == settings


def test_settings_to_args_with_nothing_set():
    empty = {k: None for k in ("in", "out", "gain", "blocksize", "samplerate")}
    assert settings_to_args(empty) == []
