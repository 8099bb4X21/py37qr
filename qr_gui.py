#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
QR 界面模块: 输入文字跟随生成。短文字单码静止，长文字喷泉轮播(单张快速切换)。

运行环境: Python3.7 + tkinter(标准库) + segno + Pillow。
依赖 qr_converter.py / fountain.py(同目录)，启动: python3.7 qr_gui.py。
轮播帧走 fountain 协议(免顺序/免缺码)，手机 App(zxing-cpp)抓够 k 块即还原。
"""

import configparser
import datetime
import os
import sys
import tkinter as tk
import traceback

from tkinter import filedialog
from tkinter import messagebox

from PIL import ImageTk
import PIL._tkinter_finder  # noqa: F401  # 打包后 ImageTk 定位 Tcl/Tk 必需

import qr_converter


DEBUG = False
CONFIG_FILE = "qr_config.ini"
LOG_FILE = "qr_debug.log"
DEBOUNCE_MS = 2000
PREVIEW_SIZE = 460
PREVIEW_BOX = 4
PREVIEW_BORDER = 4
FIXED_BORDER = 4
DEFAULT_BLOCK_LEN = 200
DEFAULT_INTERVAL_MS = 100
DEFAULT_BOX_SIZE = 10
LEFT_WIDTH = 250


def get_app_dir():
    # 程序所在目录，编译前后统一读 ini/log。
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = get_app_dir()


def find_config_path():
    # exe 同目录 ini 优先，包内默认兜底。
    side = os.path.join(APP_DIR, CONFIG_FILE)
    if os.path.isfile(side):
        return side
    if getattr(sys, "frozen", False):
        inner = os.path.join(getattr(sys, "_MEIPASS", APP_DIR), CONFIG_FILE)
        if os.path.isfile(inner):
            return inner
    return side


def load_app_config():
    # 读 ini 全量配置，每项独立 try，坏一项不影响其他项的默认值。
    # 返回 (debug, interval_ms, box_size)。
    debug = False
    interval_ms = DEFAULT_INTERVAL_MS
    box_size = DEFAULT_BOX_SIZE
    try:
        parser = configparser.ConfigParser()
        parser.read(find_config_path(), encoding="utf-8")
    except Exception:
        return debug, interval_ms, box_size
    try:
        debug = parser.get("general", "debug", fallback="0").strip() == "1"
    except Exception:
        pass
    try:
        interval_ms = int(parser.get("carousel", "interval_ms", fallback="100"))
    except Exception:
        pass
    try:
        box_size = int(parser.get("qr", "box_size", fallback="10"))
    except Exception:
        pass
    if interval_ms < 50 or interval_ms > 2000:
        interval_ms = DEFAULT_INTERVAL_MS
    if box_size < 4 or box_size > 20:
        box_size = DEFAULT_BOX_SIZE
    return debug, interval_ms, box_size


DEBUG, APP_INTERVAL_MS, APP_BOX_SIZE = load_app_config()


def write_log(level, msg):
    # 控制台永远打印，文件只在 debug=1 时落 qr_debug.log。
    if level == "debug" and not DEBUG:
        return
    line = "[" + level.upper() + "] " + datetime.datetime.now().strftime("%H:%M:%S") + " " + str(msg)
    print(line, flush=True)
    if not DEBUG:
        return
    try:
        with open(os.path.join(APP_DIR, LOG_FILE), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


class QrApp:
    # 主窗口：左输入参数，右单张预览。

    def __init__(self, root):
        self.root = root
        self.root.title("文字转二维码工具")
        self.root.minsize(820, 600)
        self.debounce_id = None
        self.carousel_id = None
        self.interval_debounce_id = None
        self.stream = None
        self.carousel_pos = 0
        self.error_var = tk.StringVar(value="M")
        self.box_var = tk.IntVar(value=APP_BOX_SIZE)
        self.interval_var = tk.IntVar(value=APP_INTERVAL_MS)
        self.build_widgets()
        self.set_status("在左侧输入文字，二维码将自动生成", False)

    def build_widgets(self):
        # 左固定宽参数面板，右弹性单张预览。
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        left = tk.Frame(self.root, width=LEFT_WIDTH, padx=8, pady=10)
        left.grid(row=0, column=0, sticky="nsw")
        left.pack_propagate(False)
        right = tk.Frame(self.root, padx=10, pady=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        tk.Label(left, text="输入文字(自动生成)").pack(anchor="w")
        text_frame = tk.Frame(left)
        text_frame.pack(fill="both", expand=True)
        self.text_widget = tk.Text(text_frame, height=14, wrap="word")
        scroll = tk.Scrollbar(text_frame, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scroll.set)
        self.text_widget.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text_widget.bind("<KeyRelease>", self.on_text_change)

        self.count_label = tk.Label(left, text="字符: 0", anchor="w", justify="left")
        self.count_label.pack(anchor="w", pady=(6, 0))

        param = tk.LabelFrame(left, text="参数", padx=8, pady=8)
        param.pack(fill="x", pady=(8, 0))
        tk.Label(param, text="纠错等级(L<M<Q<H)").pack(anchor="w")
        level_row = tk.Frame(param)
        level_row.pack(fill="x")
        for pos, level in enumerate(("L", "M", "Q", "H")):
            tk.Radiobutton(
                level_row, text=level, value=level, variable=self.error_var,
                command=self.schedule_auto_generate,
            ).grid(row=pos // 2, column=pos % 2, sticky="w")
        row = tk.Frame(param)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="分辨率").pack(side="left")
        self.box_spin = tk.Spinbox(row, from_=4, to=20, width=3, textvariable=self.box_var,
                   command=self.schedule_auto_generate)
        self.box_spin.pack(side="left", padx=(2, 0))
        # Spinbox 的 command 只响应上下箭头，键盘打字走 KeyRelease，都进 2 秒防抖。
        self.box_spin.bind("<KeyRelease>", lambda event: self.schedule_auto_generate())
        row2 = tk.Frame(param)
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="轮播ms").pack(side="left")
        self.interval_spin = tk.Spinbox(row2, from_=50, to=2000, width=5, textvariable=self.interval_var,
                   command=self.schedule_interval_apply)
        self.interval_spin.pack(side="left", padx=(2, 0))
        self.interval_spin.bind("<KeyRelease>", lambda event: self.schedule_interval_apply())

        btn_row = tk.Frame(left)
        btn_row.pack(fill="x", pady=(10, 0))
        self.gen_button = tk.Button(btn_row, text="生成二维码", command=self.do_generate)
        self.gen_button.pack(side="left", expand=True, fill="x")
        self.save_button = tk.Button(btn_row, text="保存二维码", command=self.on_save)
        self.save_button.pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.clear_button = tk.Button(left, text="清空输入", command=self.on_clear)
        self.clear_button.pack(fill="x", pady=(6, 0))

        tk.Label(right, text="二维码预览").grid(row=0, column=0, sticky="w")
        self.frame_label = tk.Label(right, text="", anchor="w")
        self.frame_label.grid(row=0, column=0, sticky="e")
        self.preview_label = tk.Label(right, bg="white", relief="groove")
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.status_label = tk.Label(right, text="", anchor="w", justify="left")
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def set_status(self, text, is_error):
        self.status_label.configure(text=text, fg=("red" if is_error else "black"))
        write_log("error" if is_error else "info", text)

    def get_box(self):
        # 保存用分辨率；边框固定 4（规范静默区），不再可调。
        try:
            box = int(self.box_var.get())
        except Exception:
            box = APP_BOX_SIZE
        return max(4, min(box, 20))

    def get_interval(self):
        try:
            v = int(self.interval_var.get())
        except Exception:
            v = DEFAULT_INTERVAL_MS
        return max(50, min(v, 2000))

    def on_text_change(self, event):
        self.schedule_auto_generate()

    def schedule_auto_generate(self):
        if self.debounce_id is not None:
            try:
                self.root.after_cancel(self.debounce_id)
            except Exception:
                pass
        self.debounce_id = self.root.after(DEBOUNCE_MS, self.do_generate)

    def do_generate(self):
        # 单码静止 / 喷泉轮播的统一入口，UI 线程同步生成(单帧渲染 ~0.05s)。
        self.debounce_id = None
        self.stop_carousel()
        raw = self.text_widget.get("1.0", "end-1c")
        if raw.strip() == "":
            self.stream = None
            self.frame_label.configure(text="")
            self.preview_label.configure(image="", text="")
            self.count_label.configure(text="字符: 0")
            self.set_status("输入为空，已清空预览", False)
            return
        try:
            self.stream = qr_converter.EncodedStream(
                raw, str(self.error_var.get()), block_len=DEFAULT_BLOCK_LEN)
        except Exception as exc:
            self.stream = None
            self.set_status("生成失败: " + str(exc), True)
            return
        self.refresh_info(raw)
        if self.stream.single:
            self.frame_label.configure(text="")
            self.show_frame(0)
            self.set_status("单码，共 1 张", False)
        else:
            self.carousel_pos = 0
            self.show_frame(0)
            self.frame_label.configure(text="帧 1/" + str(self.stream.frame_count()))
            self.set_status(
                "已拆 " + str(self.stream.k) + " 块，轮播中(免顺序，App 抓够即还原)", False)
            self.schedule_carousel()

    def show_frame(self, pos):
        # 渲染第 pos 帧并缩略显示。预览固定小 box 保证轮播流畅。
        text = self.stream.frame_text(pos)
        img = qr_converter.build_qr_image(
            text, PREVIEW_BOX, PREVIEW_BORDER, self.stream.error_name)
        thumb = img.copy()
        thumb.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
        photo = ImageTk.PhotoImage(thumb)
        self.preview_label.configure(image=photo)
        self.preview_label.image = photo

    def schedule_carousel(self):
        self.carousel_id = self.root.after(self.get_interval(), self.tick_carousel)

    def tick_carousel(self):
        if self.stream is None or self.stream.single:
            return
        self.carousel_pos = (self.carousel_pos + 1) % self.stream.frame_count()
        self.show_frame(self.carousel_pos)
        self.frame_label.configure(
            text="帧 " + str(self.carousel_pos + 1) + "/" + str(self.stream.frame_count()))
        self.schedule_carousel()

    def stop_carousel(self):
        if self.carousel_id is not None:
            try:
                self.root.after_cancel(self.carousel_id)
            except Exception:
                pass
            self.carousel_id = None

    def schedule_interval_apply(self):
        # 轮播间隔改动后 2 秒无操作再生效，避免边输边重启轮播。
        if self.interval_debounce_id is not None:
            try:
                self.root.after_cancel(self.interval_debounce_id)
            except Exception:
                pass
        self.interval_debounce_id = self.root.after(DEBOUNCE_MS, self.apply_interval)

    def apply_interval(self):
        # 防抖到期真正应用轮播间隔（与 restart_carousel 分开，便于单测与复用）。
        self.interval_debounce_id = None
        self.restart_carousel()

    def restart_carousel(self):
        # 按当前轮播间隔重启节奏（喷泉轮播中才有效）。
        if self.stream is not None and (not self.stream.single):
            self.stop_carousel()
            self.schedule_carousel()

    def refresh_info(self, raw):
        try:
            used = len(raw.encode("utf-8"))
        except Exception:
            used = len(raw)
        if self.stream is None:
            self.count_label.configure(text="字符: " + str(len(raw)))
        elif self.stream.single:
            self.count_label.configure(text="字符: " + str(len(raw)) + " / 字节: " + str(used) + " / 单码")
        else:
            self.count_label.configure(
                text="字符: " + str(len(raw)) + " / 字节: " + str(used)
                + " / 轮播 " + str(self.stream.k) + " 块")

    def on_save(self):
        # 单码存 1 张；喷泉存 k 张系统帧(seq 0..k-1，按序即原文)。
        if self.stream is None:
            self.set_status("没有可保存的内容", True)
            return
        target = filedialog.asksaveasfilename(
            title="保存二维码", defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")], initialfile="qrcode.png")
        if not target:
            return
        box = self.get_box()
        try:
            if self.stream.single:
                images = [qr_converter.build_qr_image(
                    self.stream.frame_text(0), box, FIXED_BORDER, self.stream.error_name)]
            else:
                images = [qr_converter.build_qr_image(
                    self.stream.frame_text(i), box, FIXED_BORDER, self.stream.error_name)
                    for i in range(self.stream.k)]
            saved = qr_converter.save_qr_images(images, target)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            self.set_status("保存失败: " + str(exc), True)
            return
        self.set_status("已保存 " + str(len(saved)) + " 张", False)
        messagebox.showinfo("保存成功", "\n".join(saved))

    def on_clear(self):
        self.stop_carousel()
        if self.debounce_id is not None:
            try:
                self.root.after_cancel(self.debounce_id)
            except Exception:
                pass
            self.debounce_id = None
        self.text_widget.delete("1.0", "end")
        self.do_generate()


def log_startup_info():
    # 启动环境快照落入 debug 日志。
    try:
        import segno
        import PIL

        segno_ver = getattr(segno, "__version__", "未知")
        pil_ver = getattr(PIL, "__version__", "未知")
    except Exception as exc:
        segno_ver = "导入失败: " + str(exc)
        pil_ver = "导入失败: " + str(exc)
    write_log(
        "debug",
        "启动 frozen=" + str(bool(getattr(sys, "frozen", False)))
        + " python=" + sys.version.split()[0]
        + " segno=" + str(segno_ver) + " pillow=" + str(pil_ver)
        + " app_dir=" + APP_DIR + " config=" + find_config_path()
        + " debug=" + str(DEBUG)
        + " interval_ms=" + str(APP_INTERVAL_MS) + " box=" + str(APP_BOX_SIZE),
    )


def main():
    log_startup_info()
    root = tk.Tk()
    QrApp(root)
    try:
        root.mainloop()
    except Exception:
        write_log("debug", "主循环异常退出\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()