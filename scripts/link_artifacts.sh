#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ARTIFACT_ROOT="${ANON_ARTIFACT_ROOT:-$HOME/.briefcase-out/pdf-md-anonymizer}"
mkdir -p "$ARTIFACT_ROOT/build" "$ARTIFACT_ROOT/dist"

link_artifact_dir() {
  local name="$1"
  local target="$ARTIFACT_ROOT/$name"
  local candidate

  if [[ -L "$name" ]]; then
    return
  fi

  for candidate in "$name "[0-9]*; do
    [[ -L "$candidate" ]] || continue
    if [[ "$(readlink "$candidate")" == "$target" ]]; then
      mv "$candidate" "$name"
      return
    fi
  done

  if [[ -d "$name" ]]; then
    shopt -s dotglob nullglob
    mv "$name"/* "$target"/ 2>/dev/null || true
    shopt -u dotglob nullglob
    rmdir "$name"
  elif [[ -e "$name" ]]; then
    echo "$name exists and is not a directory or artifact symlink." >&2
    exit 1
  fi

  ln -s "$target" "$name"
}

link_artifact_dir build
link_artifact_dir dist
