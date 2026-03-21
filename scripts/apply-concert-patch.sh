#!/bin/bash
set -euo pipefail

PATCH_DIR="concert-patches"

echo "Applying IBM Concert patches..."

for patch in "$PATCH_DIR"/*.patch; do
  [ -f "$patch" ] || continue
  echo "  Applying: $patch"
  git apply "$patch"
done

# If Concert delivers Dockerfile overlays or image base updates
if [ -f "$PATCH_DIR/base-image-override.txt" ]; then
  NEW_BASE=$(cat "$PATCH_DIR/base-image-override.txt")
  echo "  Overriding base image to: $NEW_BASE"
  sed -i "1s|^FROM .*|FROM $NEW_BASE|" python-app/Dockerfile
fi

echo "Concert patches applied."
