"""Config load/save/resolve and the per-user directories."""

import json

from mic_monitor import config


def test_load_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "nope.json") == config.DEFAULTS


def test_load_ignores_unknown_keys_and_garbage(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"in": "Yeti", "bogus": 1}), encoding="utf-8")
    assert config.load(p)["in"] == "Yeti"
    assert "bogus" not in config.load(p)
    p.write_text("not json", encoding="utf-8")
    assert config.load(p) == config.DEFAULTS


def test_save_merges_and_round_trips(tmp_path):
    p = tmp_path / "sub" / "config.json"  # parent dir is created
    config.save({"in": "Yeti"}, p)
    config.save({"out": "CORSAIR", "gain": 0.8}, p)
    loaded = config.load(p)
    assert loaded["in"] == "Yeti" and loaded["out"] == "CORSAIR" and loaded["gain"] == 0.8
    assert loaded["blocksize"] == 64  # untouched default persists


def test_resolve_precedence_cli_over_saved_over_default():
    saved = {"in": "Yeti", "gain": 0.5}
    cli = {"in": None, "gain": 2.0, "out": "CORSAIR"}
    r = config.resolve(cli, saved)
    assert r["in"] == "Yeti"  # CLI None does not override
    assert r["gain"] == 2.0  # CLI value wins
    assert r["out"] == "CORSAIR"
    assert r["blocksize"] == 64  # default


def test_dirs_follow_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgc"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdgs"))
    assert config.config_dir().parent.parent == tmp_path
    assert config.state_dir().parent.parent == tmp_path
    assert config.config_dir().name == "mic-monitor"
    assert config.pid_path().parent == config.state_dir()
