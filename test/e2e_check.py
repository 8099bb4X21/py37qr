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
# 先停自动轮播再用 update_idletasks：避免 55ms 自续定时器让 update 一直有事件可处理而卡住。
app.stop_carousel()
seqs = [app.carousel_pos]
for _ in range(5):
    app.tick_carousel()
    app.stop_carousel()
    root.update_idletasks()
    seqs.append(app.carousel_pos)
check("轮播帧循环", len(set(seqs)) > 1)


def find_widgets(parent, widget_class):
    # 递归收集指定 Tk 控件类（用于校验纠错等级是否已挪到右侧）。
    found = []
    for child in parent.winfo_children():
        if child.winfo_class() == widget_class:
            found.append(child)
        found.extend(find_widgets(child, widget_class))
    return found


# 布局：纠错等级从左侧参数区移到二维码上方一行，左侧换成剪贴板选项
check("左侧无纠错等级单选", find_widgets(left, "Radiobutton") == [])
check("右侧有 4 个纠错单选", len(find_widgets(app.preview_label.master, "Radiobutton")) == 4)
check("纠错等级在二维码上一行", int(find_widgets(app.preview_label.master, "Radiobutton")[0]
                                  .master.grid_info()["row"]) == 1)
check("二维码图在第 2 行", int(str(app.preview_label.grid_info()["row"])) == 2)
check("左侧有自动读取剪贴板选项",
      app.auto_clip_check.cget("text") == "自动读取剪贴板" and app.auto_clip_check.master is left)

# 自动读取剪贴板：勾选即载入并出码，内容变化后整段替换
root.clipboard_clear()
root.clipboard_append("剪贴板自动载入测试")
root.update()
app.auto_clip_var.set(True)
app.on_auto_clip_toggle()
root.update()
check("勾选后自动载入剪贴板", app.text_widget.get("1.0", "end-1c") == "剪贴板自动载入测试")
check("载入后已出码", app.stream is not None and app.preview_label.image is not None)

root.clipboard_clear()
root.clipboard_append("第二轮剪贴板内容")
root.update()
app.load_clipboard_if_changed()
root.update()
check("剪贴板变化后整段替换", app.text_widget.get("1.0", "end-1c") == "第二轮剪贴板内容")

root.clipboard_clear()
root.clipboard_append("   ")
root.update()
app.load_clipboard_if_changed()
check("空白剪贴板不清空已出码内容", app.text_widget.get("1.0", "end-1c") == "第二轮剪贴板内容")

app.auto_clip_var.set(False)
app.on_auto_clip_toggle()
check("取消勾选后停止轮询", app.clip_poll_id is None)

root.destroy()
if FAILS:
    print("[FAIL] 失败 " + str(len(FAILS)) + " 项: " + ", ".join(FAILS))
    sys.exit(1)
print("[INFO] GUI 端到端通过")