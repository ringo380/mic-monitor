"""Device selection without hardware. Shapes mirror a real Windows listing:
truncated MME names, the headset microphone sharing a substring with the
headset earphone, WASAPI not first."""

import pytest

from mic_monitor.devices import DeviceNotFound, default_device, find_device, resolve_device


def _api(name, din, dout):
    return {"name": name, "default_input_device": din, "default_output_device": dout}


def _dev(name, api, ins, outs):
    return {"name": name, "hostapi": api, "max_input_channels": ins, "max_output_channels": outs}


HS = "Headset Earphone (CORSAIR VIRTUOSO SE Wireless Gaming Headset)"
HS_MIC = "Headset Microphone (CORSAIR VIRTUOSO SE Wireless Gaming Headset)"
MIC = "Microphone (Yeti Stereo Microphone)"

WIN_APIS = [
    _api("MME", 0, 2),
    _api("Windows DirectSound", 3, -1),
    _api("Windows WASAPI", 5, 4),
    _api("Windows WDM-KS", 7, -1),
]
WIN_DEVICES = [
    _dev("Microphone (Yeti Stereo Microph", 0, 2, 0),  # MME truncates names
    _dev("Headset Microphone (CORSAIR VIR", 0, 1, 0),
    _dev("Headset Earphone (CORSAIR VIRTU", 0, 0, 8),
    _dev(MIC, 1, 2, 0),
    _dev(HS, 2, 0, 2),  # 4: WASAPI output
    _dev(MIC, 2, 2, 0),  # 5: WASAPI input
    _dev(HS_MIC, 2, 1, 0),
    _dev(MIC, 3, 2, 0),
]

MAC_APIS = [_api("Core Audio", 0, 1)]
MAC_DEVICES = [
    _dev("Yeti Stereo Microphone", 0, 2, 2),
    _dev("MacBook Pro Speakers", 0, 0, 2),
]


def test_windows_prefers_wasapi_input():
    assert find_device("Yeti", "input", WIN_DEVICES, WIN_APIS) == 5


def test_windows_prefers_wasapi_output_and_skips_headset_mic():
    assert find_device("CORSAIR", "output", WIN_DEVICES, WIN_APIS) == 4


def test_falls_back_to_first_match_without_wasapi():
    devs = [d for d in WIN_DEVICES if d["hostapi"] != 2]
    assert find_device("Yeti", "input", devs, WIN_APIS) == 0


def test_mac_single_hostapi_first_match():
    assert find_device("Yeti", "input", MAC_DEVICES, MAC_APIS) == 0
    assert find_device("Speakers", "output", MAC_DEVICES, MAC_APIS) == 1


def test_no_match_raises():
    with pytest.raises(DeviceNotFound):
        find_device("Nonexistent", "output", WIN_DEVICES, WIN_APIS)


def test_bad_kind_rejected():
    with pytest.raises(ValueError):
        find_device("Yeti", "sideways", WIN_DEVICES, WIN_APIS)


def test_windows_default_uses_wasapi_hostapi_defaults():
    # PortAudio's own default (pa_default) is the MME one and must be ignored
    assert default_device("input", WIN_DEVICES, WIN_APIS, pa_default=(0, 2)) == 5
    assert default_device("output", WIN_DEVICES, WIN_APIS, pa_default=(0, 2)) == 4


def test_mac_default_uses_portaudio_default():
    assert default_device("input", MAC_DEVICES, MAC_APIS, pa_default=(0, 1)) == 0
    assert default_device("output", MAC_DEVICES, MAC_APIS, pa_default=(0, 1)) == 1


def test_no_default_raises():
    with pytest.raises(DeviceNotFound):
        default_device("output", MAC_DEVICES, MAC_APIS, pa_default=(0, -1))


def test_resolve_none_means_default_and_name_means_match():
    assert resolve_device(None, "output", WIN_DEVICES, WIN_APIS) == 4
    assert resolve_device("", "input", WIN_DEVICES, WIN_APIS) == 5
    assert resolve_device("yeti", "input", MAC_DEVICES, MAC_APIS) == 0
