"""The docker CLI, only for what the runner itself must do (pull and
bundle builds go through drone-sitl's :8090). Never `prune`, never a
pattern: every call names one image or one container (trap 6)."""
import asyncio

from . import policy
from .jobs import JobFailed


async def sh(*argv, timeout=60.0, env=None, cwd=None):
    """Run argv; (exit code, combined output). 124 on timeout. The child is
    killed if we time out or are cancelled."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=env, cwd=cwd)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        return 124, f"timed out after {timeout:.0f}s"
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return proc.returncode, out.decode(errors="replace")


def tail(text, n=8):
    return "\n".join((text or "").strip().splitlines()[-n:])


class Docker:
    def __init__(self, run=sh):
        self.run = run

    async def exists(self, ref):
        """False only when docker says the image is not there. Any other
        failure (timeout, daemon down) reads as present, so cleanup never
        removes a ref it cannot prove this job brought in (design 7)."""
        code, out = await self.run("docker", "image", "inspect", ref, timeout=30)
        return code == 0 or "no such image" not in out.lower()

    async def manifest_bytes(self, ref, timeout):
        code, out = await self.run("docker", "manifest", "inspect", "-v", ref, timeout=timeout)
        return policy.manifest_bytes(out) if code == 0 else None

    async def size(self, ref):
        code, out = await self.run("docker", "image", "inspect", "--format", "{{.Size}}", ref, timeout=30)
        try:
            return int(out.strip()) if code == 0 else None
        except ValueError:
            return None

    async def containers_of(self, image_tag):
        code, out = await self.run("docker", "ps", "-a", "--filter", f"ancestor={image_tag}",
                                   "--format", "{{.Names}}", timeout=30)
        return out.split() if code == 0 else []

    async def rm_force(self, name):
        await self.run("docker", "rm", "-f", name, timeout=30)

    async def rmi(self, ref):
        code, _ = await self.run("docker", "rmi", ref, timeout=120)
        return code == 0

    async def load(self, path, timeout):
        """docker load -i; what it loaded (names, or image IDs if untagged)."""
        code, out = await self.run("docker", "load", "-i", str(path), timeout=timeout)
        if code != 0:
            raise JobFailed("load_failed", tail(out))
        loaded = []
        for line in out.splitlines():
            for prefix in ("Loaded image ID: ", "Loaded image: "):
                if line.startswith(prefix):
                    loaded.append(line[len(prefix):].strip())
                    break
        return loaded

    async def tag(self, src, dst):
        code, out = await self.run("docker", "tag", src, dst, timeout=30)
        if code != 0:
            raise JobFailed("load_failed", tail(out))
