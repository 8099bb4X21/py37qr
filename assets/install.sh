#!/bin/bash
# qr_tool 安装脚本：无需 root，全部装进当前用户家目录。
# 用法：解压产物后执行 bash install.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"
cp -f "$SRC_DIR/qr_tool" "$BIN_DIR/qr_tool"
chmod +x "$BIN_DIR/qr_tool"
cp -f "$SRC_DIR/qr_tool.svg" "$ICON_DIR/qr_tool.svg"
sed "s|^Exec=.*|Exec=$BIN_DIR/qr_tool %F|" "$SRC_DIR/qr_tool.desktop" > "$APP_DIR/qr_tool.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "installed: $BIN_DIR/qr_tool (图标稍后出现在应用菜单)"
