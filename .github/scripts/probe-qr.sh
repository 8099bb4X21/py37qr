#!/bin/bash
set -euo pipefail

# 与 build-qr.sh 同环境（ARM64 Debian 10，UOS20 对应），只跑性能探测不打包。
sed -i 's|deb\.debian\.org|archive.debian.org|g' /etc/apt/sources.list
sed -i 's|security\.debian\.org|archive.debian.org/debian-security|g' /etc/apt/sources.list 2>/dev/null || true
sed -i '/buster-updates/s/^/# /' /etc/apt/sources.list

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-pip python3-dev python3-tk \
    2>&1 | tail -3

python3 --version

# Debian 10 自带 pip 太老，先升级再装与产品一致的 pin 版本。
pip3 install --quiet --upgrade pip
pip3 install --quiet -r /workspace/requirements.txt

python3 -c "import segno, PIL; print('[OK] deps ready')"

# 容器无显示，探测脚本自动跳过上屏项；结果 tee 进文件供 artifact 回传。
cd /workspace
python3 test/probe_qr_perf.py 2>&1 | tee /workspace/probe_result.txt

echo "[OK] 探测完成!"
ls -lh /workspace/probe_result.txt
