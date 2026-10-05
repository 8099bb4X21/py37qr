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

from PIL import Image
from PIL import ImageDraw
from PIL import ImageTk
import PIL._tkinter_finder  # noqa: F401  # 打包后 ImageTk 定位 Tcl/Tk 必需

import qr_converter


DEBUG = False
CONFIG_FILE = "qr_config.ini"
LOG_FILE = "qr_debug.log"
DEBOUNCE_MS = 2000
PREVIEW_SIZE = 460
PREVIEW_BORDER = 4
FIXED_BORDER = 4
DEFAULT_BLOCK_LEN = 200
DEFAULT_INTERVAL_MS = 100
DEFAULT_BOX_SIZE = 10
DEFAULT_PREVIEW_BOX = 4
LEFT_WIDTH = 250
WIN_MIN_W = 820
WIN_MIN_H = 600


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
    # 返回 (debug, interval_ms, box_size, preview_box)。
    debug = False
    interval_ms = DEFAULT_INTERVAL_MS
    box_size = DEFAULT_BOX_SIZE
    preview_box = DEFAULT_PREVIEW_BOX
    try:
        parser = configparser.ConfigParser()
        parser.read(find_config_path(), encoding="utf-8")
    except Exception:
        return debug, interval_ms, box_size, preview_box
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
    try:
        preview_box = int(parser.get("preview", "box", fallback="4"))
    except Exception:
        pass
    if interval_ms < 50 or interval_ms > 2000:
        interval_ms = DEFAULT_INTERVAL_MS
    if box_size < 4 or box_size > 20:
        box_size = DEFAULT_BOX_SIZE
    if preview_box < 2 or preview_box > 12:
        preview_box = DEFAULT_PREVIEW_BOX
    return debug, interval_ms, box_size, preview_box


DEBUG, APP_INTERVAL_MS, APP_BOX_SIZE, APP_PREVIEW_BOX = load_app_config()


def _ini_upsert(path, section, items, overwrite=False):
    # 文本级增量更新 ini：只补/改指定节的键，原样保留注释、空行与其他内容。
    # configparser 整文件重写会吃掉注释，所以这里手写追加逻辑。
    # overwrite=False 时已存在的键绝不覆盖（只补缺项）；True 则更新旧值（存窗口用）。
    # 返回 True=文件被改动过。
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception:
        lines = []
    pending = dict(items)
    in_target = False
    section_seen = False
    changed = False
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_target = stripped[1:-1].strip().lower() == section.lower()
            if in_target:
                section_seen = True
            out.append(line)
            continue
        if in_target and stripped and not stripped.startswith((";", "#")) and "=" in line:
            key = line.split("=", 1)[0].strip().lower()
            hit = None
            for want_key in pending.keys():
                if key == want_key.lower():
                    hit = want_key
                    break
            if hit is not None:
                if overwrite:
                    old_value = line.split("=", 1)[1].strip()
                    if old_value != str(pending[hit]):
                        out.append(hit + " = " + str(pending.pop(hit)))
                        changed = True
                        continue
                # 值相同或只补缺项：保留原行，绝不覆盖用户内容。
                del pending[hit]
        out.append(line)
    if not section_seen:
        out.append("[" + section + "]")
        changed = True
    for want_key, value in pending.items():
        out.append(want_key + " = " + str(value))
        changed = True
    if not changed:
        return False
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("\n".join(out) + "\n")
        return True
    except Exception:
        return False


def ensure_config_defaults():
    # ini 缺项自动回写（只补 general/carousel/qr/preview；window 关闭时才有真实值）。
    # 返回 True=写过文件。目录只读等异常静默跳过，保证任何环境可启动。
    path = find_config_path()
    changed = False
    changed = _ini_upsert(path, "general", {"debug": "0"}) or changed
    changed = _ini_upsert(path, "carousel", {"interval_ms": "100"}) or changed
    changed = _ini_upsert(path, "qr", {"box_size": "10"}) or changed
    changed = _ini_upsert(path, "preview", {"box": "4"}) or changed
    return changed


ensure_config_defaults()


