"""scripts/vendor-map.sh against a fake map_setup_tool output."""
import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vendor-map.sh"
STAGE = """#usda 1.0
(
    customLayerData = { string input = "/home/someone/Tiger/base.usdc" }
    subLayers = [
        @./drone_map_physics.usdc@,
        @../base.usdc@
    ]
)
def "A" ( prepend payload = @../../Downloads/Truck.usd@ ) {}
def "B" ( prepend payload = @../../Downloads/Truck.usd@ ) {}
"""


@pytest.fixture
def src(tmp_path):
    out = tmp_path / "Tiger" / "out"
    out.mkdir(parents=True)
    (out / "drone_map.usda").write_text(STAGE)
    (out / "drone_map_physics.usdc").write_bytes(b"physics")
    (out / "drone_map_vehicles.json").write_text('{"trucks": []}')
    (tmp_path / "Tiger" / "base.usdc").write_bytes(b"base")
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "Truck.usd").write_bytes(b"truck")
    return out


def vendor_map(tmp_path, src, site="m"):
    env = {**os.environ, "VENDOR_MAPS_DIR": str(tmp_path / "maps")}
    r = subprocess.run(["bash", str(SCRIPT), site, str(src)], env=env,
                       capture_output=True, text=True)
    return r, tmp_path / "maps" / site


def test_copies_the_folder_and_every_referenced_layer_flat(tmp_path, src):
    r, dest = vendor_map(tmp_path, src)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir()) == [
        "SHA256SUMS", "Truck.usd", "base.usdc", "drone_map.usda",
        "drone_map_physics.usdc", "drone_map_vehicles.json"]
    assert (dest / "Truck.usd").read_bytes() == b"truck"


def test_references_point_inside_the_folder(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    refs = re.findall(r"@([^@]+)@", (dest / "drone_map.usda").read_text())
    assert sorted(set(refs)) == ["./Truck.usd", "./base.usdc", "./drone_map_physics.usdc"]
    assert all((dest / r).is_file() for r in refs)


def test_sha256sums_covers_every_file_and_verifies(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    names = [line.split(None, 1)[1] for line in (dest / "SHA256SUMS").read_text().splitlines()]
    assert sorted(names) == sorted(p.name for p in dest.iterdir() if p.name != "SHA256SUMS")
    assert subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=dest).returncode == 0


def test_a_missing_layer_fails_and_keeps_the_old_copy(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    (tmp_path / "Tiger" / "base.usdc").unlink()
    r, dest = vendor_map(tmp_path, src)
    assert r.returncode != 0 and "base.usdc" in r.stderr
    assert (dest / "base.usdc").read_bytes() == b"base"
    assert [p.name for p in dest.parent.iterdir()] == ["m"]          # no temp dir left


def test_two_different_layers_with_one_name_fail(tmp_path, src):
    (tmp_path / "Other").mkdir()
    (tmp_path / "Other" / "base.usdc").write_bytes(b"different")
    (src / "drone_map.usda").write_text(STAGE.replace("@./drone_map_physics.usdc@",
                                                      "@../../Other/base.usdc@"))
    r, dest = vendor_map(tmp_path, src)
    assert r.returncode != 0 and "base.usdc" in r.stderr and not dest.exists()


def test_the_copy_is_readable_by_others(tmp_path, src):
    _, dest = vendor_map(tmp_path, src)
    assert dest.stat().st_mode & 0o755 == 0o755
