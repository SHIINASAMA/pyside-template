#!/usr/bin/env bash
# 生成 Sparkle 2 appcast.xml 并 EdDSA 签名（参考 wifi-lens .github/workflows/release.yml）。
#
# 用法:
#   scripts/generate_appcast.sh <更新包目录> <app名称> <版本号> [发布tag]
#   例:  scripts/generate_appcast.sh release/appcast-src App 0.1.0 v0.1.0
#
# enclosure URL = ${SPARKLE_APPCAST_BASE_URL}/${TAG}/<文件>  （末尾斜杠必须加）
# 默认 SPARKLE_APPCAST_BASE_URL = https://github.com/SHIINASAMA/pyside-template/releases/download
#
# 私钥来源（按优先级）:
#   1. $SPARKLE_PRIVATE_KEY 环境变量：为私钥内容（PEM/base64），会写入临时文件 --ed-key-file
#   2. $SPARKLE_PRIVATE_KEY 指向一个存在的文件路径
#   3. 本机 $HOME/.config/pyside-template/sparkle/ed25519_private_key.pem
set -euo pipefail

ARCHIVES_DIR="${1:?Update archives directory required}"
APP_NAME="${2:?App name required}"
VERSION="${3:?Version required}"
TAG="${4:-v${VERSION}}"
SPARKLE_VERSION="${SPARKLE_VERSION:-2.9.6}"
BASE_URL="${SPARKLE_APPCAST_BASE_URL:-https://github.com/SHIINASAMA/pyside-template/releases/download}"
TOOLS_CACHE="${HOME}/.cache/pyside-template/sparkle-tools/bin"
OUT="${ARCHIVES_DIR}/appcast.xml"

# --- 解析私钥 ---
TMP_KEY=""
if [ -n "${SPARKLE_PRIVATE_KEY:-}" ]; then
  if [ -f "${SPARKLE_PRIVATE_KEY}" ]; then
    PRIVATE_KEY="${SPARKLE_PRIVATE_KEY}"
  else
    # 内容是密钥本体（PEM / base64），写入临时文件
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
  echo "私钥不存在: $PRIVATE_KEY  (请设置 SPARKLE_PRIVATE_KEY，或先运行 generate_keys 导出)" >&2
  exit 1
fi

download_tools() {
  if [ -x "${TOOLS_CACHE}/generate_appcast" ]; then
    echo "使用已缓存工具: ${TOOLS_CACHE}/generate_appcast"
    return
  fi
  echo "下载 Sparkle ${SPARKLE_VERSION} 工具到 ${TOOLS_CACHE} ..."
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

echo "生成 appcast（version=${VERSION}, tag=${TAG}, prefix=${URL_PREFIX}）"
"${TOOLS_CACHE}/generate_appcast" \
  --ed-key-file "$PRIVATE_KEY" \
  --download-url-prefix "$URL_PREFIX" \
  -o "$OUT" \
  "$ARCHIVES_DIR"

echo "已生成: $OUT"
