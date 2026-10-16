# Submission template

Files that must be in the folder before `docker build` (everything the Dockerfile COPYs):

| file | needed | what it is |
|---|---|---|
| `Dockerfile` | yes | `FROM competition-base:latest`, COPY, ENTRYPOINT |
| `my_agent.py` | yes | exactly one `class X(Agent)` |
| `detection.py` | yes (it is imported) | your model; this stub finds nothing |
| `.dockerignore` | no | keeps `*.tar`, `*.md`, `build.sh` out of the build context |
| `requirements.txt`, `weights.pt`, helper dirs | only if used | add a COPY line for each |

`README.md` and `build.sh` are for you; they do not go in the image.

## Build and test
```bash
# once: the base image
(cd vendor/drone-sitl && docker build -t competition-base:latest -f docker/competition-base/Dockerfile .)

# your image
docker build -t my-agent docs/reference/submission-template

# or a bundle to upload (kind=bundle, <= 200 MB, regular files only)
docs/reference/submission-template/build.sh my-agent
scripts/flight.py run --file docs/reference/submission-template/my-agent.tar --kind bundle --name my-agent
```
