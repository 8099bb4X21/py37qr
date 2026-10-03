#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
QR 界面模块: 输入文字跟随自动生成 1 至 4 个二维码并预览保存。

运行环境: Python3.7 + tkinter(标准库) + Pillow + qrcode。
依赖 qr_converter.py(同目录)，启动: python3.7 qr_gui.py。

布局(工具面板型): 左侧固定参数面板，右侧弹性预览区。
"""

import datetime
import os
import sys
import threading
import tkinter as tk

from tkinter import filedialog
from tkinter import messagebox
from typing import List

from PIL import ImageTk

import qr_converter


DEBUG = False
LOG_FILE = "qr_gui.log"
DEBOUNCE_MS = 600
PREVIEW_SIZE = 320
LEFT_WIDTH = 200


def write_log(level, msg):
    # 用途: 统一日志出口，带时间戳，DEBUG 关闭时只记 info 以上。
    # 参数 level: debug/info/warn/error。
    # 参数 msg: 日志正文。
    if level == "debug" and not DEBUG:
        return
    line = datetime.datetime.now().strftime("%H:%M:%S")
    line = "[" + level.upper() + "] " + line + " " + str(msg)
    print(line, flush=True)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, LOG_FILE)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


class QrApp:
    # 主窗口类，左侧输入参数，右侧预览结果。

    def __init__(self, root):
        self.root = root
        self.root.title("文字转二维码工具(Python3.7)")
        self.root.minsize(700, 500)
        self.after_id = None
        self.seq = 0
        self.last_key = None
        self.photo_refs = []  # type: List[object]
        self.current_images = []  # type: List[object]
        self.error_var = tk.StringVar(value="M")
        self.box_var = tk.IntVar(value=10)
        self.border_var = tk.IntVar(value=4)
        self.build_widgets()
        self.refresh_count_label("")
        self.set_status("在左侧输入文字，二维码将自动生成", False)

    def build_widgets(self):
        # 用途: 搭建左右分栏界面，左固定宽，右弹性。
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        left = tk.Frame(self.root, width=LEFT_WIDTH, padx=8, pady=10)
        left.grid(row=0, column=0, sticky="nsw")
        left.grid_propagate(False)
        right = tk.Frame(self.root, padx=10, pady=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        tk.Label(left, text="输入文字(自动生成)").pack(anchor="w")
        text_frame = tk.Frame(left)
        text_frame.pack(fill="both", expand=True)
        self.text_widget = tk.Text(text_frame, height=12, wrap="word")
        scroll = tk.Scrollbar(text_frame, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scroll.set)
        self.text_widget.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text_widget.bind("<KeyRelease>", self.on_text_change)

        self.count_label = tk.Label(left, text="字符数: 0 / 二维码: -")
        self.count_label.pack(anchor="w", pady=(6, 0))

        param = tk.LabelFrame(left, text="参数", padx=8, pady=8)
        param.pack(fill="x", pady=(8, 0))
        tk.Label(param, text="纠错等级(L<M<Q<H)").pack(anchor="w")
        for level in ("L", "M", "Q", "H"):
            tk.Radiobutton(
                param,
                text=level,
                value=level,
                variable=self.error_var,
                command=self.schedule_auto_generate,
            ).pack(side="left")
        row = tk.Frame(param)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="尺寸").pack(side="left")
        tk.Spinbox(
            row,
            from_=4,
            to=20,
            width=5,
            textvariable=self.box_var,
            command=self.schedule_auto_generate,
        ).pack(side="left", padx=(4, 12))
        tk.Label(row, text="边框").pack(side="left")
        tk.Spinbox(
            row,
            from_=1,
            to=10,
            width=5,
            textvariable=self.border_var,
            command=self.schedule_auto_generate,
        ).pack(side="left", padx=(4, 0))

        btn_row = tk.Frame(left)
        btn_row.pack(fill="x", pady=(10, 0))
        self.gen_button = tk.Button(btn_row, text="生成二维码", command=self.do_generate)
        self.gen_button.pack(side="left", expand=True, fill="x")
        self.save_button = tk.Button(btn_row, text="保存二维码", command=self.on_save)
        self.save_button.pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.clear_button = tk.Button(left, text="清空输入", command=self.on_clear)
        self.clear_button.pack(fill="x", pady=(6, 0))

        tk.Label(right, text="二维码预览(1-4 个)").grid(row=0, column=0, sticky="w")
        self.preview_frame = tk.Frame(right)
        self.preview_frame.grid(row=1, column=0, sticky="nsew")
        self.preview_labels = []
        for idx in range(4):
            label = tk.Label(self.preview_frame, text="", relief="groove")
            label.grid(row=idx // 2, column=idx % 2, padx=6, pady=6, sticky="nsew")
            self.preview_frame.rowconfigure(idx // 2, weight=1)
            self.preview_frame.columnconfigure(idx % 2, weight=1)
            self.preview_labels.append(label)
        self.status_label = tk.Label(right, text="", anchor="w", justify="left")
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def set_status(self, text, is_error):
        # 用途: 底部状态栏反馈，每次操作 200ms 内可见。
        # 参数 text: 提示文字，说清问题和解法，不写空话。
        # 参数 is_error: True 显示红色常驻，False 黑色短暂。
        self.status_label.configure(text=text)
        if is_error:
            self.status_label.configure(fg="red")
        else:
            self.status_label.configure(fg="black")
        write_log("error" if is_error else "info", text)

    def refresh_count_label(self, raw):
        # 用途: 显示现有字符数与上限数，上限按当前纠错等级的 byte 预算估算。
        # 为什么用字节估算: QR 容量本质按字节/模式计算，中文 3 字节、ASCII 1 字节，
        # 直接给"字符上限"会因中英文比例不同而失真，所以同时给出字节数，
        # 字符数按当前文本的平均字节折算，仅作参考，是否装得下以实际生成为准。
        # 参数 raw: 当前输入全文。
        error_name = str(self.error_var.get()).strip().upper()
        budget = qr_converter.BYTE_BUDGET.get(error_name, 2331)
        char_count = len(raw)
        try:
            used_bytes = len(raw.encode("utf-8"))
        except Exception:
            used_bytes = char_count
        if char_count > 0:
            avg = used_bytes / char_count
        else:
            avg = 1.0
        single_chars = int(budget / avg)
        total_chars = single_chars * qr_converter.MAX_QR_COUNT
        self.count_label.configure(
            text="字符: " + str(char_count) + " / 单码约 " + str(single_chars)
            + " 字内\n字节: " + str(used_bytes) + " / 单码 " + str(budget)
            + " B，4 码约 " + str(total_chars) + " 字"
        )

    def on_text_change(self, event):
        # 用途: 文本变化时防抖，600ms 无新输入才真正生成。
        # 参数 event: tkinter 事件对象，未使用。
        self.schedule_auto_generate()

    def schedule_auto_generate(self):
        # 用途: 重置防抖计时器，避免每敲一个字就生成一次。
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
        self.after_id = self.root.after(DEBOUNCE_MS, self.start_generate_thread)

    def start_generate_thread(self):
        # 用途: 防抖到期后在后台线程生成，主线程只刷新界面，避免输入卡顿。
        # 为什么用线程: 大版本 QR 的版本适配要试 40 个版本再对 8 种掩模打分，
        # 单次几百毫秒到数秒，放在主线程会冻结输入，线程里算完再回主线程贴图。
        # 注意 PhotoImage 必须在主线程创建，工作线程只返回 PIL 图片。
        self.after_id = None
        raw = self.text_widget.get("1.0", "end-1c")
        self.refresh_count_label(raw)
        key = (raw, int(self.box_var.get()), int(self.border_var.get()),
               str(self.error_var.get()))
        if key == self.last_key and self.current_images:
            self.set_status("内容无变化，已跳过重复生成", False)
            return
        if raw.strip() == "":
            self.seq += 1
            self.last_key = key
            self.current_images = []
            self.photo_refs = []
            for label in self.preview_labels:
                label.configure(image="", text="")
            self.set_status("输入为空，已清空预览", False)
            return
        self.seq += 1
        seq = self.seq
        self.last_key = key
        self.gen_button.configure(state="disabled")
        self.set_status("生成中...", False)
        worker = threading.Thread(
            target=self.generate_worker,
            args=(raw, key, seq),
            daemon=True,
        )
        worker.start()

    def generate_worker(self, raw, key, seq):
        # 用途: 后台线程做重活，算完切回主线程更新界面。
        # 参数 raw: 快照全文，避免生成过程中用户继续输入导致错位。
        # 参数 key: 本次参数快照，用于回填时核对。
        # 参数 seq: 本次任务序号，过时任务的结果直接丢弃。
        try:
            images = qr_converter.text_to_qr_images(
                raw, key[1], key[2], key[3],
            )
            error = None
        except Exception as exc:
            images = []
            error = exc
        self.root.after(
            0, lambda: self.on_generate_done(seq, raw, images, error),
        )

    def on_generate_done(self, seq, raw, images, error):
        # 用途: 主线程回调，只接受最新任务的结果，旧任务直接丢弃。
        # 参数 seq: 任务序号，与 self.seq 不一致说明用户又输入了新内容。
        # 参数 raw: 本次任务的全文快照，用于计数显示。
        # 参数 images: 生成的 PIL 图片列表，失败时为空。
        # 参数 error: 异常对象，成功时为 None。
        if seq != self.seq:
            write_log("debug", "丢弃过期任务 seq=" + str(seq))
            return
        self.gen_button.configure(state="normal")
        if error is not None:
            self.set_status("生成失败: " + str(error), True)
            return
        self.current_images = images
        self.update_preview(images)
        self.refresh_count_label(raw)
        if len(images) > 1:
            self.set_status(
                "文字过长，已自动拆成 " + str(len(images)) + " 个二维码", False
            )
        else:
            self.set_status("已生成 1 个二维码", False)

    def do_generate(self):
        # 用途: 手动按钮入口，与自动生成走同一后台线程路径。
        self.schedule_auto_generate()

    def update_preview(self, images):
        # 用途: 把 1-4 张 PIL 图片缩略后放到 2x2 预览格。
        # 参数 images: PIL 图片列表。
        self.photo_refs = []
        for idx, label in enumerate(self.preview_labels):
            if idx < len(images):
                thumb = images[idx].copy()
                thumb.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
                photo = ImageTk.PhotoImage(thumb)
                self.photo_refs.append(photo)
                label.configure(image=photo, text="")
                label.image = photo
            else:
                label.configure(image="", text="")
                label.image = None

    def on_save(self):
        # 用途: 弹出保存框，单张存一文件，多张自动加 _1/_2 后缀。
        if not self.current_images:
            self.set_status("没有可保存的内容，请先输入文字生成", True)
            return
        init = "qrcode.png"
        target = filedialog.asksaveasfilename(
            title="保存二维码",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")],
            initialfile=init,
        )
        if not target:
            return
        try:
            saved = qr_converter.save_qr_images(self.current_images, target)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            self.set_status("保存失败: " + str(exc), True)
            return
        self.set_status("已保存: " + ", ".join(saved), False)
        messagebox.showinfo("保存成功", "\n".join(saved))

    def on_clear(self):
        # 用途: 清空输入框并立即刷新为空状态，不留白屏疑惑。
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        self.text_widget.delete("1.0", "end")
        self.start_generate_thread()


def main():
    root = tk.Tk()
    QrApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
