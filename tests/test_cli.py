"""CLI plumbing that needs no audio hardware: liveness, PID file, status,
worker command line. State is redirected to a temp dir via env vars."""

import json
import os
import subprocess
import sys

import pytest

from mic_monitor import cli, config


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


def test_own_pid_is_alive_and_absurd_pid_is_not():
    assert cli.pid_alive(os.getpid())
    assert not cli.pid_alive(2**22 + 12345)
    assert not cli.pid_alive(0)
    assert not cli.pid_alive(-1)


def test_pid_alive_does_not_kill_the_target():
    # A sleeping child must survive a liveness check (os.kill(pid, 0) would
    # terminate it on Windows).
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert cli.pid_alive(child.pid)
        assert child.poll() is None, "liveness check killed the process"
    finally:
        child.kill()
        child.wait()


def test_status_not_running_when_no_pid_file():
    assert cli.status() == "Not running."
    assert not cli.is_running()


def test_stale_pid_file_is_cleaned_on_stop():
    config.state_dir().mkdir(parents=True)
    config.pid_path().write_text("4", encoding="utf-8")  # not a Python process
    assert cli.read_pid() is None
    assert cli.stop() == "Not running."
    assert not config.pid_path().exists()


def test_garbage_pid_file():
    config.state_dir().mkdir(parents=True)
    config.pid_path().write_text("nope", encoding="utf-8")
    assert cli.read_pid() is None


def test_worker_command_carries_settings_and_paths():
    cmd = cli.worker_command({"in": "Yeti", "out": None, "gain": 0.5}, python="py", token="abc")
    assert cmd[:3] == ["py", "-m", "mic_monitor.worker"]
    assert "--log" in cmd and str(config.log_path()) in cmd
    assert "--status-file" in cmd and str(config.status_path()) in cmd
    assert cmd[cmd.index("--token") + 1] == "abc"
    assert cmd[cmd.index("--in") + 1] == "Yeti"
    assert "--out" not in cmd
    assert cmd[cmd.index("--gain") + 1] == "0.5"


def test_status_file_only_trusted_with_matching_token():
    # In a Windows venv the launched PID is a launcher and the worker is its
    # child, so status.json is matched by token, never by PID.
    config.state_dir().mkdir(parents=True)
    config.pid_path().write_text(f"{os.getpid()} tok1\n", encoding="utf-8")
    st = {"pid": 999999, "token": "tok1", "in": "A", "out": "B", "reopens": 0}
    config.status_path().write_text(json.dumps(st), encoding="utf-8")
    assert cli.read_record() == (os.getpid(), "tok1")
    assert cli.read_status()["in"] == "A"
    assert cli.status() == f"Running (pid {os.getpid()}): A  ->  B"
    st["token"] = "stale"
    config.status_path().write_text(json.dumps(st), encoding="utf-8")
    assert cli.read_status() is None
    assert "still opening" in cli.status()


def test_status_shows_waiting_instead_of_last_devices():
    config.state_dir().mkdir(parents=True)
    config.pid_path().write_text(f"{os.getpid()} tok1\n", encoding="utf-8")
    st = {"token": "tok1", "in": "A", "out": "B", "reopens": 1, "waiting": "no device"}
    config.status_path().write_text(json.dumps(st), encoding="utf-8")
    assert cli.status() == f"Running (pid {os.getpid()}), waiting for device: no device"


def test_legacy_pid_file_without_token_still_parses():
    config.state_dir().mkdir(parents=True)
    config.pid_path().write_text(f"{os.getpid()}", encoding="utf-8")
    assert cli.read_record() == (os.getpid(), "")


def test_config_command_saves_and_shows(capsys):
    assert cli.main(["config", "--in", "Yeti", "--gain", "0.7"]) == 0
    out = capsys.readouterr().out
    assert "Saved to" in out and "Yeti" in out
    saved = config.load()
    assert saved["in"] == "Yeti" and saved["gain"] == 0.7
    cli.main(["config"])
    assert "(system default)" in capsys.readouterr().out  # out is unset
    cli.main(["config", "--in", ""])
    assert config.load()["in"] is None and config.load()["gain"] == 0.7
    cli.main(["config", "--reset"])
    assert not config.config_path().exists()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "mic-monitor" in capsys.readouterr().out