def center_window(root):
    # 无存档时居中（参考 docx 批量替换的 _center_window）。
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry("%dx%d+%d+%d" % (width, height, x, y))


def apply_window_from_config(root):
    # 打开时按 ini 摆窗口：齐了就用存档（钳制到可见范围），缺了/非法就居中。
    # 参考 docx 批量替换的 _apply_saved_window_size。
    # 返回 True=用了存档。
    try:
        parser = configparser.ConfigParser()
        parser.read(find_config_path(), encoding="utf-8")
        x = int(parser.get("window", "x"))
        y = int(parser.get("window", "y"))
        width = int(parser.get("window", "width"))
        height = int(parser.get("window", "height"))
    except Exception:
        center_window(root)
        return False
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    width = max(WIN_MIN_W, min(width, screen_w - 40))
    height = max(WIN_MIN_H, min(height, screen_h - 80))
    x = max(0, min(x, screen_w - 100))
    y = max(0, min(y, screen_h - 100))
    root.geometry("%dx%d+%d+%d" % (width, height, x, y))
    return True


def save_window_to_config(root):
    # 关闭时把当前窗口位置尺寸写回 ini，目录只读则静默跳过。
    try:
        root.update_idletasks()
        x = root.winfo_x()
        y = root.winfo_y()
        width = max(WIN_MIN_W, root.winfo_width())
        height = max(WIN_MIN_H, root.winfo_height())
    except Exception:
        return False
    try:
        return _ini_upsert(find_config_path(), "window", {
            "x": str(x),
            "y": str(y),
            "width": str(width),
            "height": str(height),
        }, overwrite=True)
    except Exception:
        return False


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
        self.root.minsize(WIN_MIN_W, WIN_MIN_H)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.debounce_id = None
        self.carousel_id = None
        self.interval_debounce_id = None
        self.stream = None
        self.carousel_pos = 0
        self.error_var = tk.StringVar(value="M")
        self.box_var = tk.IntVar(value=APP_BOX_SIZE)
        self.interval_var = tk.IntVar(value=APP_INTERVAL_MS)
        self.preview_var = tk.IntVar(value=APP_PREVIEW_BOX)
        self.build_widgets()
        apply_window_from_config(self.root)
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
        # UOS/Linux 下 Tk 输入框默认 Ctrl+A=跳行首（非全选），
        # 且 Ctrl+C/X/V 无 Win 习惯行为，这里显式补上并吃掉默认键行为。
        self.text_widget.bind("<Control-a>", self.select_all_text)
        self.text_widget.bind("<Control-A>", self.select_all_text)
        self.text_widget.bind("<Control-c>", lambda event: self.forward_clipboard(event, "<<Copy>>"))
        self.text_widget.bind("<Control-C>", lambda event: self.forward_clipboard(event, "<<Copy>>"))
        self.text_widget.bind("<Control-x>", lambda event: self.forward_clipboard(event, "<<Cut>>"))
        self.text_widget.bind("<Control-X>", lambda event: self.forward_clipboard(event, "<<Cut>>"))
        self.text_widget.bind("<Control-v>", lambda event: self.forward_clipboard(event, "<<Paste>>"))
        self.text_widget.bind("<Control-V>", lambda event: self.forward_clipboard(event, "<<Paste>>"))

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
        row3 = tk.Frame(param)
        row3.pack(fill="x", pady=(8, 0))
        tk.Label(row3, text="预览尺寸").pack(side="left")
        self.preview_spin = tk.Spinbox(row3, from_=2, to=12, width=3, textvariable=self.preview_var,
                   command=self.schedule_auto_generate)
        self.preview_spin.pack(side="left", padx=(2, 0))
        # 预览尺寸只影响显示大小（2~12），改后 2 秒防抖重渲染，回写 ini 下次沿用。
        self.preview_spin.bind("<KeyRelease>", lambda event: self.schedule_auto_generate())

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

    def get_preview_box(self):
        # 预览用分辨率，只影响显示大小；非法输入回退 ini 默认。
        try:
            box = int(self.preview_var.get())
        except Exception:
            box = APP_PREVIEW_BOX
        return max(2, min(box, 12))

    def on_text_change(self, event):
        self.update_counts_fast()
        self.schedule_auto_generate()

    def select_all_text(self, event):
        # Ctrl+A 全选：覆盖 Linux 默认的跳行首行为。
        event.widget.tag_add("sel", "1.0", "end-1c")
        event.widget.mark_set("insert", "end-1c")
        event.widget.see("insert")
        return "break"

    def forward_clipboard(self, event, virtual):
        # Ctrl+C/X/V 转调输入框原生 <<Copy>>/<<Cut>>/<<Paste>>，吃掉默认键行为。
        try:
            event.widget.event_generate(virtual)
        except Exception:
            pass
        return "break"

    def update_counts_fast(self):
        # 每次按键立即刷新字符/字节数（纯计算不渲染不生成）；生成仍走 2 秒防抖。
        raw = self.text_widget.get("1.0", "end-1c")
        try:
            used = len(raw.encode("utf-8"))
        except Exception:
            used = len(raw)
        self.count_label.configure(text="字符: " + str(len(raw)) + " / 字节: " + str(used))

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
        # 参数回写 ini：之前只读不存，轮播间隔/分辨率改后重启丢失，此处补上。
        # _ini_upsert 值相同零写入，空输入也照存参数。
        self.persist_params_to_ini()
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
            if self.stream.compressed:
                self.set_status(
                    "已压缩 " + str(self.stream.raw_len) + "->" + str(self.stream.payload_len)
                    + " 字节，拆 " + str(self.stream.k) + " 块，轮播中(免顺序，App 抓够即还原)", False)
            else:
                self.set_status(
                    "不可压，用原文直发，已拆 " + str(self.stream.k) + " 块，轮播中(免顺序，App 抓够即还原)", False)
            self.schedule_carousel()

    def show_frame(self, pos):
        # 渲染第 pos 帧并缩略显示。预览尺寸界面可调（默认 4，UOS 实测 55ms 档
        # box=6 最坏 18.5ms 也稳；再大就得加宽窗口，范围钳在 2~12）。
        # segno 对象走轮播缓存，不逐帧重编，单帧只剩渲染开销，防卡顿共振。
        qr = self.stream.qr_code(pos)
        img = qr_converter.render_qr_image(
            qr, self.get_preview_box(), PREVIEW_BORDER)
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
        try:
            self.show_frame(self.carousel_pos)
        except Exception as exc:
            # 单帧渲染失败不断轮播链，报错后继续下一帧。
            self.set_status("渲染失败，已跳过该帧: " + str(exc), True)
            self.schedule_carousel()
            return
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
        self.persist_params_to_ini()
        self.restart_carousel()

    def persist_params_to_ini(self):
        # 分辨率、轮播间隔与预览尺寸是 ini 已有键，变了就回写；纠错档无 ini 键，保持会话级。
        # 目录只读等异常静默跳过，不影响生成主流程。
        try:
            _ini_upsert(find_config_path(), "carousel", {
                "interval_ms": str(self.get_interval()),
            }, overwrite=True)
        except Exception:
            pass
        try:
            _ini_upsert(find_config_path(), "qr", {
                "box_size": str(self.get_box()),
            }, overwrite=True)
        except Exception:
            pass
        try:
            _ini_upsert(find_config_path(), "preview", {
                "box": str(self.get_preview_box()),
            }, overwrite=True)
        except Exception:
            pass

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
            extra = ""
            if self.stream.compressed:
                extra = " / 压缩 " + str(self.stream.raw_len) + "->" + str(self.stream.payload_len)
            self.count_label.configure(
                text="字符: " + str(len(raw)) + " / 字节: " + str(used)
                + " / 轮播 " + str(self.stream.k) + " 块" + extra)

    def on_save(self):
        # 单码存 1 张；喷泉存 k 张系统帧(seq 0..k-1)。
        # 系统帧按序拼 = 传输层载荷：未压缩时即原文，压缩时需还原后再 gunzip。
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
                images = [qr_converter.render_qr_image(
                    self.stream.qr_code(i), box, FIXED_BORDER)
                    for i in range(self.stream.k)]
            saved = qr_converter.save_qr_images(images, target)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            self.set_status("保存失败: " + str(exc), True)
            return
        self.set_status("已保存 " + str(len(saved)) + " 张", False)
        messagebox.showinfo("保存成功", "\n".join(saved))

    def on_close(self):
        # 关闭：停掉定时器，把窗口位置尺寸写回 ini，再退出。
        self.stop_carousel()
        for timer_id in (self.debounce_id, self.interval_debounce_id):
            if timer_id is not None:
                try:
                    self.root.after_cancel(timer_id)
                except Exception:
                    pass
        save_window_to_config(self.root)
        self.root.destroy()

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


