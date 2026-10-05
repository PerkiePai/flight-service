#!/usr/bin/env bash
# vendor-map.sh -- copy a map_setup_tool stage into vendor/maps/<site>/ so it
# needs nothing outside that folder: every file in the output dir, plus every
# file drone_map.usda points at (@...@), flat, with those references rewritten
# to ./<name>. Writes SHA256SUMS (scripts/preflight.sh checks it).
#
#   ./scripts/vendor-map.sh <site> <map_setup_output_dir>
#   ./scripts/vendor-map.sh nt-testgs ~/Tiger/map_setup_output_nt_testgs
#
# Only drone_map.usda's own references are followed; check the copy has no
# deeper ones with Isaac's pxr (vendor/README.md, "map").
# VENDOR_MAPS_DIR moves the target (tests).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: vendor-map.sh <site> <map_setup_output_dir>"
SITE="${1:?$USAGE}"
SRC="$(realpath -e "${2:?$USAGE}")"
MAPS="${VENDOR_MAPS_DIR:-$DIR/vendor/maps}"
DEST="$MAPS/$SITE"
STAGE="drone_map.usda"
say() { echo "vendor-map: $*"; }
die() { echo "vendor-map: $*" >&2; exit 1; }

[[ -f "$SRC/$STAGE" ]] || die "no $STAGE in $SRC"
mkdir -p "$MAPS"
TMP="$(mktemp -d "$MAPS/.$SITE.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
find "$SRC" -maxdepth 1 -type f -exec cp -p {} "$TMP/" \;

mapfile -t REFS < <(grep -oE '@[^@]+@' "$SRC/$STAGE" | tr -d @ | sort -u)
for ref in "${REFS[@]}"; do
    [[ "$ref" == /* ]] && from="$ref" || from="$SRC/$ref"
    from="$(realpath -e "$from" 2>/dev/null)" || die "$STAGE points at $ref, which does not exist"
    [[ "$(dirname "$from")" == "$SRC" ]] && continue            # copied with the folder
    name="$(basename "$from")"
    if [[ -e "$TMP/$name" ]]; then
        cmp -s "$from" "$TMP/$name" && continue                 # same file, another path
        die "two different layers named $name -- cannot put them in one folder"
    fi
    cp -p "$from" "$TMP/$name"
done
sed -i -E 's#@([^@]*/)?([^/@]+)@#@./\2@#g' "$TMP/$STAGE"
(cd "$TMP" && find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' \
    | LC_ALL=C sort | xargs -d '\n' sha256sum > SHA256SUMS)

chmod 755 "$TMP"                    # mktemp -d makes it 700
rm -rf "$DEST"
mv "$TMP" "$DEST"
trap - EXIT
say "$DEST <- $SRC ($(ls "$DEST" | wc -l) files, $(du -sh "$DEST" | cut -f1))"
