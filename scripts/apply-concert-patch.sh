#!/bin/bash
set -euo pipefail

PATCH_DIR="concert-patches"
APPLIED=0

echo "============================================"
echo "  IBM Concert Patch Application"
echo "============================================"

# 1. Apply git patches (.patch files)
for patch in "$PATCH_DIR"/*.patch; do
  [ -f "$patch" ] || continue
  echo "[PATCH] Applying: $patch"
  git apply "$patch"
  APPLIED=$((APPLIED + 1))
done

# 2. Base image override (python-app)
if [ -f "$PATCH_DIR/python-base-image.txt" ]; then
  NEW_BASE=$(cat "$PATCH_DIR/python-base-image.txt" | tr -d '[:space:]')
  echo "[IMAGE] Overriding Python base image to: $NEW_BASE"
  sed -i'' -e "s|^FROM python:.*|FROM $NEW_BASE|g" python-app/Dockerfile
  APPLIED=$((APPLIED + 1))
fi

# 3. Base image override (java-app)
if [ -f "$PATCH_DIR/java-base-image.txt" ]; then
  NEW_BASE=$(cat "$PATCH_DIR/java-base-image.txt" | tr -d '[:space:]')
  echo "[IMAGE] Overriding Java base image to: $NEW_BASE"
  sed -i'' -e "s|^FROM eclipse-temurin:.*|FROM $NEW_BASE|g" java-app/Dockerfile
  APPLIED=$((APPLIED + 1))
fi

# 4. Python requirements override
if [ -f "$PATCH_DIR/requirements-override.txt" ]; then
  echo "[DEPS] Overriding Python requirements"
  cp "$PATCH_DIR/requirements-override.txt" python-app/requirements.txt
  APPLIED=$((APPLIED + 1))
fi

# 5. Java pom.xml dependency version updates
if [ -f "$PATCH_DIR/pom-versions.json" ]; then
  echo "[DEPS] Applying Java dependency version updates"
  # Format: {"groupId:artifactId": "newVersion", ...}
  while IFS='=' read -r dep version; do
    dep=$(echo "$dep" | tr -d '"{}[:space:]')
    version=$(echo "$version" | tr -d '",[:space:]')
    [ -z "$dep" ] && continue
    echo "  Updating $dep -> $version"
  done < <(cat "$PATCH_DIR/pom-versions.json" | tr ',' '\n' | tr ':' '=')
  APPLIED=$((APPLIED + 1))
fi

echo "============================================"
echo "  $APPLIED Concert patches applied"
echo "============================================"