def make_window_icon(size=48):
    # PIL 现场画任务栏图标：照着 assets/qr_tool.svg 简化（圆角深底+青色取景框+
    # 白色定位块+扫描线），渐变/辉光/虚线网格在 48px 下不可见故省略。
    # 不带外部资源，frozen 包直接可用；返回 RGBA 图。
    scale = size / 108.0

    def s(v):
        return int(round(v * scale))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=s(24), fill=(15, 23, 42, 255))
    cyan = (0, 242, 254, 255)
    white = (255, 255, 255, 255)
    light = (226, 232, 240, 255)
    w = max(1, s(3))
    # 四角取景框
    draw.line([s(27), s(37), s(27), s(27), s(37), s(27)], fill=cyan, width=w, joint="curve")
    draw.line([s(71), s(27), s(79), s(27), s(81), s(29), s(81), s(37)], fill=cyan, width=w, joint="curve")
    draw.line([s(27), s(71), s(27), s(79), s(29), s(81), s(37), s(81)], fill=cyan, width=w, joint="curve")
    draw.line([s(71), s(81), s(79), s(81), s(81), s(79), s(81), s(71)], fill=cyan, width=w, joint="curve")
    # 三个定位块：白外框+深底掏空+白中心
    for fx, fy in ((32, 32), (64, 32), (32, 64)):
        draw.rectangle([s(fx), s(fy), s(fx + 12), s(fy + 12)], fill=white)
        draw.rectangle([s(fx + 2), s(fy + 2), s(fx + 10), s(fy + 10)], fill=(15, 23, 42, 255))
        draw.rectangle([s(fx + 5), s(fy + 5), s(fx + 7), s(fy + 7)], fill=white)
    # 数据点阵抽几个
    for mx, my in ((64, 64), (72, 64), (64, 72), (50, 32), (32, 50), (56, 56)):
        draw.rectangle([s(mx), s(my), s(mx + 4), s(my + 4)], fill=light)
    draw.rectangle([s(48), s(48), s(48 + 5), s(48 + 5)], fill=cyan)
    # 扫描线
    draw.line([s(25), s(54), s(83), s(54)], fill=cyan, width=max(1, s(2)))
    return img


