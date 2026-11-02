#!/usr/bin/env bash
set -euo pipefail

for name in CSC_LINK CSC_KEY_PASSWORD APPLE_TEAM_ID APPLE_API_KEY APPLE_API_KEY_ID APPLE_API_ISSUER; do
    if [ -z "${!name:-}" ]; then
        echo "::error::$name is required for Developer ID distribution" >&2
        exit 1
    fi
done

umask 077
KEYCHAIN="$RUNNER_TEMP/autohand-signing.keychain-db"
KEYCHAIN_PASSWORD="$(uuidgen)"
CERTIFICATE="$RUNNER_TEMP/autohand-signing.p12"
NOTARY_KEY="$RUNNER_TEMP/AutohandNotary.p8"
trap 'rm -f "$CERTIFICATE"' EXIT

printf '%s' "$CSC_LINK" | base64 --decode > "$CERTIFICATE"
printf '%s' "$APPLE_API_KEY" > "$NOTARY_KEY"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -t 21600 -l "$KEYCHAIN"
security import "$CERTIFICATE" -k "$KEYCHAIN" -P "$CSC_KEY_PASSWORD" -T /usr/bin/codesign > /dev/null 2>&1
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" > /dev/null 2>&1
export AUTOHAND_CODESIGN_KEYCHAIN="$KEYCHAIN"
python3 - <<'PY'
import os
import shlex
import subprocess
keychain = os.environ['AUTOHAND_CODESIGN_KEYCHAIN']
current = shlex.split(subprocess.check_output(['security', 'list-keychains', '-d', 'user'], text=True))
if keychain not in current:
    subprocess.run(['security', 'list-keychains', '-d', 'user', '-s', *current, keychain], check=True)
PY

IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN" | sed -n "s/.*\"\(Developer ID Application: .* (${APPLE_TEAM_ID})\)\".*/\1/p")
if [ -z "$IDENTITY" ] || [ "$(printf '%s\n' "$IDENTITY" | wc -l | tr -d ' ')" -ne 1 ]; then
    echo "::error::Expected exactly one Developer ID Application identity for APPLE_TEAM_ID" >&2
    exit 1
fi
{
    printf 'AUTOHAND_CODESIGN_IDENTITY=%s\n' "$IDENTITY"
    printf 'AUTOHAND_CODESIGN_KEYCHAIN=%s\n' "$KEYCHAIN"
    printf 'APPLE_API_KEY_PATH=%s\n' "$NOTARY_KEY"
} >> "$GITHUB_ENV"
