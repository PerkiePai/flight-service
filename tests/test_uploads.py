import asyncio

import pytest

from flight_service.uploads import UploadError, receive


async def chunks(*parts):
    for p in parts:
        yield p


def test_receive_writes_exactly_the_declared_bytes(tmp_path):
    dest = tmp_path / "u" / "a.tar"
    assert asyncio.run(receive(chunks(b"abc", b"de"), dest, 5, 100)) == 5
    assert dest.read_bytes() == b"abcde" and not list(tmp_path.glob("u/*.part"))


@pytest.mark.parametrize("parts,expected,limit,status", [
    ((b"abc",), 5, 100, 400),          # short
    ((b"abcdef",), 5, 100, 413),       # longer than declared
    ((b"abcdef",), 10, 4, 413),        # over the limit
])
def test_receive_rejects_and_leaves_nothing(tmp_path, parts, expected, limit, status):
    dest = tmp_path / "a.tar"
    with pytest.raises(UploadError) as e:
        asyncio.run(receive(chunks(*parts), dest, expected, limit))
    assert e.value.status == status and list(tmp_path.iterdir()) == []


def test_a_stalled_upload_times_out(tmp_path):
    async def stalls():
        yield b"abc"
        await asyncio.sleep(5)
        yield b"de"

    with pytest.raises(UploadError) as e:
        asyncio.run(receive(stalls(), tmp_path / "a.tar", 5, 100, idle_timeout_s=0.05))
    assert e.value.status == 408 and list(tmp_path.iterdir()) == []
