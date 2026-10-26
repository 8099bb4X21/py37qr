#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""ini 增量写入验证：缺键补在所属节内、注释保留、只补不覆盖、值同零写入。"""
import configparser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qr_gui

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_check")


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        raise SystemExit(1)


def write_file(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def read_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def read_ini(path):
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser


if not os.path.isdir(OUT_DIR):
    os.makedirs(OUT_DIR)

# 1. 已存在的节缺键：必须补在节内；补到文件末尾会被解析进最后一节，配置等于没写
path = os.path.join(OUT_DIR, "cfg_missing_key.ini")
write_file(path, "[clipboard]\n; 保留注释\n\n[window]\nx = 1\n")
changed = qr_gui._ini_upsert(path, "clipboard", {"auto": "1"}, overwrite=True)
parser = read_ini(path)
check("缺键补在所属节内", changed and parser.get("clipboard", "auto", fallback="") == "1")
check("不污染后面的节", parser.get("window", "auto", fallback="") == "")
check("缺键写在下一节之前", read_file(path).index("auto = 1") < read_file(path).index("[window]"))
check("注释原样保留", "; 保留注释" in read_file(path))
check("原有内容不丢", parser.get("window", "x", fallback="") == "1")

# 2. 整节不存在：追加到文件末尾，键紧跟自己的节头
path = os.path.join(OUT_DIR, "cfg_new_section.ini")
write_file(path, "[general]\ndebug = 0\n")
qr_gui._ini_upsert(path, "clipboard", {"auto": "0"})
parser = read_ini(path)
check("新节可被解析", parser.get("clipboard", "auto", fallback="") == "0")
check("旧节保持不变", parser.get("general", "debug", fallback="") == "0")

# 3. overwrite=False：已有键绝不覆盖用户值
path = os.path.join(OUT_DIR, "cfg_keep.ini")
write_file(path, "[qr]\nbox_size = 7\n")
changed = qr_gui._ini_upsert(path, "qr", {"box_size": "10"})
check("只补缺项不覆盖", (not changed) and read_ini(path).get("qr", "box_size") == "7")

# 4. overwrite=True：值变了只改那一行，值相同零写入
path = os.path.join(OUT_DIR, "cfg_overwrite.ini")
write_file(path, "[carousel]\n; 用户注释\ninterval_ms = 55\n")
changed = qr_gui._ini_upsert(path, "carousel", {"interval_ms": "100"}, overwrite=True)
check("换值成功", changed and read_ini(path).get("carousel", "interval_ms") == "100")
check("换值保留注释", "; 用户注释" in read_file(path))
check("值相同零写入", qr_gui._ini_upsert(
    path, "carousel", {"interval_ms": "100"}, overwrite=True) is False)

# 5. 节名大小写不敏感：写进去的值也要能按小写节名读出来
path = os.path.join(OUT_DIR, "cfg_case.ini")
write_file(path, "[Clipboard]\nauto = 0\n")
qr_gui._ini_upsert(path, "clipboard", {"auto": "1"}, overwrite=True)
check("节名大小写不敏感", qr_gui.ini_get(read_ini(path), "clipboard", "auto") == "1")

# 6. 空文件（等价于 ini 丢失）：按整节不存在处理，能正常建出配置
path = os.path.join(OUT_DIR, "cfg_empty.ini")
write_file(path, "")
qr_gui._ini_upsert(path, "general", {"debug": "0"})
check("空文件可建节", read_ini(path).get("general", "debug") == "0")

# 6b. 文件在但不是 UTF-8（用户用记事本存成 ANSI/GBK）：不能空写覆盖
path = os.path.join(OUT_DIR, "cfg_gbk.ini")
with open(path, "wb") as handle:
    handle.write("[general]\n备注 = 中文\n".encode("gbk"))
with open(path, "rb") as handle:
    before_bytes = handle.read()
changed = qr_gui._ini_upsert(path, "general", {"debug": "0"})
with open(path, "rb") as handle:
    after_bytes = handle.read()
check("非UTF8配置不被覆盖", (not changed) and before_bytes == after_bytes)

# 6c. 带 BOM 的 ini 也能认出节头，不会重复建出一个同名节
path = os.path.join(OUT_DIR, "cfg_bom.ini")
write_file(path, "\ufeff[general]\ndebug = 1\n")
qr_gui._ini_upsert(path, "general", {"debug": "0"}, overwrite=True)
check("BOM文件只有一个节头", read_file(path).count("[general]") == 1
      and "debug = 0" in read_file(path))

# 7. 界面统计用的字节数换算
check("utf8_len 中文=3字节", qr_gui.utf8_len("中") == 3)
check("utf8_len 空串=0", qr_gui.utf8_len("") == 0)

print("[INFO] ini 增量写入验证全部通过")
