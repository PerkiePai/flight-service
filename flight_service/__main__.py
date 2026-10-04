"""python -m flight_service -- everything wired for real."""
import logging

import uvicorn

from .app import create_app
from .config import Settings
from .dockerctl import Docker
from .jobs import JobStore
from .sim import SimControl
from .sitl import Sitl
from .worker import Worker


def build(settings):
    store = JobStore(settings.runs_dir)
    worker = Worker(settings, store, Docker(), SimControl(settings), Sitl(settings.web_url))
    return create_app(settings, store, worker)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    uvicorn.run(build(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
