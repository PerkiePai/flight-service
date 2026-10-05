#!/usr/bin/env bash
# vendor-drone-sitl.sh -- copy the drone-sitl files flight-service runs on
# into vendor/drone-sitl/, from one commit of a drone-sitl checkout.
#
#   ./scripts/vendor-drone-sitl.sh <drone-sitl checkout> [commit]    (default HEAD)
#
# Takes only the paths in vendor/drone-sitl.manifest, from the commit (never
# the working tree), applies vendor/patches/drone-sitl/*.patch in name order,
# writes VENDORED (source commit + patches), then syncs the result over the
# copy. Runtime output inside the copy -- logs/, recordings/, .cache/,
# sim/secrets.env -- is kept. Nothing changes if any step fails.
# VENDOR_DIR, VENDOR_MANIFEST, VENDOR_PATCHES move the inputs (tests).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: vendor-drone-sitl.sh <drone-sitl checkout> [commit]"
SRC="${1:?$USAGE}"
REV="${2:-HEAD}"
DEST="${VENDOR_DIR:-$DIR/vendor/drone-sitl}"
MANIFEST="${VENDOR_MANIFEST:-$DIR/vendor/drone-sitl.manifest}"
PATCHES="${VENDOR_PATCHES:-$DIR/vendor/patches/drone-sitl}"
say() { echo "vendor-drone-sitl: $*"; }
die() { echo "vendor-drone-sitl: $*" >&2; exit 1; }

COMMIT="$(git -C "$SRC" rev-parse --verify --quiet "$REV^{commit}")" \
    || die "no commit '$REV' in $SRC"
mapfile -t PATHS < <(grep -vE '^[[:space:]]*(#|$)' "$MANIFEST")
(( ${#PATHS[@]} )) || die "nothing listed in $MANIFEST"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git -C "$SRC" archive "$COMMIT" -- "${PATHS[@]}" | tar -x -C "$TMP" \
    || die "git archive failed -- is every path in $MANIFEST in ${COMMIT:0:7}?"

# patch(1), not git apply: $TMP is not a repo, and git apply would look for one.
APPLIED=()
shopt -s nullglob
for p in "$PATCHES"/*.patch; do
    patch -p1 --batch --forward --fuzz=0 --no-backup-if-mismatch -s -d "$TMP" -i "$p" \
        || die "$(basename "$p") does not apply to ${COMMIT:0:7} -- update the patch first"
    APPLIED+=("$(basename "$p")")
done

{
    echo "source_commit=$COMMIT"
    echo "source_subject=$(git -C "$SRC" log -1 --format=%s "$COMMIT")"
    echo "vendored_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "patches=${APPLIED[*]}"
} > "$TMP/VENDORED"

mkdir -p "$DEST"
rsync -a --delete --exclude=/logs/ --exclude=/recordings/ --exclude=/.cache/ \
    --exclude=/sim/secrets.env --exclude=__pycache__/ --exclude='/NvStreamer-*.etli' \
    "$TMP/" "$DEST/"
say "$DEST <- ${COMMIT:0:7} (${#PATHS[@]} paths, ${#APPLIED[@]} patches)"
