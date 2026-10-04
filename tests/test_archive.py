import io
import json
import tarfile

import pytest

from flight_service.archive import repo_tags
from flight_service.jobs import JobFailed


def make_tar(path, manifest, mode="w"):
    with tarfile.open(path, mode) as tar:
        for name, data in (("blobs/sha256/aa", b"layer"), ("manifest.json", json.dumps(manifest).encode())):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize("suffix,mode", [(".tar", "w"), (".tar.gz", "w:gz")])
def test_repo_tags(tmp_path, suffix, mode):
    p = tmp_path / f"a{suffix}"
    make_tar(p, [{"Config": "c", "RepoTags": ["truck:1"], "Layers": []}], mode)
    assert repo_tags(p) == ["truck:1"]


def test_untagged_archive_is_fine(tmp_path):
    make_tar(tmp_path / "a.tar", [{"Config": "c", "RepoTags": None, "Layers": []}])
    assert repo_tags(tmp_path / "a.tar") == []


@pytest.mark.parametrize("manifest", [[], [{"RepoTags": ["a:1"]}, {"RepoTags": ["b:1"]}], {"x": 1}])
def test_not_exactly_one_image_is_rejected(tmp_path, manifest):
    make_tar(tmp_path / "a.tar", manifest)
    with pytest.raises(JobFailed) as e:
        repo_tags(tmp_path / "a.tar")
    assert e.value.reason == "archive_rejected"


def test_not_an_archive(tmp_path):
    (tmp_path / "a.tar").write_bytes(b"not a tar")
    with pytest.raises(JobFailed) as e:
        repo_tags(tmp_path / "a.tar")
    assert e.value.reason == "archive_rejected"
