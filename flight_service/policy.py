"""What the runner agrees to run: which image refs, how big, how much
disk must stay free (design 8)."""
import json
import re

from .config import GB
from .jobs import JobFailed


def check_ref(ref, patterns):
    """None if `ref` may be pulled, else (http status, why not)."""
    if (not isinstance(ref, str) or not ref or len(ref) > 512
            or any(c.isspace() for c in ref)):
        return 400, "image must be a single-line image reference"
    if not any(re.fullmatch(p, ref) for p in patterns):
        return 403, "image is not on the allowlist"
    return None


def manifest_bytes(text, arch="amd64"):
    """Compressed size from `docker manifest inspect -v` for linux/<arch>."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    for entry in data if isinstance(data, list) else [data]:
        if not isinstance(entry, dict):
            continue
        plat = (entry.get("Descriptor") or {}).get("platform") or {}
        if plat and (plat.get("os"), plat.get("architecture")) != ("linux", arch):
            continue
        layers = (entry.get("OCIManifest") or entry.get("SchemaV2Manifest") or {}).get("layers")
        if layers:
            return sum(int(layer.get("size", 0)) for layer in layers)
    return None


def check_space(free_bytes, image_bytes, min_free_gb, max_image_gb):
    if image_bytes is not None and image_bytes > max_image_gb * GB:
        raise JobFailed("image_too_large", f"{image_bytes / GB:.1f} GB > {max_image_gb:g} GB")
    need = max(min_free_gb * GB, 2 * (image_bytes or 0))
    if free_bytes < need:
        raise JobFailed("disk_low", f"{free_bytes / GB:.0f} GB free, need {need / GB:.0f} GB")
