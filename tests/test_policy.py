import json

import pytest

from flight_service.config import DEFAULT_ALLOWED, GB
from flight_service.jobs import JobFailed
from flight_service.policy import check_ref, check_space, manifest_bytes

P = (DEFAULT_ALLOWED,)


@pytest.mark.parametrize("ref", ["perkiepai/truck-detector:20260929-214240",
                                 "docker.io/perkiepai/truck-detector:latest",
                                 "perkiepai/x@sha256:" + "a" * 64])
def test_allowed_refs(ref):
    assert check_ref(ref, P) is None


@pytest.mark.parametrize("ref", ["submission-truck-detector-20260929-214240",
                                 "competition-base:latest", "postgres:15.4",
                                 "evil.io/perkiepai/x:1", "perkiepai/x:1;rm", "perkiepai/X:1"])
def test_refs_off_the_allowlist_are_403(ref):
    assert check_ref(ref, P)[0] == 403


@pytest.mark.parametrize("ref", ["", " perkiepai/x:1", "perkiepai/x:1\n", "a" * 513, None])
def test_malformed_refs_are_400(ref):
    assert check_ref(ref, P)[0] == 400


def test_manifest_bytes_single_and_multi_platform():
    assert manifest_bytes(json.dumps({"SchemaV2Manifest": {"layers": [{"size": 10}, {"size": 5}]}})) == 15
    multi = [{"Descriptor": {"platform": {"os": "linux", "architecture": "arm64"}},
              "OCIManifest": {"layers": [{"size": 999}]}},
             {"Descriptor": {"platform": {"os": "linux", "architecture": "amd64"}},
              "OCIManifest": {"layers": [{"size": 7}]}}]
    assert manifest_bytes(json.dumps(multi)) == 7
    assert manifest_bytes("not json") is None and manifest_bytes("{}") is None


def test_check_space():
    check_space(100 * GB, 12 * GB, min_free_gb=40, max_image_gb=16)
    check_space(100 * GB, None, min_free_gb=40, max_image_gb=16)
    for free, img, min_free, why in [(100 * GB, 17 * GB, 40, "image_too_large"),
                                     (30 * GB, 1 * GB, 40, "disk_low"),     # under MIN_FREE_GB
                                     (25 * GB, 15 * GB, 20, "disk_low")]:   # under 2x the image
        with pytest.raises(JobFailed) as e:
            check_space(free, img, min_free, 16)
        assert e.value.reason == why
    check_space(50 * GB, 15 * GB, 40, 16)       # 50 >= max(40, 2 x 15)
