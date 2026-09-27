"""Unit test for device selection: WASAPI must win over MME on Windows, and a
single-host-API list (macOS Core Audio) must still return the first match.

Run:  python -m pytest test_find_device.py   (or:  python test_find_device.py)
"""
import importlib.util
import os
import sys

import pytest

# The worker file has a hyphen in its name, so load it by path.
_spec = importlib.util.spec_from_file_location(
    "yeti_monitor", os.path.join(os.path.dirname(__file__), "yeti-monitor.py"))
yeti_monitor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yeti_monitor)
find_device = yeti_monitor.find_device

WIN_APIS = [{"name": "MME"}, {"name": "Windows DirectSound"},
            {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]
# Shape mirrors the real fancy-pc listing: truncated MME names, the Corsair
# microphone sharing the substring with the earphone, WASAPI not first.
WIN_DEVICES = [
    {"name": "Microphone (Yeti Stereo Microph", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Headset Microphone (CORSAIR VIR", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
    {"name": "Headset Earphone (CORSAIR VIRTU", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 8},
    {"name": "Microphone (Yeti Stereo Microphone)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Headset Earphone (CORSAIR VIRTUOSO SE Wireless Gaming Headset)", "hostapi": 2, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Microphone (Yeti Stereo Microphone)", "hostapi": 2, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Headset Microphone (CORSAIR VIRTUOSO SE Wireless Gaming Headset)", "hostapi": 2, "max_input_channels": 1, "max_output_channels": 0},
    {"name": "Microphone (Yeti Stereo Microphone)", "hostapi": 3, "max_input_channels": 2, "max_output_channels": 0},
]

MAC_APIS = [{"name": "Core Audio"}]
MAC_DEVICES = [
    {"name": "Yeti Stereo Microphone", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 2},
    {"name": "CORSAIR VIRTUOSO SE Wireless Gaming Headset", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 2},
]


def test_windows_prefers_wasapi_input():
    assert find_device("Yeti", "input", WIN_DEVICES, WIN_APIS) == 5


def test_windows_prefers_wasapi_output_and_skips_corsair_mic():
    assert find_device("CORSAIR", "output", WIN_DEVICES, WIN_APIS) == 4


def test_falls_back_to_first_match_without_wasapi():
    # Only MME/DirectSound/WDM-KS rows for a made-up device: first match wins.
    devs = [d for d in WIN_DEVICES if d["hostapi"] != 2]
    assert find_device("Yeti", "input", devs, WIN_APIS) == 0


def test_mac_single_hostapi_first_match():
    assert find_device("Yeti", "input", MAC_DEVICES, MAC_APIS) == 0
    assert find_device("CORSAIR", "output", MAC_DEVICES, MAC_APIS) == 1


def test_no_match_exits():
    with pytest.raises(SystemExit):
        find_device("Nonexistent", "output", WIN_DEVICES, WIN_APIS)


# --- endpoint re-arrival decision (drives auto-recovery after headset wake) ---
endpoints_changed = yeti_monitor.endpoints_changed
MIC, HS = "Microphone (Yeti)", "Headset Earphone (CORSAIR)"


def test_same_arrival_is_not_a_change():
    assert not endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: 200})


def test_newer_arrival_is_a_change():
    assert endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: 999})


def test_absent_then_present_with_new_arrival_is_a_change():
    # headset asleep at a poll (None), then back with a fresh arrival stamp
    assert endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: 300})


def test_still_absent_is_not_a_change():
    # reopen would fail anyway; wait for it to come back
    assert not endpoints_changed({MIC: 100, HS: 200}, {MIC: 100, HS: None})


def test_unwatched_endpoint_never_triggers():
    # no baseline (None) = watch disabled for that name, even if it appears
    assert not endpoints_changed({MIC: None, HS: None}, {MIC: 5, HS: 6})
    assert not endpoints_changed({}, {MIC: 5})


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
