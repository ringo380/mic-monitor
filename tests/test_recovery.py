"""The endpoint re-arrival decision that drives auto-recovery, plus the
worker's argument round trip."""

import argparse

from mic_monitor.worker import (
    Monitor,
    add_settings_args,
    default_changed,
    endpoints_changed,
    settings_from_args,
    settings_to_args,
    stream_channels,
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


BOTH = (True, True)


def test_same_default_is_not_a_change():
    assert default_changed(("a", "x"), ("a", "x"), BOTH) is None


def test_new_default_input_is_a_change():
    assert default_changed(("a", "x"), ("b", "x"), BOTH) == "input"
    assert default_changed(("a", "x"), ("a", "y"), BOTH) == "output"


def test_pinned_device_ignores_default_change():
    assert default_changed(("a", "x"), ("b", "x"), (False, True)) is None
    assert default_changed(("a", "x"), ("a", "y"), (True, False)) is None


def test_vanished_or_unknown_default_is_not_a_change():
    assert default_changed(("a", "x"), (None, "x"), BOTH) is None
    assert default_changed((None, None), ("b", "y"), BOTH) is None


def test_monitor_follows_only_unset_devices():
    assert Monitor({"in": None, "out": "CORSAIR"}).follow == (True, False)
    assert Monitor({"in": "", "out": None}).follow == (True, True)
    assert Monitor({"in": "Yeti", "out": "CORSAIR"}).follow == (False, False)


def _dev(i, o):
    return {"max_input_channels": i, "max_output_channels": o}


def test_stream_channels():
    assert stream_channels(_dev(2, 0), _dev(0, 2)) == (2, 2)
    assert stream_channels(_dev(1, 0), _dev(0, 2)) == (1, 2)  # mono mic, both ears
    assert stream_channels(_dev(8, 0), _dev(0, 6)) == (2, 2)  # capped at stereo
    assert stream_channels(_dev(2, 0), _dev(0, 1)) == (1, 1)  # never wider than out


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
