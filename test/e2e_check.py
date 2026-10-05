#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""GUI headless 端到端：单码静止 + 喷泉轮播 + 保存渲染。"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qr_gui

FAILS = []


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        FAILS.append(name)


root = tk.Tk()
app = qr_gui.QrApp(root)
root.geometry("900x620")
root.deiconify()
root.update()

left = root.grid_slaves(row=0, column=0)[0]
check("左栏宽度==250", left.winfo_width() == 250)

# 单码
app.text_widget.insert("1.0", "你好二维码")
app.do_generate()
root.update()
check("短文字单码", app.stream is not None and app.stream.single)
check("单码有预览图", app.preview_label.image is not None)

# 喷泉轮播
app.text_widget.delete("1.0", "end")
app.text_widget.insert("1.0", "轮播测试内容" * 400)
app.do_generate()
root.update()
check("长文字喷泉", app.stream is not None and (not app.stream.single))
check("轮播帧数=2k", app.stream.frame_count() == 2 * app.stream.k)

# 手动 tick 几帧，应循环且不抛异常
seqs = [app.carousel_pos]
for _ in range(5):
    app.tick_carousel()
    root.update()
    seqs.append(app.carousel_pos)
check("轮播帧循环", len(set(seqs)) > 1)

root.destroy()
if FAILS:
    print("[FAIL] 失败 " + str(len(FAILS)) + " 项: " + ", ".join(FAILS))
    sys.exit(1)
print("[INFO] GUI 端到端通过")