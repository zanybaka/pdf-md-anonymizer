#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "DMG builds require macOS." >&2
  exit 1
fi

ARTIFACT_ROOT="${ANON_ARTIFACT_ROOT:-$HOME/.briefcase-out/pdf-md-anonymizer}"
DIST_DIR="$ARTIFACT_ROOT/dist"
APP_NAME="PDF-MD Anonymizer.app"
APP="$ARTIFACT_ROOT/build/anonymizer-ui/macos/app/$APP_NAME"

bash scripts/build_app.sh

# Ad-hoc sign the freshly built bundle. Briefcase's own `package` step would
# also do this, but we skip `briefcase package` so we can build the DMG by
# hand below (briefcase's DMG only contains the .app + Applications symlink
# and there is no supported hook to add First Launch.txt / Third party notices).
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP"

VERSION="$(grep -E '^version\s*=' pyproject.toml | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/')"
DMG="$DIST_DIR/PDF-MD Anonymizer-${VERSION}.dmg"
STAGING_DIR="$DIST_DIR/dmg-staging"

mkdir -p "$DIST_DIR"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -R "$APP" "$STAGING_DIR/"
cp "First Launch.txt" "$STAGING_DIR/"
cp "Third party notices.txt" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

rm -f "$DMG"
hdiutil create \
  -volname "PDF-MD Anonymizer" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG"
rm -rf "$STAGING_DIR"

echo "Built $DMG"
