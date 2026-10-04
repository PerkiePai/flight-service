"""Settings from the environment -- one place for every limit and timeout
(design sections 5, 6, 8, 12, 13)."""
import os
from dataclasses import dataclass
from pathlib import Path

GB = 1024 ** 3

DEFAULT_ALLOWED = (r"^(docker\.io/)?perkiepai/[a-z0-9][a-z0-9_.-]*"
                   r"(:\w[\w.-]{0,127}|@sha256:[0-9a-f]{64})$")
DEFAULT_RUN_ARGS = ("--memory 24g --memory-swap 24g --pids-limit 1024 "
                    "--cap-drop ALL --security-opt no-new-privileges")
HERE = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    token: str
    drone_sitl_dir: Path
    runs_dir: Path
    host: str = "127.0.0.1"
    port: int = 8095
    allowed_images: tuple = (DEFAULT_ALLOWED,)
    max_image_gb: float = 16.0
    min_free_gb: float = 40.0
    docker_root: Path = Path("/var/lib/docker")
    max_pending: int = 1          # jobs waiting behind the running one (design 5)
    max_upload_gb: float = 16.0
    upload_idle_timeout_s: float = 60.0
    data_retention_gb: float = 10.0
    pull_timeout_s: float = 1800.0
    manifest_timeout_s: float = 30.0
    boot_timeout_s: float = 420.0
    px4_ready_timeout_s: float = 180.0
    arming_timeout_s: float = 90.0
    default_flight_s: int = 600
    max_flight_s: int = 900
    collect_timeout_s: float = 60.0
    cleanup_timeout_s: float = 120.0
    kill_wait_s: float = 60.0
    web_url: str = "http://127.0.0.1:8090"
    ws_url: str = "ws://127.0.0.1:8090/ws"
    video_url: str = "http://127.0.0.1:8080/"
    docker_run_args: str = DEFAULT_RUN_ARGS
    keep_image: bool = False
    site: str = "nt-testgs"

    @property
    def uploads_dir(self):
        return self.runs_dir.parent / "uploads"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        token = env.get("RUNNER_TOKEN", "")
        if len(token) < 32:
            raise SystemExit("RUNNER_TOKEN must be set and at least 32 characters")

        def num(name, default, kind=float):
            return kind(env.get(name, default))

        return cls(
            token=token,
            drone_sitl_dir=Path(env.get("DRONE_SITL_DIR", Path.home() / "pai" / "drone-sitl")),
            runs_dir=Path(env.get("RUNS_DIR", HERE / "data" / "runs")),
            host=env.get("RUNNER_HOST", "127.0.0.1"),
            port=num("RUNNER_PORT", 8095, int),
            allowed_images=tuple(env.get("ALLOWED_IMAGES", DEFAULT_ALLOWED).split()),
            max_image_gb=num("MAX_IMAGE_GB", 16.0),
            min_free_gb=num("MIN_FREE_GB", 40.0),
            docker_root=Path(env.get("DOCKER_ROOT", "/var/lib/docker")),
            max_pending=num("MAX_PENDING", 1, int),
            max_upload_gb=num("MAX_UPLOAD_GB", 16.0),
            upload_idle_timeout_s=num("UPLOAD_IDLE_TIMEOUT_S", 60.0),
            data_retention_gb=num("DATA_RETENTION_GB", 10.0),
            pull_timeout_s=num("PULL_TIMEOUT_S", 1800.0),
            manifest_timeout_s=num("MANIFEST_TIMEOUT_S", 30.0),
            boot_timeout_s=num("BOOT_TIMEOUT_S", 420.0),
            px4_ready_timeout_s=num("PX4_READY_TIMEOUT_S", 180.0),
            arming_timeout_s=num("ARMING_TIMEOUT_S", 90.0),
            default_flight_s=num("DEFAULT_FLIGHT_S", 600, int),
            max_flight_s=num("MAX_FLIGHT_S", 900, int),
            collect_timeout_s=num("COLLECT_TIMEOUT_S", 60.0),
            cleanup_timeout_s=num("CLEANUP_TIMEOUT_S", 120.0),
            kill_wait_s=num("KILL_WAIT_S", 60.0),
            docker_run_args=env.get("DRONE_SITL_DOCKER_RUN_ARGS", DEFAULT_RUN_ARGS),
            keep_image=env.get("KEEP_IMAGE", "0") == "1",
            site=env.get("SITE", "nt-testgs"),
        )
