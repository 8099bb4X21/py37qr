#!/bin/bash
set -euo pipefail

# UOS20 对应 Debian 10，已 EOL，先切归档源（参考 KeymouseGo 做法）。
sed -i 's|deb\.debian\.org|archive.debian.org|g' /etc/apt/sources.list
sed -i 's|security\.debian\.org|archive.debian.org/debian-security|g' /etc/apt/sources.list 2>/dev/null || true
sed -i '/buster-updates/s/^/# /' /etc/apt/sources.list

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-pip python3-dev python3-tk binutils \
    2>&1 | tail -3

python3 --version

# Debian 10 自带 pip 太老，不认 manylinux2014 标签，先升级。
pip3 install --quiet --upgrade pip
pip3 install --quiet -r /workspace/requirements.txt
# PyInstaller 6.x 起要求 Python>=3.8，Debian 10 的 Python3.7 只能用 5.x。
pip3 install --quiet 'pyinstaller>=5.0,<6.0'

python3 -c "import segno, PIL; print('[OK] deps ready')"

mkdir -p /workspace/dist /tmp/pyinstaller-build /tmp/pyinstaller-spec

pyinstaller --onefile \
    --distpath /workspace/dist \
    --specpath /tmp/pyinstaller-spec \
    --workpath /tmp/pyinstaller-build \
    --log-level WARN \
    --paths /workspace \
    --hidden-import tkinter \
    --hidden-import segno \
    --hidden-import PIL \
    --hidden-import PIL._tkinter_finder \
    --hidden-import fountain \
    --add-data /workspace/qr_config.ini:. \
    --name qr_tool \
    /workspace/qr_gui.py

# 默认 ini 同时以内嵌(_MEIPASS 兜底)和外置(exe 同目录，可改)两种形式存在，
# 外置优先，改完重启生效，不用重打包。
cp /workspace/qr_config.ini /workspace/dist/qr_config.ini
cp /workspace/assets/qr_tool.desktop /workspace/assets/qr_tool.svg /workspace/dist/

# UOS 端打成日期 zip 包：发版时 TAG_DATE 即 tag 名（YYYYMMDD），
# 手动触发时取当天日期；非法值回退到当天日期。
TAG_DATE="${TAG_DATE:-$(date +%Y%m%d)}"
case "$TAG_DATE" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) TAG_DATE="$(date +%Y%m%d)" ;;
esac
python3 - "$TAG_DATE" <<'EOF'
import sys
import zipfile
date = sys.argv[1]
names = ["qr_tool", "qr_config.ini", "qr_tool.desktop", "qr_tool.svg"]
out = "/workspace/dist/QR_tool_%s.zip" % date
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for name in names:
        zf.write("/workspace/dist/" + name, name)
print("[OK] zip done: " + out)
EOF

echo "[OK] 构建完成!"
ls -lh /workspace/dist/
