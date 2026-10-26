#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""输入框粘贴/全选行为验证：覆盖式粘贴 + 生成后点击全选。

不依赖 segno/PIL 之外的界面逻辑，直接调用 QrApp 的事件处理方法，
在真实 Tk 控件上跑，验证 UOS(Tk 8.6.9) 下“Ctrl+A 后 Ctrl+V 新旧内容并存”的修复。
"""
import os
import sys
import tkinter as tk
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qr_gui


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        raise SystemExit(1)


class Stub:
    # 只承载 QrApp 事件处理需要的属性，绕开整个主窗口。
    def __init__(self, root, text):
        self.root = root
        self.text_widget = text
        self.auto_select_pending = False


def make_stub(root):
    text = tk.Text(root, height=5, wrap="word")
    text.pack()
    stub = Stub(root, text)
    stub.select_all_content = types.MethodType(qr_gui.QrApp.select_all_content, stub)
    stub.select_all_text = types.MethodType(qr_gui.QrApp.select_all_text, stub)
    stub.on_text_click = types.MethodType(qr_gui.QrApp.on_text_click, stub)
    stub.select_all_after_click = types.MethodType(qr_gui.QrApp.select_all_after_click, stub)
    stub.paste_text = types.MethodType(qr_gui.QrApp.paste_text, stub)
    stub.read_clipboard_text = types.MethodType(qr_gui.QrApp.read_clipboard_text, stub)
    stub.event = types.SimpleNamespace(widget=text)
    return stub


def set_clipboard(root, value):
    root.clipboard_clear()
    root.clipboard_append(value)
    root.update()


def text_of(stub):
    return stub.text_widget.get("1.0", "end-1c")


root = tk.Tk()
root.withdraw()

# 1. Ctrl+A 全选后 Ctrl+V：必须只剩新内容（旧内容被替换掉）
stub = make_stub(root)
stub.text_widget.insert("1.0", "旧内容")
set_clipboard(root, "新内容")
stub.select_all_text(stub.event)
check("Ctrl+A 全选中全文", stub.text_widget.tag_ranges("sel") != ())
stub.paste_text(stub.event)
check("全选粘贴覆盖旧内容", text_of(stub) == "新内容")
check("粘贴后无残留选区", stub.text_widget.tag_ranges("sel") == ())

# 2. 部分选区粘贴：只替换选中那段，前后保留
stub.text_widget.delete("1.0", "end")
stub.text_widget.insert("1.0", "abcdef")
stub.text_widget.tag_add("sel", "1.2", "1.4")
stub.paste_text(stub.event)
check("部分选区粘贴只替换选中段", text_of(stub) == "ab新内容ef")

# 3. 无选区粘贴：插在插入点，不吞原有内容
stub.text_widget.delete("1.0", "end")
stub.text_widget.insert("1.0", "abc")
stub.text_widget.mark_set("insert", "1.1")
stub.paste_text(stub.event)
check("无选区粘贴按插入点插入", text_of(stub) == "a新内容bc")

# 4. 剪贴板为空/非文本：原内容与选区都不动，避免误删
stub.text_widget.delete("1.0", "end")
stub.text_widget.insert("1.0", "保留内容")
stub.select_all_text(stub.event)
root.clipboard_clear()
try:
    root.update()
except tk.TclError:
    pass
stub.paste_text(stub.event)
check("空剪贴板不破坏原内容", text_of(stub) == "保留内容")
check("空剪贴板保留选区", stub.text_widget.tag_ranges("sel") != ())

# 5. 生成后首次点击：空闲后自动全选，且标志只消费一次
stub.text_widget.tag_remove("sel", "1.0", "end")
stub.auto_select_pending = True
stub.on_text_click(stub.event)
root.update_idletasks()
ranges = stub.text_widget.tag_ranges("sel")
check("生成后点击自动全选", len(ranges) == 2
      and str(ranges[0]) == "1.0"
      and str(ranges[1]) == str(stub.text_widget.index("end-1c")))
check("全选后插入点在末尾", stub.text_widget.index("insert") == stub.text_widget.index("end-1c"))
check("点击标志已消费", stub.auto_select_pending is False)

# 6. 第二次点击不再全选（可正常定位光标改字）
stub.text_widget.tag_remove("sel", "1.0", "end")
stub.on_text_click(stub.event)
root.update_idletasks()
check("再次点击不全选", stub.text_widget.tag_ranges("sel") == ())

# 7. 空输入时点击不清选区逻辑也不报错
stub.text_widget.delete("1.0", "end")
stub.auto_select_pending = True
stub.on_text_click(stub.event)
root.update_idletasks()
check("空输入点击不报错", stub.auto_select_pending is False and text_of(stub) == "")

root.destroy()
print("[INFO] 粘贴/全选行为验证全部通过")
