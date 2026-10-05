#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
QR 轮播性能探测：找出本机不掉帧的最大显示尺寸。

只测不管改：对“可压缩长文 / 难压缩长文”两种载荷，
在纠错 M/H × box 4~20 的组合下逐项计时
(segno 编码 / PIL 放大 / 缩略 / Tk 上屏)，
再按 qr_config.ini 里 interval_ms 判定每档能否跟上。

用法（UOS 与 Win 通用，在工程目录下执行）：
    python3.7 test/probe_qr_perf.py

说明：
- 会闪现一个隐藏 Tk 窗口（测上屏耗时用）；无显示环境自动跳过该项。
- 全程约 1~3 分钟；控制台与日志文件双写日志，跑完把 [结论] 几行贴回即可。
"""

import configparser
import os
import random
import statistics
import sys
import time

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qr_converter


PROBE_BLOCK_LEN = 200
PROBE_BORDER = 4
PROBE_PREVIEW_CAP = 460
PROBE_BOXES = (4, 6, 8, 10, 12, 16, 20)
PROBE_LEVELS = ("M", "H")
PROBE_FRAMES = 6
PROBE_HEADROOM = 0.7
PROBE_SEED = 42


def get_base_dir():
    # frozen 单文件时取 exe 所在目录，否则取工程根（test/ 的上层）。
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_interval_ms():
    # 只读轮播间隔；读不到用 100，与 qr_gui 默认一致。
    # ini 与 probe_tool 放同一目录（zip 包自带一份，可按需改）。
    default_ms = 100
    ini_path = os.path.join(get_base_dir(), "qr_config.ini")
    try:
        parser = configparser.ConfigParser()
        parser.read(ini_path, encoding="utf-8")
        value = int(parser.get("carousel", "interval_ms", fallback="100"))
    except Exception:
        return default_ms
    if value < 50 or value > 2000:
        return default_ms
    return value


def build_samples():
    # 可压缩走 PYQRF2，难压缩走 PYQRF1 原文；两者都是真实轮播载荷。
    easy_text = "轮播测试内容" * 400
    rng = random.Random(PROBE_SEED)
    pool = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    hard_chars = []
    for _ in range(3000):
        hard_chars.append(rng.choice(pool))
    hard_text = "".join(hard_chars)
    return [
        ("可压缩长文", qr_converter.EncodedStream(
            easy_text, error_name="M", block_len=PROBE_BLOCK_LEN)),
        ("难压缩长文", qr_converter.EncodedStream(
            hard_text, error_name="M", block_len=PROBE_BLOCK_LEN)),
    ]


def make_tk_root():
    # 上屏计时需要真实 Tk；无显示环境返回 None 并跳过该项。
    try:
        import tkinter as tk
    except Exception:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except Exception:
        return None


def time_one_frame(text, level, box, root):
    # 还原 show_frame() 的真实链路，分段计时便于定位瓶颈。
    start = time.perf_counter()
    qr = qr_converter.try_encode(text, level)
    after_encode = time.perf_counter()
    img = qr_converter.render_qr_image(qr, box, PROBE_BORDER)
    after_render = time.perf_counter()
    thumb = img.copy()
    thumb.thumbnail((PROBE_PREVIEW_CAP, PROBE_PREVIEW_CAP))
    after_thumb = time.perf_counter()
    photo_ms = None
    if root is not None:
        # 导入放保护分支内：无 Tk 的 Python（如纯云容器）跳过该项也不崩。
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(thumb)
        photo_ms = (time.perf_counter() - after_thumb) * 1000.0
        del photo
    return {
        "encode_ms": (after_encode - start) * 1000.0,
        "render_ms": (after_render - after_encode) * 1000.0,
        "thumb_ms": (after_thumb - after_render) * 1000.0,
        "photo_ms": photo_ms,
        "side": len(qr.matrix),
    }


def avg(values):
    return statistics.mean(values)


def probe():
    interval_ms = read_interval_ms()
    print("[INFO] 目标轮播间隔 = " + str(interval_ms) + "ms，合格线 = 合计 < "
          + str(interval_ms * PROBE_HEADROOM) + "ms（留主循环余量）")
    root = make_tk_root()
    if root is None:
        print("[WARN] 无 Tk 显示环境，跳过上屏项，结论按偏乐观解读")
    rows = []
    for sample_name, stream in build_samples():
        texts = []
        for seq in range(PROBE_FRAMES):
            texts.append(stream.frame_text(seq))
        for level in PROBE_LEVELS:
            for box in PROBE_BOXES:
                print(".... 测 " + sample_name + " / " + level + " / box="
                      + str(box), flush=True)
                enc_list = []
                render_list = []
                thumb_list = []
                photo_list = []
                side = 0
                for text in texts:
                    timed = time_one_frame(text, level, box, root)
                    enc_list.append(timed["encode_ms"])
                    render_list.append(timed["render_ms"])
                    thumb_list.append(timed["thumb_ms"])
                    if timed["photo_ms"] is not None:
                        photo_list.append(timed["photo_ms"])
                    side = timed["side"]
                photo_avg = avg(photo_list) if photo_list else 0.0
                total = avg(enc_list) + avg(render_list) + avg(thumb_list) + photo_avg
                rows.append({
                    "sample": sample_name,
                    "level": level,
                    "box": box,
                    "px": (side + PROBE_BORDER * 2) * box,
                    "encode": avg(enc_list),
                    "render": avg(render_list),
                    "thumb": avg(thumb_list),
                    "photo": photo_avg,
                    "total": total,
                })
    if root is not None:
        try:
            root.destroy()
        except Exception:
            pass
    return interval_ms, rows


def report(interval_ms, rows):
    # 只留最坏情形一行一档：box | 显示多大 | 一帧最慢 | 能不能跟上。
    print("")
    print("尺寸box | 显示多大 | 一帧最慢 | 跟得上吗")
    limit = interval_ms * PROBE_HEADROOM
    best_box = PROBE_BOXES[0]
    for box in PROBE_BOXES:
        worst = 0.0
        biggest_px = 0
        count = 0
        for row in rows:
            if row["box"] != box:
                continue
            count += 1
            if row["total"] > worst:
                worst = row["total"]
            if row["px"] > biggest_px:
                biggest_px = row["px"]
        if count == 0:
            continue
        if worst <= limit:
            mark = "可以"
            best_box = box
        elif worst <= interval_ms:
            mark = "有点悬"
        else:
            mark = "不行"
        print("box=" + str(box) + " | 约" + str(biggest_px) + "像素 | "
              + format(worst, ".0f") + "毫秒 | " + mark)
    print("")
    print("[结论] 你这台机：预览尺寸最大可用到 box=" + str(best_box)
          + "，再大就可能掉帧。当前默认 box=4，可直接在界面里调大。")


class TeeLogger:
    # 控制台与日志文件双写：在文件管理器双击运行时终端一闪而过，靠日志文件兜底。

    def __init__(self, *targets):
        self.targets = targets

    def write(self, data):
        for target in self.targets:
            try:
                target.write(data)
            except Exception:
                pass

    def flush(self):
        for target in self.targets:
            try:
                target.flush()
            except Exception:
                pass


def open_log_file():
    # 日志落 exe 同目录，带时间戳防覆盖；打不开就只走控制台。
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(get_base_dir(), "probe_log_" + stamp + ".txt")
        return open(path, "w", encoding="utf-8"), path
    except Exception:
        return None, None


def main():
    log_handle, log_path = open_log_file()
    if log_handle is not None:
        sys.stdout = TeeLogger(sys.stdout, log_handle)
    try:
        interval_ms, rows = probe()
        report(interval_ms, rows)
    finally:
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
    if log_path is not None:
        print("日志已存: " + log_path)
    # 终端手工运行时停一下看结论；管道/双击无 stdin 时直接退出。
    if sys.stdin.isatty():
        print("按回车退出...", end="", flush=True)
        try:
            sys.stdin.readline()
        except Exception:
            pass


if __name__ == "__main__":
    main()
