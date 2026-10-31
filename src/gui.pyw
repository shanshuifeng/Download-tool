#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载工具 · 极简界面（依赖同目录 downloader.py）

设计方向：Brutally Minimal —— 近黑底、单一青柠强调色、细线分隔、大留白。

DPI：进程声明 per-monitor 感知后再建窗口，并按 DPI 比例缩放所有像素尺寸，
否则 Windows 会把整个窗口当位图放大，文字和细线全糊。
"""

import json
import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

# ---------------- DPI：必须在任何窗口创建之前 ----------------
_REAL_DPI = 96
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
    _REAL_DPI = ctypes.windll.user32.GetDpiForSystem() or 96
except Exception:
    pass

SCALE = max(1.0, _REAL_DPI / 96.0)


def S(v):
    """逻辑像素 → 物理像素"""
    return int(round(v * SCALE))


if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE)


def _cfg_home():
    """配置目录：U 盘（非用户目录）放 exe 旁边；装在本机则放 AppData"""
    if not getattr(sys, "frozen", False):
        return BASE
    home = os.path.abspath(os.path.expanduser("~")).lower()
    if os.path.abspath(BASE).lower().startswith(home):
        d = os.path.join(os.environ.get("APPDATA", BASE), "下载工具")
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            return BASE
    return BASE


from downloader import human  # noqa: E402
from taskqueue import DownloadQueue  # noqa: E402

CFG = os.path.join(_cfg_home(), "config.json")

# ---- design tokens ----
BG = "#0B0C0D"
SURFACE = "#131517"
SURFACE_2 = "#191C1F"
HAIRLINE = "#232629"
TEXT = "#EDEEEF"
MUTED = "#7A8188"
ACCENT = "#C6F24E"
ACCENT_HOVER = "#D4FF63"
ON_ACCENT = "#0B0C0D"
ERR = "#FF6B6B"
WARN = "#FFC857"
PLACEHOLDER = "#5E656C"

F_TITLE = ("Microsoft YaHei UI", 19, "bold")
F_BODY = ("Microsoft YaHei UI", 10)
F_SMALL = ("Microsoft YaHei UI", 9)
F_LABEL = ("Microsoft YaHei UI", 10)
F_MONO = ("Consolas", 10)
F_MONO_S = ("Consolas", 9)

DEFAULTS = {
    "last_url": "",
    "last_dir": os.path.join(os.path.expanduser("~"), "Downloads"),
    "threads": 16,
    "chunk_mb": 0,
    "slow_kb": 15,
    "slow_sec": 12,
    "retries": 6,
    "timeout": 30,
    "max_speed_kb": 0,
    "proxy": "",
    "concurrent": 2,
    "extra_mirrors": "",
    "advanced_open": False,
}


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(CFG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def dark_titlebar(win):
    """Win10/11 深色标题栏，让窗口边框和内容一致"""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


# ---------------- 自绘控件 ----------------
def _round_pts(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class Button(tk.Canvas):
    """扁平圆角按钮，自绘以摆脱系统控件观感"""

    def __init__(self, master, text, command=None, kind="primary", height=46,
                 radius=10, width=None):
        super().__init__(master, height=S(height), bg=master["bg"],
                         highlightthickness=0, bd=0)
        if width:
            self.configure(width=S(width))
        self.text = text
        self.command = command
        self.kind = kind
        self.radius = S(radius)
        self._state = "normal"
        self._hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", lambda e: self._draw())
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._hover_to(True))
        self.bind("<Leave>", lambda e: self._hover_to(False))
        self.configure(cursor="hand2")

    def _colors(self):
        if self._state == "disabled":
            return HAIRLINE, MUTED
        if self.kind == "primary":
            return (ACCENT_HOVER if self._hover else ACCENT), ON_ACCENT
        return (SURFACE_2 if self._hover else SURFACE), (TEXT if self._hover else MUTED)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < S(4):
            return
        fill, fg = self._colors()
        self.create_polygon(_round_pts(1, 1, w - 1, h - 1, self.radius),
                            smooth=True, fill=fill, outline="")
        font = (F_LABEL[0], 10, "bold") if self.kind == "primary" else F_LABEL
        self.create_text(w // 2, h // 2, text=self.text, fill=fg, font=font)

    def _hover_to(self, v):
        self._hover = v
        self._draw()

    def _release(self, _):
        if self._state == "normal" and self.command:
            self.command()

    def set_text(self, t):
        self.text = t
        self._draw()

    def set_state(self, s):
        self._state = s
        self.configure(cursor="hand2" if s == "normal" else "arrow")
        self._draw()

    def set_kind(self, kind):
        self.kind = kind
        self._draw()


class Slider(tk.Canvas):
    """极简滑杆：细轨道 + 圆形滑块 + 右侧等宽数值"""

    def __init__(self, master, lo, hi, value, step=1, fmt=None, label_w=84):
        super().__init__(master, height=S(30), bg=master["bg"],
                         highlightthickness=0, bd=0)
        self.lo, self.hi, self.step = lo, hi, step
        self.value = value
        self.fmt = fmt or (lambda v: str(v))
        self.label_w = S(label_w)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._drag)
        self.configure(cursor="hand2")

    def _track_w(self):
        return max(S(10), self.winfo_width() - self.label_w)

    def _x_of(self, v):
        t = 0 if self.hi == self.lo else (v - self.lo) / (self.hi - self.lo)
        return S(4) + t * (self._track_w() - S(8))

    def _drag(self, e):
        w = self._track_w() - S(8)
        t = max(0.0, min(1.0, (e.x - S(4)) / max(1, w)))
        v = self.lo + t * (self.hi - self.lo)
        v = int(round(v / self.step) * self.step)
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v
            self._draw()

    def set(self, v):
        self.value = max(self.lo, min(self.hi, int(v)))
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < S(20):
            return
        cy = h // 2
        x1, x2 = S(4), self._track_w() - S(4)
        lw = max(1, S(3))
        knob = S(6)
        self.create_line(x1, cy, x2, cy, fill=HAIRLINE, width=lw, capstyle="round")
        kx = self._x_of(self.value)
        if kx > x1:
            self.create_line(x1, cy, kx, cy, fill=ACCENT, width=lw, capstyle="round")
        self.create_oval(kx - knob, cy - knob, kx + knob, cy + knob,
                         fill=ACCENT, outline=BG, width=max(1, S(2)))
        self.create_text(w - S(2), cy, text=self.fmt(self.value), anchor="e",
                         fill=TEXT, font=F_MONO_S)


class ThinBar(tk.Canvas):
    """细进度线"""

    def __init__(self, master):
        super().__init__(master, height=S(4), bg=master["bg"],
                         highlightthickness=0, bd=0)
        self.pct = 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, pct):
        self.pct = max(0.0, min(100.0, pct))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < S(4):
            return
        y = self.winfo_height() // 2
        lw = max(1, S(2))
        self.create_line(0, y, w, y, fill=HAIRLINE, width=lw)
        if self.pct > 0:
            self.create_line(0, y, max(lw, w * self.pct / 100), y,
                             fill=ACCENT, width=lw)


class HintEntry(tk.Entry):
    """带占位提示的输入框"""

    def __init__(self, master, hint="", **kw):
        super().__init__(master, **kw)
        self.hint = hint
        self._empty = True
        self.config(fg=PLACEHOLDER)
        self.insert(0, hint)
        self.bind("<FocusIn>", self._in)
        self.bind("<FocusOut>", self._out)

    def _in(self, _=None):
        if self._empty:
            self.delete(0, "end")
            self.config(fg=TEXT)
            self._empty = False

    def _out(self, _=None):
        if not super().get().strip():
            self.delete(0, "end")
            self.insert(0, self.hint)
            self.config(fg=PLACEHOLDER)
            self._empty = True

    def value(self):
        return "" if self._empty else super().get().strip()


class SlimScroll(tk.Canvas):
    """细滚动条，替换系统原生滚动条"""

    def __init__(self, master, target):
        super().__init__(master, width=S(5), bg=BG, highlightthickness=0, bd=0)
        self.target = target
        self.target.configure(yscrollcommand=self._on_set)
        self.first, self.last = 0.0, 1.0
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._jump)
        self.bind("<B1-Motion>", self._jump)

    def _on_set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def _draw(self):
        self.delete("all")
        h = self.winfo_height()
        if h < S(10) or (self.last - self.first) >= 0.999:
            return
        y1 = self.first * h
        y2 = max(y1 + S(20), self.last * h)
        self.create_line(S(2), y1 + S(2), S(2), y2 - S(2), fill="#3C4247",
                         width=max(1, S(3)), capstyle="round")

    def _jump(self, e):
        h = max(1, self.winfo_height())
        self.target.yview_moveto(max(0.0, min(1.0, e.y / h)))


# ---------------- 说明弹窗 ----------------
HELP_ROWS = [
    ("下载链接", "支持 http/https 直链。一行一个；贴多行会被当作同一个文件的镜像，"
                 "自动测速后挑最快的用。GitHub 的 release 链接会自动补 3 个加速源。", "必填"),
    ("保存到", "填目录就沿用服务器给的文件名；填完整文件名可以改名。", "默认「下载」文件夹"),
    ("线程数", "同时下载的分片数量。家用宽带 8–16 比较合适；开太高会被服务端限速或触发风控，反而更慢。", "16"),
    ("分片大小", "每片多大。0 = 自动按文件大小均分（1–32MB）。超大文件可固定 8–16MB 降低重试成本；小文件建议留自动。", "自动"),
    ("慢速断开", "某一片速度持续低于这个值时，断开重连换镜像，避免卡在坏连接上。设为 0 关闭该机制。", "15 KB/s"),
    ("慢速时长", "速度要持续低于阈值多久才判定为慢链。设太短会频繁重连，设太长会白等。", "12 秒"),
    ("重试次数", "单片失败后换镜像重试的次数。网络差可以调大，镜像多时也建议调大。", "6 次"),
    ("连接超时", "单次请求多久没响应就放弃。跨境线路慢可以调到 45–60 秒。", "30 秒"),
    ("SHA256", "服务器公布的校验值（sha1/md5 也能自动识别）。留空则只核对文件大小；"
               "经镜像下载时强烈建议填写——镜像只保证连通，不保证内容。", "可留空"),
    ("额外镜像", "逗号分隔的镜像前缀，会拼在链接前面。例如 https://ghfast.top/", "可留空"),
]


class HelpDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("参数说明")
        self.configure(bg=BG)
        self.geometry(f"{S(680)}x{S(640)}")
        self.minsize(S(560), S(480))
        self.transient(master)
        dark_titlebar(self)
        self.after(200, lambda: dark_titlebar(self))

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=S(32), pady=(S(28), S(4)))
        tk.Label(head, text="参数说明", bg=BG, fg=TEXT, font=F_TITLE).pack(anchor="w")
        tk.Label(head, text="每个调节项的作用，以及什么时候该动它。",
                 bg=BG, fg=MUTED, font=F_SMALL).pack(anchor="w", pady=(S(6), 0))

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(24), pady=(S(18), S(8)))

        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        slim = SlimScroll(wrap, canvas)
        slim.pack(side="right", fill="y", padx=(S(8), 0))
        canvas.pack(side="left", fill="both", expand=True)

        def _wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self.bind("<MouseWheel>", _wheel)

        desc_labels = []

        def _fit(_=None):
            w = canvas.winfo_width()
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure("inner", width=w)
            for lb in desc_labels:
                lb.configure(wraplength=max(S(220), w - S(56)))
        inner.bind("<Configure>", _fit)
        canvas.bind("<Configure>", _fit)

        for name, desc, default in HELP_ROWS:
            row = tk.Frame(inner, bg=BG)
            row.pack(fill="x", pady=(0, S(18)), padx=(S(8), S(14)))
            top = tk.Frame(row, bg=BG)
            top.pack(fill="x")
            tk.Label(top, text=name, bg=BG, fg=TEXT,
                     font=(F_BODY[0], 10, "bold")).pack(side="left")
            tk.Label(top, text=default, bg=BG, fg=ACCENT,
                     font=F_MONO_S).pack(side="right")
            d = tk.Label(row, text=desc, bg=BG, fg=MUTED, font=F_SMALL,
                         justify="left", wraplength=S(520))
            d.pack(anchor="w", pady=(S(4), 0))
            desc_labels.append(d)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=S(32), pady=(S(4), S(24)))
        tk.Label(foot, text="设置自动保存在 config.json，跟着 exe 走。",
                 bg=BG, fg=MUTED, font=F_SMALL).pack(side="left")
        Button(foot, "知道了", self.destroy, kind="ghost",
               height=34, width=110).pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())
        self.after(60, self._center)

    def _center(self):
        self.update_idletasks()
        x = self.master.winfo_rootx() + (self.master.winfo_width() - self.winfo_width()) // 2
        y = self.master.winfo_rooty() + S(50)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")


# ---------------- 主界面 ----------------
class TaskRow(tk.Frame):
    """任务列表的一行：标题 + 进度线 + 状态 + 行内操作。"""

    def __init__(self, master, tid, title, on_action):
        super().__init__(master, bg=BG)
        self.tid = tid
        self.path = None
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x")
        self.lbl = tk.Label(head, text=title, bg=BG, fg=TEXT, font=F_MONO_S,
                            anchor="w")
        self.lbl.pack(side="left", fill="x", expand=True)
        self.btn = Button(head, "取消", lambda: on_action(tid), kind="ghost",
                          height=22, width=52)
        self.btn.pack(side="right")
        self.bar = ThinBar(self)
        self.bar.pack(fill="x", pady=(S(5), 0))
        self.stat = tk.Label(self, text="排队中", bg=BG, fg=MUTED, font=F_SMALL,
                             anchor="w")
        self.stat.pack(fill="x", pady=(S(3), S(10)))


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_cfg()
        self.q = queue.Queue()
        self.rows = {}
        self._clip_seen = ""
        self._list_shown = False
        self._clear_shown = False
        self.queue = DownloadQueue(
            concurrent=int(self.cfg.get("concurrent", 2)),
            on_event=lambda kind, tid, **kw: self.q.put(
                ("task", (kind, tid, kw))))
        self._build()
        self.root.after(80, self._drain)
        self.root.after(1200, self._watch_clip)

    def _build(self):
        r = self.root
        r.title("下载")
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        W, H = S(600), min(S(430), sh - S(120))
        r.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(S(24), (sh - H) // 2 - S(40))}")
        r.minsize(S(520), S(440))
        r.configure(bg=BG)
        try:
            r.iconbitmap(os.path.join(BASE, "icon.ico"))
        except Exception:
            pass
        dark_titlebar(r)
        r.after(200, lambda: dark_titlebar(r))

        PAD = S(30)
        HAIR = max(1, S(1))

        # 底部操作区先占位：窗口再矮也不会把主按钮挤出屏幕
        bottom = tk.Frame(r, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=PAD, pady=(S(16), S(20)))

        content = tk.Frame(r, bg=BG)
        content.pack(side="top", fill="both", expand=True)

        # 顶栏
        top = tk.Frame(content, bg=BG)
        top.pack(fill="x", padx=PAD, pady=(S(24), 0))
        tk.Label(top, text="下载", bg=BG, fg=TEXT, font=F_TITLE).pack(side="left")
        Button(top, "参数说明", self._help, kind="ghost",
               height=30, width=96).pack(side="right")

        tk.Label(content, text="粘贴链接，选好位置，开始。", bg=BG, fg=MUTED,
                 font=F_SMALL).pack(anchor="w", padx=PAD, pady=(S(2), S(18)))

        # 链接输入
        self.txt_url = tk.Text(content, height=2, bg=SURFACE, fg=TEXT,
                               insertbackground=ACCENT, relief="flat", font=F_MONO,
                               wrap="none", bd=0, padx=S(14), pady=S(12),
                               highlightthickness=0,
                               selectbackground="#2E3A1F", selectforeground=TEXT)
        self.txt_url.pack(fill="x", padx=PAD)
        self.txt_url.bind("<FocusIn>", self._clear_placeholder)
        self.txt_url.bind("<FocusOut>", lambda e: self._restore_placeholder())
        self._restore_placeholder()

        # 保存位置
        row = tk.Frame(content, bg=BG)
        row.pack(fill="x", padx=PAD, pady=(S(14), 0))
        tk.Label(row, text="保存到", bg=BG, fg=MUTED, font=F_SMALL).pack(side="left")
        self.lbl_dir = tk.Label(row, text=self._short(self.cfg["last_dir"]), bg=BG,
                                fg=TEXT, font=F_MONO_S, anchor="w")
        self.lbl_dir.pack(side="left", padx=(S(12), S(8)), fill="x", expand=True)
        Button(row, "更改", self._pick_dir, kind="ghost",
               height=26, width=58).pack(side="right")

        # 任务列表（空时完全不占空间）
        self.listwrap = tk.Frame(content, bg=BG)
        self.lb_canvas = tk.Canvas(self.listwrap, bg=BG, height=S(1),
                                   highlightthickness=0, bd=0)
        self.lb_inner = tk.Frame(self.lb_canvas, bg=BG)
        self._lb_win = self.lb_canvas.create_window((0, 0), window=self.lb_inner,
                                                    anchor="nw")
        self.lb_scroll = SlimScroll(self.listwrap, self.lb_canvas)
        self.lb_scroll.configure(height=S(1))   # 否则 Canvas 默认高度会把窗口顶高
        self.lb_scroll.pack(side="right", fill="y", padx=(S(8), 0))
        self.lb_canvas.pack(side="left", fill="both", expand=True)
        self.lb_inner.bind("<Configure>", lambda e: self._fit_list())
        self.lb_canvas.bind(
            "<Configure>",
            lambda e: self.lb_canvas.itemconfigure(self._lb_win, width=e.width))

        # 分隔线
        tk.Frame(content, bg=HAIRLINE, height=HAIR).pack(fill="x", padx=PAD,
                                                         pady=(S(22), 0))

        # 高级设置
        head = tk.Frame(content, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(S(14), 0))
        self.lbl_adv = tk.Label(head, text="高级设置", bg=BG, fg=MUTED,
                                font=F_SMALL, cursor="hand2")
        self.lbl_adv.pack(side="left")
        self.lbl_chev = tk.Label(head, text="›", bg=BG, fg=MUTED,
                                 font=(F_BODY[0], 12), cursor="hand2")
        self.lbl_chev.pack(side="left", padx=S(6))
        for w in (self.lbl_adv, self.lbl_chev):
            w.bind("<Button-1>", lambda e: self._toggle_adv())

        self.adv = tk.Frame(content, bg=BG)
        self._build_adv(self.adv)
        if self.cfg.get("advanced_open"):
            self.adv.pack(fill="x", padx=PAD, pady=(S(10), 0))
            self.lbl_chev.config(text="⌄")
            self.lbl_adv.config(fg=TEXT)
            r.after(60, self._fit_height)

        # 底部操作区内容
        self.btn_main = Button(bottom, "开始下载", self._start, kind="primary", height=50)
        self.btn_main.pack(fill="x")

        self.bar = ThinBar(bottom)
        self.bar.pack(fill="x", pady=(S(12), 0))

        stat = tk.Frame(bottom, bg=BG)
        stat.pack(fill="x", pady=(S(10), 0))
        self.lbl_state = tk.Label(stat, text="就绪", bg=BG, fg=MUTED, font=F_SMALL)
        self.lbl_state.pack(side="left")
        self.lbl_stat = tk.Label(stat, text="", bg=BG, fg=MUTED, font=F_MONO_S)
        self.lbl_stat.pack(side="right")
        self.lbl_clear = tk.Label(stat, text="清除已完成", bg=BG, fg=MUTED,
                                  font=F_SMALL, cursor="hand2")
        self.lbl_clear.bind("<Button-1>", lambda e: self._clear_finished())

        self.log = tk.Text(bottom, height=2, bg=BG, fg=MUTED, relief="flat", bd=0,
                           font=F_MONO_S, wrap="word", state="disabled",
                           highlightthickness=0, padx=0, pady=0)
        self.log.pack(fill="x", pady=(S(12), 0))
        for tag, c in (("ok", ACCENT), ("warn", WARN), ("err", ERR), ("dim", MUTED)):
            self.log.tag_configure(tag, foreground=c)

    def _build_adv(self, parent):
        rows = [
            ("线程数", "threads", 1, 32, 1, lambda v: f"{v} 线程"),
            ("分片", "chunk_mb", 0, 32, 1, lambda v: "自动" if v == 0 else f"{v} MB"),
            ("慢速断开", "slow_kb", 0, 200, 5, lambda v: "关闭" if v == 0 else f"{v} KB/s"),
            ("慢速时长", "slow_sec", 3, 60, 1, lambda v: f"{v} 秒"),
            ("重试", "retries", 0, 20, 1, lambda v: f"{v} 次"),
            ("超时", "timeout", 5, 120, 5, lambda v: f"{v} 秒"),
            ("限速", "max_speed_kb", 0, 10240, 128,
             lambda v: "不限" if v == 0 else f"{v} KB/s"),
            ("并发任务", "concurrent", 1, 4, 1, lambda v: f"{v} 个"),
        ]
        self.sliders = {}
        for label, key, lo, hi, step, fmt in rows:
            line = tk.Frame(parent, bg=BG)
            line.pack(fill="x", pady=S(1))
            tk.Label(line, text=label, bg=BG, fg=MUTED, font=F_SMALL,
                     width=9, anchor="w").pack(side="left")
            s = Slider(line, lo, hi, int(self.cfg.get(key, DEFAULTS[key])),
                       step=step, fmt=fmt)
            s.pack(side="left", fill="x", expand=True, padx=(S(10), 0))
            self.sliders[key] = s

        hrow = tk.Frame(parent, bg=BG)
        hrow.pack(fill="x", pady=(S(10), 0))
        tk.Label(hrow, text="SHA256", bg=BG, fg=MUTED, font=F_SMALL,
                 width=9, anchor="w").pack(side="left")
        self.ent_sha = HintEntry(hrow, hint="可选：服务器公布的校验值", bg=SURFACE,
                                 fg=TEXT, insertbackground=ACCENT, relief="flat",
                                 font=F_MONO_S, bd=0, highlightthickness=0)
        self.ent_sha.pack(side="left", fill="x", expand=True, padx=(S(10), 0),
                          ipady=S(6), ipadx=S(8))

        mrow = tk.Frame(parent, bg=BG)
        mrow.pack(fill="x", pady=(S(8), 0))
        tk.Label(mrow, text="镜像", bg=BG, fg=MUTED, font=F_SMALL,
                 width=9, anchor="w").pack(side="left")
        self.ent_mirror = HintEntry(mrow, hint="可选：镜像前缀，逗号分隔", bg=SURFACE,
                                    fg=TEXT, insertbackground=ACCENT, relief="flat",
                                    font=F_MONO_S, bd=0, highlightthickness=0)
        self.ent_mirror.pack(side="left", fill="x", expand=True, padx=(S(10), 0),
                             ipady=S(6), ipadx=S(8))
        if self.cfg.get("extra_mirrors"):
            self.ent_mirror._in()
            self.ent_mirror.insert(0, self.cfg["extra_mirrors"])

        prow = tk.Frame(parent, bg=BG)
        prow.pack(fill="x", pady=(S(8), 0))
        tk.Label(prow, text="代理", bg=BG, fg=MUTED, font=F_SMALL,
                 width=9, anchor="w").pack(side="left")
        self.ent_proxy = HintEntry(prow, hint="留空跟随系统代理，direct=直连", bg=SURFACE,
                                   fg=TEXT, insertbackground=ACCENT, relief="flat",
                                   font=F_MONO_S, bd=0, highlightthickness=0)
        self.ent_proxy.pack(side="left", fill="x", expand=True, padx=(S(10), 0),
                            ipady=S(6), ipadx=S(8))
        if self.cfg.get("proxy"):
            self.ent_proxy._in()
            self.ent_proxy.insert(0, self.cfg["proxy"])

    # ---------- 小工具 ----------
    @staticmethod
    def _short(p, n=48):
        p = str(p)
        return p if len(p) <= n else p[:16] + " … " + p[-(n - 20):]

    def _restore_placeholder(self):
        if self.txt_url.get("1.0", "end").strip():
            return
        last = self.cfg.get("last_url", "").strip()
        if last:
            self.txt_url.insert("1.0", last)
        else:
            self.txt_url.insert("1.0", "https://…")
            self.txt_url.tag_add("ph", "1.0", "end")
            self.txt_url.tag_configure("ph", foreground=PLACEHOLDER)

    def _clear_placeholder(self, _=None):
        if self.txt_url.tag_ranges("ph"):
            self.txt_url.delete("1.0", "end")
            self.txt_url.tag_remove("ph", "1.0", "end")

    def _fit_height(self):
        """按内容实际需要的高度调整窗口，避免展开后被裁切"""
        r = self.root
        r.update_idletasks()
        need = r.winfo_reqheight()
        max_h = r.winfo_screenheight() - S(120)
        h = min(max_h, max(S(430), need))
        r.geometry(f"{r.winfo_width()}x{h}")

    def _toggle_adv(self):
        if self.adv.winfo_ismapped():
            self.adv.pack_forget()
            self.lbl_chev.config(text="›")
            self.lbl_adv.config(fg=MUTED)
            self.cfg["advanced_open"] = False
        else:
            self.adv.pack(fill="x", padx=S(30), pady=(S(10), 0))
            self.lbl_chev.config(text="⌄")
            self.lbl_adv.config(fg=TEXT)
            self.cfg["advanced_open"] = True
        self._fit_height()
        save_cfg(self.cfg)

    def _help(self):
        HelpDialog(self.root)

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.cfg["last_dir"])
        if d:
            self.cfg["last_dir"] = d
            self.lbl_dir.config(text=self._short(d))
            save_cfg(self.cfg)

    def _say(self, msg, level="dim"):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n", level)
        self.log.see("end")
        self.log.config(state="disabled")

    # ---------- 下载 ----------
    def _start(self):
        raw = self.txt_url.get("1.0", "end").strip()
        urls = [ln.strip() for ln in raw.splitlines()
                if ln.strip() and not ln.strip().startswith("#") and "…" not in ln]
        if not urls:
            messagebox.showwarning("缺少链接", "请先粘贴下载链接。")
            return
        extra = [m.strip() for m in self.ent_mirror.value().split(",") if m.strip()]
        for m in extra:
            if m.endswith("/"):
                urls += [m + urls[0]]

        self.cfg.update(last_url=raw, extra_mirrors=self.ent_mirror.value(),
                        proxy=self.ent_proxy.value(),
                        advanced_open=bool(self.adv.winfo_ismapped()))
        for k, s in self.sliders.items():
            self.cfg[k] = s.value
        save_cfg(self.cfg)
        # 并发数改了要立刻生效，否则滑杆是死的
        self.queue.concurrent = max(1, int(self.cfg["concurrent"]))

        tid = self.queue.add(
            urls, self.cfg["last_dir"],
            threads=self.cfg["threads"], chunk_mb=self.cfg["chunk_mb"] or None,
            slow_kb=self.cfg["slow_kb"], slow_sec=self.cfg["slow_sec"],
            retries=self.cfg["retries"], timeout=self.cfg["timeout"],
            proxy=self.cfg["proxy"] or None,
            max_speed_kb=self.cfg["max_speed_kb"],
            sha256=self.ent_sha.value() or None,
        )
        row = TaskRow(self.lb_inner, tid, self._short(urls[0], 64), self._task_action)
        row.pack(fill="x")
        self.rows[tid] = row
        if not self._list_shown:
            self.listwrap.pack(fill="x", padx=S(30), pady=(S(6), S(16)))
            self._list_shown = True
        self.txt_url.delete("1.0", "end")
        self.txt_url.insert("1.0", "https://…")
        self.txt_url.tag_add("ph", "1.0", "end")
        self.txt_url.tag_configure("ph", foreground=PLACEHOLDER)
        self._fit_list()
        self._fit_height()

    def _task_action(self, tid):
        """行内按钮：运行中=取消，已完成=打开，失败/取消=移除该行。"""
        st = self.queue.state_of(tid)
        row = self.rows.get(tid)
        if st in ("queued", "running"):
            self.queue.cancel(tid)
            if row:
                row.stat.config(text="正在取消…", fg=WARN)
            return
        if row and row.path and os.path.exists(row.path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(row.path)])
            return
        if row and row.path:
            # 文件被移走或删掉了：一次点击就把整行静默抹掉，用户会以为还能打开
            messagebox.showinfo(
                "文件不在了",
                f"找不到这个文件：\n{row.path}\n\n可以再点一次按钮，把它从列表里移除。")
            row.path = None
            row.stat.config(text="完成（文件已不在）", fg=MUTED)
            row.btn.set_text("移除")
            return
        if row:
            self.queue.forget(tid)
            row.destroy()
            self.rows.pop(tid, None)
            if not self.rows and self._list_shown:
                self.listwrap.pack_forget()
                self._list_shown = False
            self._fit_list()
            self._fit_height()
            self._refresh_bottom()

    def _clear_finished(self):
        """把已结束的任务从列表与统计里一起摘掉，底部汇总才能真正复位。"""
        for tid in list(self.rows):
            if self.queue.state_of(tid) in ("done", "failed", "cancelled"):
                self.queue.forget(tid)
                self.rows.pop(tid).destroy()
        if not self.rows and self._list_shown:
            self.listwrap.pack_forget()
            self._list_shown = False
        self._fit_list()
        self._fit_height()
        self._refresh_bottom()

    def _on_task(self, kind, tid, kw):
        row = self.rows.get(tid)
        if kind == "progress":
            d = kw.get("data") or {}
            if not row:
                return
            phase = d.get("phase")
            if phase == "downloading":
                pct = d.get("percent", 0)
                row.bar.set(pct)
                sp = d.get("speed") or 0
                eta = ""
                if sp > 0 and d.get("total"):
                    left = int((d["total"] - d["done"]) / sp)
                    eta = f"  ·  剩余 {left // 60:02d}:{left % 60:02d}"
                row.stat.config(
                    text=f"{pct:.0f}%  {human(d.get('done', 0))}/{human(d.get('total', 0))}"
                         f"  {human(sp)}/s{eta}", fg=TEXT)
            elif phase == "verifying":
                row.stat.config(text="校验中…", fg=TEXT)
        elif kind == "log":
            lv = kw.get("level")
            if lv in ("warn", "error"):
                self._say(kw.get("msg", ""), "warn" if lv == "warn" else "err")
        elif kind == "state":
            st = kw.get("state")
            if not row:
                return
            if st == "queued":
                row.stat.config(text="排队中", fg=MUTED)
            elif st == "running":
                row.stat.config(text="连接中…", fg=TEXT)
            elif st == "done":
                row.path = kw.get("path")
                row.bar.set(100)
                row.stat.config(text=f"完成  {self._short(row.path or '', 44)}", fg=ACCENT)
                row.btn.set_text("打开")
                self._say(f"✓ {row.path}", "ok")
            else:
                msg = kw.get("message") or ("已取消" if st == "cancelled" else "失败")
                row.stat.config(text=msg, fg=WARN if st == "cancelled" else ERR)
                row.btn.set_text("移除")
                self._say(("" if st == "cancelled" else "✗ ") + msg,
                          "dim" if st == "cancelled" else "err")
        self._refresh_bottom()

    def _refresh_bottom(self):
        s = self.queue.stats()
        finished = s["done"] + s["failed"] + s["cancelled"]
        if finished and not self._clear_shown:
            self.lbl_clear.pack(side="right", padx=(0, S(14)))
            self._clear_shown = True
        elif not finished and self._clear_shown:
            self.lbl_clear.pack_forget()
            self._clear_shown = False
        if not s["total"]:
            self.lbl_state.config(text="就绪", fg=MUTED)
            self.lbl_stat.config(text="")
            self.bar.set(0)
            return
        bits = []
        if s["running"]:
            bits.append(f"进行中 {s['running']}")
        if s["queued"]:
            bits.append(f"等待 {s['queued']}")
        if s["done"]:
            bits.append(f"完成 {s['done']}")
        if s["failed"]:
            bits.append(f"失败 {s['failed']}")
        if s["cancelled"]:
            bits.append(f"取消 {s['cancelled']}")
        active = s["running"] + s["queued"]
        color = ERR if s["failed"] else (TEXT if active else ACCENT)
        self.lbl_state.config(text="  ·  ".join(bits), fg=color)
        self.lbl_stat.config(text=f"共 {s['total']} 个")
        self.bar.set(s["done"] / s["total"] * 100)

    def _fit_list(self):
        """列表高度按内容收缩，最多露三行，超出用细滚动条。"""
        h = self.lb_inner.winfo_reqheight()
        self.lb_canvas.configure(height=min(h, S(3 * 64)) if h else S(1))
        box = self.lb_canvas.bbox("all")
        self.lb_canvas.configure(scrollregion=box or (0, 0, 0, h))

    def _url_box_empty(self):
        """输入框里只有占位符时，算空。"""
        if self.txt_url.tag_ranges("ph"):
            return True
        return not self.txt_url.get("1.0", "end").strip()

    def _watch_clip(self, _=None):
        """剪贴板里出现直链且输入框为空时自动填入；同一链接只提一次。"""
        try:
            txt = self.root.clipboard_get().strip()
            if (txt != self._clip_seen and txt.startswith(("http://", "https://"))
                    and len(txt) < 2048 and "…" not in txt
                    and self._url_box_empty()):
                self._clip_seen = txt
                self.txt_url.delete("1.0", "end")
                self.txt_url.insert("1.0", txt)
                self.txt_url.tag_remove("ph", "1.0", "end")
                self._say("已从剪贴板填入链接", "ok")
        except Exception:  # noqa: BLE001
            pass
        self.root.after(900, self._watch_clip)

    def _drain(self):
        """主线程唯一改控件的地方：把工作线程的事件搬进来。"""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "task":
                    self._on_task(*payload)
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
