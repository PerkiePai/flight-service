from pathlib import Path

import pytest

from flight_service.config import DEFAULT_ALLOWED, HERE, Settings

TOKEN = "t" * 32


def test_from_env_requires_a_long_token():
    with pytest.raises(SystemExit):
        Settings.from_env({"RUNNER_TOKEN": "short"})
    with pytest.raises(SystemExit):
        Settings.from_env({})


def test_from_env_defaults():
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN})
    assert (s.host, s.port) == ("127.0.0.1", 8095)
    assert s.allowed_images == (DEFAULT_ALLOWED,)
    assert s.runs_dir.parts[-2:] == ("data", "runs")
    assert s.uploads_dir.parts[-2:] == ("data", "uploads")
    assert (s.data_retention_gb, s.kill_wait_s, s.max_pending) == (10.0, 60.0, 1)
    assert (s.default_flight_s, s.max_flight_s) == (600, 900)
    assert "--cap-drop ALL" in s.docker_run_args and s.keep_image is False


def test_each_service_start_gets_its_own_drone_sitl_upload_token():
    a, b = Settings.from_env({"RUNNER_TOKEN": TOKEN}), Settings.from_env({"RUNNER_TOKEN": TOKEN})
    assert len(a.sitl_upload_token) >= 32 and a.sitl_upload_token != b.sitl_upload_token
    assert a.sitl_upload_token != a.token


def test_from_env_overrides(tmp_path):
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": str(tmp_path),
                           "ALLOWED_IMAGES": "^a$ ^b$", "KEEP_IMAGE": "1",
                           "ARMING_TIMEOUT_S": "5", "DATA_RETENTION_GB": "0"})
    assert s.drone_sitl_dir == tmp_path and s.allowed_images == ("^a$", "^b$")
    assert s.keep_image is True and s.arming_timeout_s == 5.0 and s.data_retention_gb == 0.0


def test_drone_sitl_dir_defaults_to_the_vendored_copy():
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN})
    assert s.drone_sitl_dir == HERE / "vendor" / "drone-sitl"
    assert (s.drone_sitl_dir / "sim" / "run-website.sh").is_file()


def test_relative_drone_sitl_dir_is_relative_to_the_project_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": "vendor/drone-sitl"})
    assert s.drone_sitl_dir == HERE / "vendor" / "drone-sitl" and s.drone_sitl_dir.is_absolute()


def test_drone_sitl_dir_expands_home(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": "~/pai/drone-sitl"})
    assert s.drone_sitl_dir == Path("/h/pai/drone-sitl")


@pytest.mark.parametrize("value", ["../drone-sitl", "vendor/../vendor/drone-sitl", "/tmp/x/../drone-sitl"])
def test_drone_sitl_dir_has_no_dotdot(value):
    """The scripts work out their own dir with `cd .. && pwd`, so sim.py's
    pgrep for <dir>/sim/bootstrap.py only matches a collapsed path."""
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": value})
    assert ".." not in s.drone_sitl_dir.parts
