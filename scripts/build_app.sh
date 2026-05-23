#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Building the macOS .app requires macOS." >&2
  exit 1
fi

ARTIFACT_ROOT="${ANON_ARTIFACT_ROOT:-$HOME/.briefcase-out/pdf-md-anonymizer}"
BUILD_DIR="$ARTIFACT_ROOT/build"

bash scripts/link_artifacts.sh

# Step 1: scaffold the .app bundle. Always wipe and recreate the .app dir
# (not the parent BUILD_DIR — the support layer there is cached and slow to
# rebuild). `briefcase build` alone does NOT regenerate Info.plist, and
# `briefcase update` is inconsistent across versions about whether it
# refreshes the plist either; only `briefcase create` reliably writes a
# fresh Info.plist from pyproject's [tool.briefcase.app.X.macOS].info_plist
# table. Doing this on every build keeps custom Info.plist keys (e.g. the
# ProjectHomepageURL UI-023 surfaces via NSBundle at runtime) in sync with
# pyproject without forcing the user to remember a manual step.
rm -rf "$BUILD_DIR/anonymizer-ui/macos/app/PDF-MD Anonymizer.app"
uvx briefcase create macOS

# Step 2: compile the app. Strip numpy ad-hoc signatures first — Briefcase's
# signing step otherwise races against numpy's `.cstemp` extension files and
# fails with `resource fork, Finder information, or similar detritus`.
find "$BUILD_DIR" -name '*.so' -path '*/numpy/*' \
  -exec codesign --remove-signature {} \; 2>/dev/null || true

uvx briefcase build macOS

echo "Built $BUILD_DIR/anonymizer-ui/macos/app/PDF-MD Anonymizer.app"
