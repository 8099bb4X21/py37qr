#!/bin/bash
set -euo pipefail

# 与 build-qr.sh 同环境（ARM64 Debian 10，UOS20 对应），
# 把探测脚本打成 UOS 可直接跑的单文件 probe_tool，不装 Python 模块也能测本机性能。
sed -i 's|deb\.debian\.org|archive.debian.org|g' /etc/apt/sources.list
sed -i 's|security\.debian\.org|archive.debian.org/debian-security|g' /etc/apt/sources.list 2>/dev/null || true
sed -i '/buster-updates/s/^/# /' /etc/apt/sources.list

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-pip python3-dev python3-tk binutils \
    2>&1 | tail -3

python3 --version

# Debian 10 自带 pip 太老，先升级再装与产品一致的 pin 版本。
pip3 install --quiet --upgrade pip
pip3 install --quiet -r /workspace/requirements.txt
# PyInstaller 6.x 起要求 Python>=3.8，Debian 10 的 Python3.7 只能用 5.x。
pip3 install --quiet 'pyinstaller>=5.0,<6.0'

python3 -c "import segno, PIL; print('[OK] deps ready')"

mkdir -p /workspace/dist /tmp/pyinstaller-build-probe /tmp/pyinstaller-spec-probe

pyinstaller --onefile \
    --distpath /workspace/dist \
    --specpath /tmp/pyinstaller-spec-probe \
    --workpath /tmp/pyinstaller-build-probe \
    --log-level WARN \
    --paths /workspace \
    --hidden-import tkinter \
    --hidden-import segno \
    --hidden-import PIL \
    --hidden-import PIL._tkinter_finder \
    --hidden-import fountain \
    --hidden-import qr_converter \
    --add-data /workspace/qr_config.ini:. \
    --name probe_tool \
    /workspace/test/probe_qr_perf.py

# 包内自带一份默认 ini（与 probe_tool 同目录，改完直接生效，不用重打包）。
cp /workspace/qr_config.ini /workspace/dist/qr_config.ini

# 日期 zip 包：手动触发取当天日期（与 build-qr.sh 同规则）。
TAG_DATE="$(date +%Y%m%d)"
python3 - "$TAG_DATE" <<'EOF'
import sys
import zipfile
date = sys.argv[1]
names = ["probe_tool", "qr_config.ini"]
out = "/workspace/dist/Probe_tool_%s.zip" % date
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for name in names:
        zf.write("/workspace/dist/" + name, name)
print("[OK] zip done: " + out)
EOF

echo "[OK] 探测工具构建完成!"
ls -lh /workspace/dist/
