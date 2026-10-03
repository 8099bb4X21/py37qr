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
    --name qr_tool \
    /workspace/qr_gui.py

echo "[OK] 构建完成!"
ls -lh /workspace/dist/qr_tool
