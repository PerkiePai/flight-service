import asyncio
import json

from flight_service.dockerctl import Docker, sh


class Rec:
    """Fake `run`: records argv, answers keyed by argv[1:3]."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def __call__(self, *argv, **kw):
        self.calls.append(list(argv))
        return self.answers.get(tuple(argv[1:3]), (0, ""))


def test_sh_returns_code_and_output_and_times_out():
    assert asyncio.run(sh("sh", "-c", "echo hi; exit 3")) == (3, "hi\n")
    code, out = asyncio.run(sh("sleep", "5", timeout=0.2))
    assert code == 124 and "timed out" in out


def test_docker_wrappers_name_exactly_one_thing():
    run = Rec({("image", "inspect"): (0, "12345\n"),
               ("ps", "-a"): (0, "submission-run-1\nsubmission-run-2\n"),
               ("manifest", "inspect"): (0, json.dumps({"SchemaV2Manifest": {"layers": [{"size": 3}]}}))})
    d = Docker(run)
    assert asyncio.run(d.exists("perkiepai/x:1")) is True
    assert asyncio.run(d.size("submission-x-1")) == 12345
    assert asyncio.run(d.containers_of("submission-x-1")) == ["submission-run-1", "submission-run-2"]
    assert asyncio.run(d.manifest_bytes("perkiepai/x:1", 5)) == 3
    asyncio.run(d.rmi("submission-x-1"))
    assert ["docker", "rmi", "submission-x-1"] in run.calls
    assert ["docker", "ps", "-a", "--filter", "ancestor=submission-x-1", "--format", "{{.Names}}"] in run.calls
    assert not any("prune" in c for call in run.calls for c in call)


def test_docker_failures_read_as_absent():
    d = Docker(Rec({("image", "inspect"): (1, "No such image"), ("manifest", "inspect"): (124, "timed out")}))
    assert asyncio.run(d.exists("perkiepai/x:1")) is False
    assert asyncio.run(d.size("perkiepai/x:1")) is None
    assert asyncio.run(d.manifest_bytes("perkiepai/x:1", 5)) is None


def test_exists_only_says_absent_when_docker_says_so():
    """A failed inspect that is not "No such image" must read as present, or
    cleanup would rmi a ref this job never brought in (design 7)."""
    absent = Docker(Rec({("image", "inspect"): (1, "Error: No such image: perkiepai/x:1")}))
    assert asyncio.run(absent.exists("perkiepai/x:1")) is False
    for code, out in [(124, "timed out after 30s"),
                      (1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"),
                      (1, "permission denied while trying to connect")]:
        d = Docker(Rec({("image", "inspect"): (code, out)}))
        assert asyncio.run(d.exists("perkiepai/x:1")) is True, out


def test_load_parses_what_was_loaded():
    out = "Loaded image: truck:1\nLoaded image ID: sha256:abc\n"
    d = Docker(Rec({("load", "-i"): (0, out)}))
    assert asyncio.run(d.load("/x.tar", 60)) == ["truck:1", "sha256:abc"]


def test_load_and_tag_failures_raise():
    import pytest
    from flight_service.jobs import JobFailed
    d = Docker(Rec({("load", "-i"): (1, "invalid tar header"), ("tag", "a"): (1, "no such image")}))
    for coro in (d.load("/x.tar", 60), d.tag("a", "b")):
        with pytest.raises(JobFailed) as e:
            asyncio.run(coro)
        assert e.value.reason == "load_failed"
