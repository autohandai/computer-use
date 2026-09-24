#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUTPUT="${TMPDIR:-/tmp}/autohand-computer-use-host-test/Autohand Computer Use.app"
rm -rf "$(dirname "$OUTPUT")"
mkdir -p "$(dirname "$OUTPUT")"

AUTOHAND_BUILD_VERSION=0.9.9-alpha.test \
  "$ROOT/scripts/build-macos-host.sh" --output "$OUTPUT"

test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$OUTPUT/Contents/Info.plist")" = \
  'Autohand Computer Use'
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$OUTPUT/Contents/Info.plist")" = \
  'Autohand Computer Use'
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$OUTPUT/Contents/Info.plist")" = \
  'ai.autohand.computer-use'
/usr/bin/codesign --verify --deep --strict --verbose=2 "$OUTPUT"
