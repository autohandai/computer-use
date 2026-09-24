#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUTPUT="$ROOT/dist/Autohand Computer Use.app"
VERSION="${AUTOHAND_BUILD_VERSION:-0.0.0}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 64
            ;;
    esac
done

PLIST_VERSION="${VERSION%%-*}"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "Autohand Computer Use can only be built on macOS." >&2
    exit 1
fi

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/autohand-computer-use.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
APP="$STAGING/Autohand Computer Use.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

/usr/bin/swiftc -O \
    "$ROOT/macos/main.swift" \
    -module-cache-path "$STAGING/module-cache" \
    -framework ApplicationServices \
    -framework CoreGraphics \
    -o "$APP/Contents/MacOS/AutohandComputerUse"

cp "$ROOT/assets/icon.png" "$APP/Contents/Resources/AutohandComputerUse.png"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key><string>Autohand Computer Use</string>
    <key>CFBundleExecutable</key><string>AutohandComputerUse</string>
    <key>CFBundleIconFile</key><string>AutohandComputerUse.png</string>
    <key>CFBundleIdentifier</key><string>ai.autohand.computer-use</string>
    <key>CFBundleName</key><string>Autohand Computer Use</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${PLIST_VERSION}</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSAccessibilityUsageDescription</key><string>Autohand uses Accessibility to operate applications you ask it to control.</string>
    <key>NSScreenCaptureUsageDescription</key><string>Autohand uses Screen Recording to see and verify applications you ask it to control.</string>
</dict>
</plist>
PLIST

SIGN_IDENTITY="${AUTOHAND_CODESIGN_IDENTITY:--}"
/usr/bin/codesign --force --deep --sign "$SIGN_IDENTITY" --timestamp=none "$APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"

mkdir -p "$(dirname "$OUTPUT")"
rm -rf "$OUTPUT"
mv "$APP" "$OUTPUT"
echo "$OUTPUT"
