import pytest

from flight_service.config import DEFAULT_ALLOWED, Settings

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


def test_from_env_overrides(tmp_path):
    s = Settings.from_env({"RUNNER_TOKEN": TOKEN, "DRONE_SITL_DIR": str(tmp_path),
                           "ALLOWED_IMAGES": "^a$ ^b$", "KEEP_IMAGE": "1",
                           "ARMING_TIMEOUT_S": "5", "DATA_RETENTION_GB": "0"})
    assert s.drone_sitl_dir == tmp_path and s.allowed_images == ("^a$", "^b$")
    assert s.keep_image is True and s.arming_timeout_s == 5.0 and s.data_retention_gb == 0.0
