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

# 日期处理与 build-qr.sh 同规则：TAG_DATE 非 8 位日期回退当天。
TAG_DATE="${TAG_DATE:-$(date +%Y%m%d)}"
case "$TAG_DATE" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) TAG_DATE="$(date +%Y%m%d)" ;;
esac
# 包内二进制改名中文（GitHub 附件名不支持中文，只能包内用中文）；
# Release 附件用英文名 Probe_tool_日期.zip，解压出来是 性能探针 + qr_config.ini。
python3 - "$TAG_DATE" <<'EOF'
import sys
import zipfile
date = sys.argv[1]
out = "/workspace/dist/Probe_tool_%s.zip" % date
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write("/workspace/dist/probe_tool", "性能探针")
    zf.write("/workspace/dist/qr_config.ini", "qr_config.ini")
print("[OK] zip done: " + out)
EOF

echo "[OK] 探测工具构建完成!"
ls -lh /workspace/dist/
