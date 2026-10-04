import asyncio

import pytest

from flight_service.jobs import JobFailed
from flight_service.sitl import Sitl


def test_pull_quotes_the_ref_and_returns_the_tag():
    seen = []

    def call(method, url, timeout):
        seen.append((method, url, timeout))
        return 200, {"image_tag": "submission-truck-detector-20261005-120000"}

    assert asyncio.run(Sitl("http://w", call).pull("perkiepai/truck-detector:1", 99)) == \
        "submission-truck-detector-20261005-120000"
    assert seen == [("POST", "http://w/agent/pull-docker?ref=perkiepai%2Ftruck-detector%3A1", 99)]


def test_pull_failure_carries_the_log_tail():
    with pytest.raises(JobFailed) as e:
        asyncio.run(Sitl("http://w", lambda m, u, t: (400, {"detail": "pull failed",
                                                             "log": ["a", "manifest unknown"]})).pull("perkiepai/x:1", 5))
    assert e.value.reason == "pull_failed" and "manifest unknown" in e.value.detail


def test_detrec_status():
    assert asyncio.run(Sitl("http://w", lambda m, u, t: (200, {"on": False})).detrec_status()) == {"on": False}
    assert asyncio.run(Sitl("http://w", lambda m, u, t: (None, {})).detrec_status()) is None
