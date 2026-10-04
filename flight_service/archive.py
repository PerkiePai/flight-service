"""Look inside uploaded tars before anything acts on them (design 12).
Reads members one at a time and only small metadata files; nothing is
extracted to disk.

  image_names(path)   every name `docker load` could give the one image in a
                      `docker save` archive. With the containerd image store
                      (this box, Docker 29) the load names images from
                      index.json annotations, not manifest.json, so both count.
  check_bundle(path)  a build context we forward to drone-sitl, whose
                      extractor follows links: plain files and directories only.
"""
import json
import tarfile
from pathlib import PurePosixPath

from .jobs import JobFailed

MAX_MEMBERS = 100_000
MAX_META_BYTES = 1 << 20
IMAGE_NAME = "io.containerd.image.name"
REF_NAME = "org.opencontainers.image.ref.name"


def _reject(why):
    raise JobFailed("archive_rejected", why)


def normalize(ref):
    """Docker's full form of an image reference: docker.io/library/x:latest."""
    name, at, digest = ref.partition("@")
    first, slash, _ = name.partition("/")
    if not slash or not ("." in first or ":" in first or first == "localhost"):
        name = "docker.io/" + (name if slash else "library/" + name)
    if not at and ":" not in name.rsplit("/", 1)[-1]:
        name += ":latest"
    return name + (at + digest if at else "")


def _clean(name):
    p = PurePosixPath(name)
    return str(p.relative_to("/")) if p.is_absolute() else str(p)


def _members(path):
    """(member, tar) one at a time, bounded; any read error is a rejection."""
    try:
        with tarfile.open(path, "r|*") as tar:
            for n, m in enumerate(tar, 1):
                if n > MAX_MEMBERS:
                    _reject(f"more than {MAX_MEMBERS} members")
                yield m, tar
    except JobFailed:
        raise
    except Exception as e:                           # noqa: BLE001 -- tar/gzip/zlib/EOF/...
        _reject(f"unreadable archive: {e!r}")


def _small_json(tar, m):
    if not m.isfile():
        _reject(f"{m.name} is not a regular file")
    if m.size > MAX_META_BYTES:
        _reject(f"{m.name} is {m.size} bytes (limit {MAX_META_BYTES})")
    try:
        return json.loads(tar.extractfile(m).read())
    except ValueError as e:
        _reject(f"{m.name} is not JSON: {e}")


def image_names(path):
    manifest = index = None
    oci = False
    for m, tar in _members(path):
        name = _clean(m.name)
        if name == "manifest.json":
            manifest = _small_json(tar, m)
        elif name == "index.json":
            index = _small_json(tar, m)
        elif name == "oci-layout":
            oci = True
    if manifest is None and index is None:
        _reject("no manifest.json or index.json: not a `docker save` archive")
    if oci and index is None:
        _reject("oci-layout without index.json")
    names = set()
    if manifest is not None:
        if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
            _reject("manifest.json must describe exactly one image")
        tags = manifest[0].get("RepoTags") or []
        if not isinstance(tags, list) or not all(isinstance(t, str) and t for t in tags):
            _reject("manifest.json RepoTags must be a list of names")
        names |= {normalize(t) for t in tags}
    if index is not None:
        descs = index.get("manifests") if isinstance(index, dict) else None
        if not isinstance(descs, list) or not descs or not all(isinstance(d, dict) for d in descs):
            _reject("index.json must list the image")
        if len({d.get("digest") for d in descs}) != 1:
            _reject("index.json must describe exactly one image")
        for d in descs:
            ann = d.get("annotations") or {}
            full, ref = (ann.get(IMAGE_NAME), ann.get(REF_NAME)) if isinstance(ann, dict) else (1, 1)
            if not all(v is None or isinstance(v, str) for v in (full, ref)):
                _reject("index.json annotations must be strings")
            if full:
                names.add(normalize(full))
            if ref:
                if "/" in ref or ":" in ref:
                    names.add(normalize(ref))
                elif not full:
                    _reject(f"index.json names the image only by the tag {ref!r}")
    return sorted(names)


def check_bundle(path):
    """Reject anything drone-sitl's extractor could be tricked with."""
    has_dockerfile = False
    for m, _ in _members(path):
        parts = PurePosixPath(m.name).parts
        if m.name.startswith("/") or ".." in parts:
            _reject(f"unsafe path {m.name!r} in bundle")
        if not (m.isfile() or m.isdir()):
            _reject(f"{m.name!r} is a link or special file; bundles hold plain files only")
        if _clean(m.name) == "Dockerfile" and m.isfile():
            has_dockerfile = True
    if not has_dockerfile:
        _reject("bundle has no Dockerfile at its root")
