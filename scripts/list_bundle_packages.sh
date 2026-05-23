#!/usr/bin/env bash
# Print every package shipped in the built .app bundle, with its version and
# license, so `Third party notices.txt` can be cross-checked against reality.
#
# Run after `scripts/build_app.sh` succeeds. Output is the source of truth for
# the notices file — any new line here must appear in `Third party notices.txt`
# before the next release.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_ROOT="${ANON_ARTIFACT_ROOT:-$HOME/.briefcase-out/pdf-md-anonymizer}"
APP_PKGS="$ARTIFACT_ROOT/build/anonymizer-ui/macos/app/PDF-MD Anonymizer.app/Contents/Resources/app_packages"

if [[ ! -d "$APP_PKGS" ]]; then
  echo "Bundle not found at: $APP_PKGS" >&2
  echo "Run scripts/build_app.sh first." >&2
  exit 1
fi

printf "%-26s %-22s %s\n" "Package" "Version" "License"
printf "%-26s %-22s %s\n" "-------" "-------" "-------"
for dist in "$APP_PKGS"/*.dist-info; do
  meta="$dist/METADATA"
  [[ -f "$meta" ]] || continue
  pkg="$(grep -m1 "^Name:" "$meta" | sed 's/^Name: //')"
  ver="$(grep -m1 "^Version:" "$meta" | sed 's/^Version: //')"
  expr="$(grep -m1 "^License-Expression:" "$meta" | sed 's/^License-Expression: //' || true)"
  lic="$(grep -m1 "^License:" "$meta" | sed 's/^License: //' || true)"
  classifier="$(grep "^Classifier: License" "$meta" | head -1 | sed 's/^Classifier: License :: OSI Approved :: //' | sed 's/^Classifier: License :: //' || true)"

  if [[ -n "${expr:-}" ]]; then
    license="$expr"
  elif [[ -n "${lic:-}" && "$lic" != "UNKNOWN" ]]; then
    license="$lic"
  else
    license="${classifier:-?}"
  fi
  printf "%-26s %-22s %s\n" "$pkg" "$ver" "$license"
done | sort
