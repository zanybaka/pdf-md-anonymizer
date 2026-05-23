#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Running .app bundles requires macOS." >&2
  exit 1
fi

ARTIFACT_ROOT="${ANON_ARTIFACT_ROOT:-$HOME/.briefcase-out/pdf-md-anonymizer}"
APP="$ARTIFACT_ROOT/build/anonymizer-ui/macos/app/PDF-MD Anonymizer.app"

if [[ ! -d "$APP" ]]; then
  bash scripts/build_app.sh
else
  bash scripts/link_artifacts.sh
fi

open "$APP"
