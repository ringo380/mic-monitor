"""Hardware tests: need real audio devices and an audible monitor path.
Skipped unless MIC_MONITOR_HW=1. They use the saved config (or the system
defaults) for device selection, so run `mic-monitor config` first if needed.

    MIC_MONITOR_HW=1 python -m pytest tests/test_hardware.py -v
"""

import io
import os
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MIC_MONITOR_HW") != "1", reason="set MIC_MONITOR_HW=1 to run hardware tests"
)


@pytest.fixture
def settings():
    from mic_monitor import config

    return config.resolve({}, config.load())


def test_open_and_close_stream(settings, tmp_path):
    from mic_monitor.worker import Monitor

    mon = Monitor(settings, status_file=tmp_path / "status.json")
    stream, names = mon.open()
    try:
        assert stream.active
        assert all(names)
    finally:
        stream.close()
    assert (tmp_path / "status.json").exists()


def test_reopen_after_simulated_endpoint_rearrival(settings, tmp_path):
    """Runs the worker loop on the main thread (as in production) with an
    injected endpoint snapshot that reports a new arrival stamp on the second
    poll. Proves the terminate/initialize/reopen mechanics on real devices."""
    from mic_monitor.worker import Monitor

    calls = {"n": 0}

    def fake_snapshot(names):
        calls["n"] += 1
        snap = {n: 1000 for n in names}
        if calls["n"] >= 2:
            snap[names[1]] = 2000  # output endpoint re-arrived
        return snap

    mon = Monitor(settings, snapshot=fake_snapshot, status_file=tmp_path / "status.json")
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    threading.Timer(5.0, mon.stop.set).start()  # first PnP check is at 2 s
    try:
        mon.run()
    finally:
        sys.stdout = real
    out = buf.getvalue()
    assert mon.reopens == 1, out
    assert "Reopening: audio endpoint re-arrived" in out and "Reopened." in out
    assert out.count("Monitoring:") == 2


def test_reopen_after_simulated_default_input_change(settings, tmp_path):
    """Same loop with the input left unset (system default) and an injected
    default-ID reader whose input ID moves on the second poll."""
    from mic_monitor.worker import Monitor

    calls = {"n": 0}

    def fake_defaults():
        calls["n"] += 1
        return ("in-a" if calls["n"] < 2 else "in-b", "out-a")

    followed = dict(settings, **{"in": None})
    mon = Monitor(
        followed, snapshot=lambda names: {}, defaults=fake_defaults,
        status_file=tmp_path / "status.json",
    )
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    threading.Timer(5.0, mon.stop.set).start()
    try:
        mon.run()
    finally:
        sys.stdout = real
    out = buf.getvalue()
    assert mon.reopens == 1, out
    assert "Reopening: system default input device changed" in out and "Reopened." in out


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Core Audio")
def test_windows_default_endpoint_ids():
    import sounddevice  # noqa: F401  PortAudio up first, as in the worker

    from mic_monitor.winaudio import default_endpoint_ids

    ids = default_endpoint_ids()
    assert all(i and i.startswith("{0.0.") for i in ids), ids
    assert ids == default_endpoint_ids()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PnP watch")
def test_windows_snapshot_sees_both_endpoints(settings):
    import sounddevice as sd

    from mic_monitor.devices import resolve_device
    from mic_monitor.winpnp import snapshot_endpoints

    names = (
        sd.query_devices(resolve_device(settings["in"], "input"))["name"],
        sd.query_devices(resolve_device(settings["out"], "output"))["name"],
    )
    snap = snapshot_endpoints(names)
    assert all(v is not None for v in snap.values()), snap
