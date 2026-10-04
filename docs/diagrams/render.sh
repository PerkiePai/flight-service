#!/usr/bin/env bash
# render.sh -- turn every *.mmd here into a PNG (needs Docker only).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
for f in *.mmd; do
    docker run --rm -u "$(id -u):$(id -g)" -v "$PWD":/data -v /usr/share/fonts:/usr/share/fonts/host:ro \
        minlag/mermaid-cli -i "$f" -o "${f%.mmd}.png" -c mermaid-config.json -s 2 -b white >/dev/null
    echo "rendered ${f%.mmd}.png"
done
