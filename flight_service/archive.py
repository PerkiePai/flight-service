"""Look inside a `docker save` archive before `docker load` runs it: one
image, and which tags it would create (design 12). Reads only metadata;
nothing is extracted to disk."""
import json
import tarfile

from .jobs import JobFailed


def repo_tags(path):
    try:
        with tarfile.open(path, "r:*") as tar:
            member = tar.getmember("manifest.json")
            data = json.load(tar.extractfile(member))
    except KeyError:
        raise JobFailed("archive_rejected", "no manifest.json: not a `docker save` archive")
    except (tarfile.TarError, OSError, ValueError) as e:
        raise JobFailed("archive_rejected", f"unreadable archive: {e}")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise JobFailed("archive_rejected", "the archive must hold exactly one image")
    return list(data[0].get("RepoTags") or [])
