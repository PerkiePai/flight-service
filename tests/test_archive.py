import io
import json
import tarfile

import pytest

from flight_service import archive
from flight_service.archive import check_bundle, image_names, normalize
from flight_service.jobs import JobFailed


def make_tar(path, members, mode="w"):
    """members: [(name, bytes | None for a directory | ("symlink"|"hardlink", target))]"""
    with tarfile.open(path, mode) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif isinstance(data, tuple):
                info.type = tarfile.SYMTYPE if data[0] == "symlink" else tarfile.LNKTYPE
                info.linkname = data[1]
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))


def saved(path, manifest=None, index=None, mode="w"):
    members = [("blobs/sha256/aa", b"layer")]
    if index is not None:
        members += [("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'),
                    ("index.json", json.dumps(index).encode())]
    if manifest is not None:
        members.append(("manifest.json", json.dumps(manifest).encode()))
    make_tar(path, members, mode)
    return path


def one_index(*names, digest="sha256:" + "a" * 64):
    return {"schemaVersion": 2, "manifests": [
        {"digest": digest, "annotations": {"io.containerd.image.name": n,
                                           "org.opencontainers.image.ref.name": n.rsplit(":", 1)[-1]}}
        for n in names]}


def rejected(fn, *a):
    with pytest.raises(JobFailed) as e:
        fn(*a)
    assert e.value.reason == "archive_rejected"
    return e.value.detail


@pytest.mark.parametrize("ref,full", [
    ("hello-world:latest", "docker.io/library/hello-world:latest"),
    ("truck", "docker.io/library/truck:latest"),
    ("perkiepai/x:1", "docker.io/perkiepai/x:1"),
    ("docker.io/library/competition-base:latest", "docker.io/library/competition-base:latest"),
    ("localhost:5000/a/b", "localhost:5000/a/b:latest"),
    ("ghcr.io/o/i@sha256:" + "b" * 64, "ghcr.io/o/i@sha256:" + "b" * 64),
])
def test_normalize(ref, full):
    assert normalize(ref) == full


@pytest.mark.parametrize("suffix,mode", [(".tar", "w"), (".tar.gz", "w:gz")])
def test_names_from_a_legacy_manifest(tmp_path, suffix, mode):
    p = saved(tmp_path / f"a{suffix}", manifest=[{"RepoTags": ["truck:1"]}], mode=mode)
    assert image_names(p) == ["docker.io/library/truck:1"]


def test_names_from_a_docker_29_save_include_index_json(tmp_path):
    """Caught in review: with the containerd image store, docker load names
    images from index.json, not manifest.json. Both must be checked."""
    p = saved(tmp_path / "a.tar", manifest=[{"RepoTags": ["harmless:1"]}],
              index=one_index("docker.io/library/competition-base:latest"))
    assert image_names(p) == ["docker.io/library/competition-base:latest",
                              "docker.io/library/harmless:1"]


def test_untagged_archive_has_no_names(tmp_path):
    p = saved(tmp_path / "a.tar", manifest=[{"RepoTags": None}],
              index={"manifests": [{"digest": "sha256:" + "a" * 64}]})
    assert image_names(p) == []


@pytest.mark.parametrize("manifest,index", [
    ([], None),
    ([{"RepoTags": ["a:1"]}, {"RepoTags": ["b:1"]}], None),
    ({"x": 1}, None),
    ([{"RepoTags": [1]}], None),
    ([{"RepoTags": "abc"}], None),
    (None, None),                                                       # neither file
    ([{"RepoTags": ["a:1"]}], {"manifests": [{"digest": "sha256:" + "a" * 64},
                                              {"digest": "sha256:" + "b" * 64}]}),  # two images
    (None, {"manifests": [{"digest": "sha256:" + "a" * 64,
                           "annotations": {"org.opencontainers.image.ref.name": "latest"}}]}),
])
def test_archives_that_are_not_exactly_one_known_image_are_rejected(tmp_path, manifest, index):
    rejected(image_names, saved(tmp_path / "a.tar", manifest=manifest, index=index))


def test_unreadable_archives_are_rejected_not_internal_errors(tmp_path):
    (tmp_path / "junk.tar").write_bytes(b"not a tar")
    rejected(image_names, tmp_path / "junk.tar")
    gz = saved(tmp_path / "a.tar.gz", manifest=[{"RepoTags": ["a:1"]}], mode="w:gz")
    (tmp_path / "cut.tar.gz").write_bytes(gz.read_bytes()[:40])
    rejected(image_names, tmp_path / "cut.tar.gz")
    make_tar(tmp_path / "dir.tar", [("manifest.json", None)])
    rejected(image_names, tmp_path / "dir.tar")


def test_metadata_and_member_count_are_bounded(tmp_path, monkeypatch):
    big = [{"RepoTags": ["a:1"], "pad": "x" * (archive.MAX_META_BYTES + 10)}]
    assert "bytes" in rejected(image_names, saved(tmp_path / "big.tar", manifest=big))
    monkeypatch.setattr(archive, "MAX_MEMBERS", 3)
    make_tar(tmp_path / "many.tar", [(f"f{i}", b"x") for i in range(5)])
    assert "members" in rejected(image_names, tmp_path / "many.tar")


def test_a_plain_bundle_passes(tmp_path):
    make_tar(tmp_path / "b.tar", [("Dockerfile", b"FROM competition-base:latest\n"),
                                  ("./requirements.txt", b""), ("pkg", None), ("pkg/a.py", b"x")])
    check_bundle(tmp_path / "b.tar")


@pytest.mark.parametrize("members,why", [
    ([("Dockerfile", b"FROM x"), ("a", ("symlink", "/home")), ("a/evil", b"x")], "link"),
    ([("Dockerfile", b"FROM x"), ("h", ("hardlink", "/etc/passwd"))], "link"),
    ([("Dockerfile", b"FROM x"), ("../evil", b"x")], "path"),
    ([("Dockerfile", b"FROM x"), ("/abs", b"x")], "path"),
    ([("app.py", b"x")], "Dockerfile"),
])
def test_unsafe_bundles_are_rejected(tmp_path, members, why):
    """Caught in review: drone-sitl's _safe_extract follows a symlink member
    out of the build context, so links never reach it."""
    make_tar(tmp_path / "b.tar", members)
    assert why in rejected(check_bundle, tmp_path / "b.tar")
