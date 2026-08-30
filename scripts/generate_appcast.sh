#!/usr/bin/env bash
# Generate Sparkle 2 appcast.xml with EdDSA signing (ref: wifi-lens release.yml).
#
# Usage:
#   scripts/generate_appcast.sh <archives-dir> <app-name> <version> [release-tag]
#   e.g. scripts/generate_appcast.sh release/appcast-src App 0.1.0 v0.1.0
#
# enclosure URL = ${SPARKLE_APPCAST_BASE_URL}/${TAG}/<file> (trailing slash REQUIRED)
# default SPARKLE_APPCAST_BASE_URL = https://github.com/SHIINASAMA/pyside-template/releases/download
#
# private key source (priority):
#   1. $SPARKLE_PRIVATE_KEY env var: key content (PEM/base64), written to temp file for --ed-key-file
#   2. $SPARKLE_PRIVATE_KEY points to an existing file path
#   3. local $HOME/.config/pyside-template/sparkle/ed25519_private_key.pem
set -euo pipefail

ARCHIVES_DIR="${1:?Update archives directory required}"
APP_NAME="${2:?App name required}"
VERSION="${3:?Version required}"
TAG="${4:-v${VERSION}}"
SPARKLE_VERSION="${SPARKLE_VERSION:-2.9.6}"
BASE_URL="${SPARKLE_APPCAST_BASE_URL:-https://github.com/SHIINASAMA/pyside-template/releases/download}"
TOOLS_CACHE="${HOME}/.cache/pyside-template/sparkle-tools/bin"
OUT="${ARCHIVES_DIR}/appcast.xml"

# --- resolve private key ---
TMP_KEY=""
if [ -n "${SPARKLE_PRIVATE_KEY:-}" ]; then
  if [ -f "${SPARKLE_PRIVATE_KEY}" ]; then
    PRIVATE_KEY="${SPARKLE_PRIVATE_KEY}"
  else
    # key content is the secret itself (PEM/base64); write to temp file
    TMP_KEY="$(mktemp -t sparkle-edkey).pem"
    printf '%s' "${SPARKLE_PRIVATE_KEY}" > "$TMP_KEY"
    PRIVATE_KEY="$TMP_KEY"
  fi
else
  PRIVATE_KEY="${HOME}/.config/pyside-template/sparkle/ed25519_private_key.pem"
fi

cleanup() { [ -n "${TMP_KEY}" ] && python3 -c "import os; os.unlink('${TMP_KEY}')" 2>/dev/null || true; }
trap cleanup EXIT

if [ ! -f "$PRIVATE_KEY" ]; then
  echo "private key not found: $PRIVATE_KEY (set SPARKLE_PRIVATE_KEY, or run generate_keys first)" >&2
  exit 1
fi

download_tools() {
  if [ -x "${TOOLS_CACHE}/generate_appcast" ]; then
    echo "using cached tool: ${TOOLS_CACHE}/generate_appcast"
    return
  fi
  echo "downloading Sparkle ${SPARKLE_VERSION} tools to ${TOOLS_CACHE} ..."
  mkdir -p "${TOOLS_CACHE}"
  tmp_archive="$(mktemp -t sparkle-tools).tar.xz"
  curl -fsSL "https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/Sparkle-${SPARKLE_VERSION}.tar.xz" -o "$tmp_archive"
  tar -xJf "$tmp_archive" -C "$(dirname "${TOOLS_CACHE}")" 2>/dev/null \
    || tar -xzf "$tmp_archive" -C "$(dirname "${TOOLS_CACHE}")"
  find "$(dirname "${TOOLS_CACHE}")" -name generate_appcast -type f -perm -111 -exec cp {} "${TOOLS_CACHE}/" \;
  find "$(dirname "${TOOLS_CACHE}")" -name sign_update -type f -perm -111 -exec cp {} "${TOOLS_CACHE}/" \;
  chmod +x "${TOOLS_CACHE}"/generate_appcast "${TOOLS_CACHE}"/sign_update 2>/dev/null || true
  python3 -c "import os; os.unlink('$tmp_archive')" 2>/dev/null || true
}

download_tools

URL_PREFIX="${BASE_URL}/${TAG}/"

echo "generating appcast (version=${VERSION}, tag=${TAG}, prefix=${URL_PREFIX})"
"${TOOLS_CACHE}/generate_appcast" \
  --ed-key-file "$PRIVATE_KEY" \
  --download-url-prefix "$URL_PREFIX" \
  -o "$OUT" \
  "$ARCHIVES_DIR"

echo "generated: $OUT"
