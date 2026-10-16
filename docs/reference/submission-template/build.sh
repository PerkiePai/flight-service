#!/usr/bin/env bash
# Pack the files the image needs into <name>.tar (the tar name = the image name).
#   ./build.sh my-agent
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
NAME=${1:?usage: ./build.sh <name>}
FILES=(Dockerfile .dockerignore my_agent.py detection.py)   # add requirements.txt, weights.pt, other dirs
tar -cf "$NAME.tar" "${FILES[@]}"
echo "$NAME.tar: $(du -h "$NAME.tar" | cut -f1)"