def set_window_icon(root):
    # 任务栏图标：Tk 的 iconphoto 会写 X11 _NET_WM_ICON，这正是 KeymouseGo
    # （Qt setWindowIcon）能显示而我们之前不能的原因；.desktop 只管启动器菜单。
    # 失败静默（退回当前无图标状态，不影响运行）。
    try:
        photo = ImageTk.PhotoImage(make_window_icon())
        root.iconphoto(True, photo)
        root.icon_image_ref = photo
    except Exception as exc:
        write_log("debug", "窗口图标设置失败（不影响运行）: " + str(exc))


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
        + " interval_ms=" + str(APP_INTERVAL_MS) + " box=" + str(APP_BOX_SIZE)
        + " preview_box=" + str(APP_PREVIEW_BOX),
    )


def main():
    log_startup_info()
    # className 决定窗口 WM_CLASS，launcher 用 StartupWMClass=Qrtool 做任务栏归组。
    # 注意 Tk 会把类名归一化为首字母大写其余小写，实测 "QrTool" 会变成 "Qrtool"，
    # 所以这里直接写归一化后的形式，保证与 .desktop 完全一致（大小写敏感）。
    root = tk.Tk(className="Qrtool")
    set_window_icon(root)
    QrApp(root)
    try:
        root.mainloop()
    except Exception:
        write_log("debug", "主循环异常退出\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()