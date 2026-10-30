"""سكاي البسيط — واجهة بوت كلاش أوف كلانس (عربي / English)."""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import cv2
from PIL import Image, ImageTk

from bot import config as cfgmod
from bot import i18n
from bot import license as lic
from bot.adb import ADB, find_adb, ldplayer_instances
from bot.army import ArmyBook
from bot.notify import Notifier
from bot.builder import BuilderFarmer
from bot.farm import Farmer, slot_type
from bot.i18n import BUTTON_GROUPS, btn_name, t
from bot.vision import Templates

VERSION = "2.3"
LICENSE_RECHECK_MS = 30 * 60 * 1000
LICENSE_MAX_NET_FAILS = 4  # ساعتان بلا إنترنت ثم يتوقف
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
    RES = getattr(sys, "_MEIPASS", BASE)
else:
    BASE = RES = os.path.dirname(os.path.abspath(__file__))
# ملف شخصي لكل محاكٍ: SkySimple.exe --profile 2  ← config_2.json و stats_2.json وصور جيش مستقلة
PROFILE = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv[:-1] else ""
SUFFIX = f"_{PROFILE}" if PROFILE else ""
CONFIG_PATH = os.path.join(BASE, f"config{SUFFIX}.json")
STATS_PATH = os.path.join(BASE, f"stats{SUFFIX}.json")

# الألوان: (فاتح، داكن)
BG = ("#eef2f6", "#0d1218")
SIDEBAR = ("#ffffff", "#111922")
CARD = ("#ffffff", "#16202b")
BORDER = ("#dbe3ec", "#22303f")
ACCENT = "#1d9bf0"
ACCENT_HOVER = "#1683cc"
TEXT = ("#16202b", "#e6edf3")
MUTED = ("#66768a", "#8b9bab")
OK = "#22c55e"
DANGER = "#ef4444"
DANGER_HOVER = "#c93636"
WARN = "#f59e0b"
FIELD = ("#f4f7fa", "#0f1720")


def font(size=13, weight="normal"):
    return ("Segoe UI", size, weight) if not i18n.is_rtl() else ("Tahoma", size, weight)


def rtl(text):
    """في العربية: علامة RLM حول كل سطر حتى تظهر الرموز وعلامات الترقيم في الجهة الصحيحة."""
    if not i18n.is_rtl():
        return text
    return "\n".join("‏" + line + "‏" for line in str(text).split("\n"))


def ltr(text):
    """يثبّت اتجاه الأرقام والإحداثيات من اليسار لليمين داخل النص العربي."""
    return "‪" + str(text) + "‬" if i18n.is_rtl() else str(text)


def pt(p):
    return ltr(f"({p[0]}, {p[1]})")


class ScreenPicker(tk.Toplevel):
    """نافذة تعرض لقطة الشاشة. mode: region (سحب مربع)، point (نقرة)، line (سحب خط)."""

    def __init__(self, master, screen, on_done, mode="region", steps=None):
        super().__init__(master)
        self.steps = steps or []      # mode="points": أسماء النقاط المطلوبة بالترتيب
        self.points = []
        self.title(t("area_step", name=self.steps[0], i=1) if self.steps else t("picker_title"))
        self.configure(bg="#000000")
        self.screen, self.on_done, self.mode = screen, on_done, mode
        h, w = screen.shape[:2]
        maxw, maxh = self.winfo_screenwidth() - 80, self.winfo_screenheight() - 140
        self.scale = min(1.0, maxw / w, maxh / h)
        img = Image.fromarray(cv2.cvtColor(screen, cv2.COLOR_BGR2RGB))
        img = img.resize((int(w * self.scale), int(h * self.scale)))
        self.photo = ImageTk.PhotoImage(img)
        self.canvas = tk.Canvas(self, width=img.width, height=img.height, cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.start = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.focus_force()

    def _press(self, e):
        self.start = (e.x, e.y)

    def _drag(self, e):
        if not self.start or self.mode == "point":
            return
        self.canvas.delete("sel")
        if self.mode == "line":
            self.canvas.create_line(*self.start, e.x, e.y, fill="#00ff88", width=3, tags="sel")
        else:
            self.canvas.create_rectangle(*self.start, e.x, e.y, outline="#00ff88", width=2, tags="sel")

    def _release(self, e):
        if not self.start:
            return
        s = self.scale
        (x1, y1), (x2, y2) = self.start, (e.x, e.y)
        p1, p2 = (int(x1 / s), int(y1 / s)), (int(x2 / s), int(y2 / s))
        if self.mode == "points":
            self.points.append(p2)
            self.canvas.create_oval(e.x - 7, e.y - 7, e.x + 7, e.y + 7, fill="#00ff88", outline="#000")
            if len(self.points) < len(self.steps):
                i = len(self.points)
                self.title(t("area_step", name=self.steps[i], i=i + 1))
                return
            self.destroy()
            self.on_done(self.points)
            return
        self.destroy()
        if self.mode == "line":
            self.on_done(p1, p2)
        elif self.mode == "point":
            self.on_done(p1)
        else:
            xa, xb = sorted((p1[0], p2[0]))
            ya, yb = sorted((p1[1], p2[1]))
            crop = self.screen[ya:yb, xa:xb].copy() if xb - xa > 8 and yb - ya > 8 else None
            self.on_done(((xa + xb) // 2, (ya + yb) // 2), crop)


class ActivationDialog(ctk.CTkToplevel):
    """نافذة إدخال مفتاح التفعيل. تستدعي on_done(result) عند النجاح."""

    def __init__(self, app, client, on_done, message="", auto=False):
        super().__init__(app)
        self.app, self.client, self.on_done = app, client, on_done
        self.title(t("lic_title"))
        self.geometry("520x440")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        ico = os.path.join(RES, "assets", "icon.ico")
        if os.path.isfile(ico):
            self.after(250, lambda: self._icon(ico))
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        box = app.card(self)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        logo = os.path.join(RES, "assets", "logo.png")
        if os.path.isfile(logo):
            self.logo_img = ctk.CTkImage(Image.open(logo), size=(64, 64))
            ctk.CTkLabel(box, image=self.logo_img, text="").pack(pady=(18, 4))
        for text, size, weight, color, pady in ((t("lic_title"), 20, "bold", TEXT, 0),
                                                (t("lic_sub"), 12, "normal", MUTED, (2, 12))):
            lbl = app.label(box, text, size, weight, color=color)
            lbl.configure(anchor="center", justify="center")
            lbl.pack(fill="x", padx=24, pady=pady)
        app.label(box, t("lic_key"), 12, "bold").pack(fill="x", padx=24)
        self.entry = ctk.CTkEntry(box, font=("Consolas", 15), justify="center", height=42,
                                  fg_color=FIELD, border_color=BORDER, corner_radius=10,
                                  placeholder_text="SKY-XXXXX-XXXXX-XXXXX-XXXXX")
        self.entry.pack(fill="x", padx=24, pady=(4, 6))
        self.entry.insert(0, client.saved_key())
        self.entry.bind("<Return>", lambda e: self.activate())
        self.status = app.label(box, message, 12, "bold", color=DANGER, wraplength=430)
        self.status.pack(fill="x", padx=24, pady=(0, 6))

        dev = ctk.CTkFrame(box, fg_color="transparent")
        dev.pack(fill="x", padx=24, pady=(0, 10))
        app.label(dev, t("lic_device") + ":", 11, color=MUTED).pack(side=app.S)
        ctk.CTkLabel(dev, text=lic.short_id(client.hwid), font=("Consolas", 12),
                     text_color=MUTED).pack(side=app.S, padx=6)
        self.copy_btn = app.button(dev, t("lic_copy"), self.copy_id, kind="ghost", width=70, height=26)
        self.copy_btn.pack(side=app.E)

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 18))
        self.go = app.button(row, t("lic_activate"), self.activate, height=42)
        self.go.pack(side=app.S, fill="x", expand=True)
        app.button(row, t("lic_exit"), self.cancel, kind="ghost", width=90, height=42).pack(side=app.S, padx=(8, 0) if app.S == "left" else (0, 8))
        if app.winfo_viewable():  # تغيير المفتاح والنافذة الرئيسية ظاهرة: تبقى فوقها
            self.transient(app)
            self.grab_set()
        self.lift()
        self.after(150, lambda: (self.lift(), self.focus_force(), self.entry.focus_set()))
        if auto and self.entry.get().strip():
            self.after(300, self.activate)

    def _icon(self, ico):
        try:
            self.iconbitmap(ico)
        except tk.TclError:
            pass

    def cancel(self):
        """إن كان البرنامج مفعّلاً (تغيير مفتاح) تُغلق النافذة فقط، وإلا يُغلق البرنامج."""
        if self.app.license and self.app.license.ok:
            self.destroy()
        else:
            self.app._close()

    def copy_id(self):
        self.clipboard_clear()
        self.clipboard_append(self.client.hwid)
        self.copy_btn.configure(text=rtl(t("lic_copied")))

    def activate(self):
        key = self.entry.get().strip().upper()
        if not key or str(self.go.cget("state")) == "disabled":
            return
        self.go.configure(state="disabled", text=rtl(t("lic_checking")))
        self.status.configure(text="")

        def work():
            res = self.client.check(key)
            self.app.ui_q.put(lambda: self._done(key, res))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, key, res):
        if not self.winfo_exists():
            return
        self.go.configure(state="normal", text=rtl(t("lic_activate")))
        if not res.ok:
            self.status.configure(text=rtl(t("lic_err_" + (res.error or "invalid"))), text_color=DANGER)
            return
        self.client.save_key(key)
        self.destroy()
        self.on_done(res)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.license = None
        self.lic_client = None
        self._lic_fails = 0
        self._lic_job = None
        self._lic_dialog = None
        self.cfg = cfgmod.load(CONFIG_PATH)
        if PROFILE and self.cfg["attack"].get("army_dir", "army") == "army":
            self.cfg["attack"]["army_dir"] = f"army_{PROFILE}"
        i18n.set_lang(self.cfg.get("lang", "ar"))
        ctk.set_appearance_mode(self.cfg.get("appearance", "dark"))
        self.templates = Templates(os.path.join(BASE, "templates"))
        self.adb = None
        self.connected = False
        self.resolution = None
        self.farmer = None
        self.farmer_thread = None
        self.log_lines = []
        self.logq = queue.Queue()
        self.ui_q = queue.Queue()
        self.stats_db = self._load_stats_db()
        self._stats_seen = 0
        self.fields = {}
        self.page = "dashboard"

        self.title(f"{t('app_title')}  {VERSION}" + (f"  —  {PROFILE}" if PROFILE else ""))
        self.geometry("1180x760")
        self.minsize(1020, 680)
        ico = os.path.join(RES, "assets", "icon.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except tk.TclError:
                pass
        self.configure(fg_color=BG)
        self.build()
        self.log(t("log_welcome"))
        self.after(300, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ================= أدوات التخطيط =================
    @property
    def S(self):  # جهة البداية
        return "right" if i18n.is_rtl() else "left"

    @property
    def E(self):  # جهة النهاية
        return "left" if i18n.is_rtl() else "right"

    @property
    def A(self):
        return "e" if i18n.is_rtl() else "w"

    def label(self, parent, text, size=13, weight="normal", color=TEXT, **kw):
        return ctk.CTkLabel(parent, text=rtl(text), font=font(size, weight), text_color=color,
                            anchor=self.A, justify="right" if i18n.is_rtl() else "left", **kw)

    def card(self, parent, title=None, **kw):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER, **kw)
        if title:
            self.label(c, title, 15, "bold").pack(fill="x", padx=18, pady=(14, 6))
        return c

    def button(self, parent, text, command, kind="primary", **kw):
        colors = {
            "primary": (ACCENT, ACCENT_HOVER, "#ffffff"),
            "danger": (DANGER, DANGER_HOVER, "#ffffff"),
            "success": (OK, "#1a9e4b", "#ffffff"),
            "ghost": (("#e7edf3", "#1e2a37"), ("#d8e1ea", "#263546"), TEXT),
        }[kind]
        return ctk.CTkButton(parent, text=rtl(text), command=command, font=font(13, "bold"),
                             fg_color=colors[0], hover_color=colors[1], text_color=colors[2],
                             corner_radius=10, height=kw.pop("height", 36), **kw)

    def form_row(self, parent, key, path, width=160):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=4)
        self.label(row, t(key), width=280).pack(side=self.S)
        e = ctk.CTkEntry(row, width=width, font=font(13), justify="center", fg_color=FIELD,
                         border_color=BORDER, corner_radius=8)
        e.insert(0, str(self._get(path)))
        e.pack(side=self.S, padx=8)
        self.fields[path] = e
        return e

    def switch_row(self, parent, key, path):
        v = tk.BooleanVar(value=bool(self._get(path)))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=6)
        ctk.CTkSwitch(row, text="", variable=v, width=46, progress_color=ACCENT).pack(side=self.S)
        self.label(row, t(key)).pack(side=self.S, padx=6)
        self.fields[path] = v

    def segmented(self, parent, values, current, command=None):
        """زر مجزأ يحترم اتجاه اللغة. values: [(المعرّف، النص)]."""
        texts = [v[1] for v in values]
        lookup = {v[1]: v[0] for v in values}
        var = tk.StringVar(value=next(v[1] for v in values if v[0] == current))
        seg = ctk.CTkSegmentedButton(parent, values=texts[::-1] if i18n.is_rtl() else texts,
                                     variable=var, font=font(13, "bold"),
                                     selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                     command=(lambda _v: command(lookup[var.get()])) if command else None)
        seg.get_id = lambda: lookup[var.get()]
        return seg

    # ================= البناء =================
    def build(self):
        self.fields = {}
        self.root = ctk.CTkFrame(self, fg_color="transparent")
        self.root.pack(fill="both", expand=True)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(side=self.S, fill="both", expand=True, padx=18, pady=16)
        self.pages = {}
        for name, builder in (("dashboard", self._page_dashboard), ("home", self._page_home),
                              ("builder", self._page_builder), ("stats", self._page_stats),
                              ("calib", self._page_calib), ("settings", self._page_settings),
                              ("logs", self._page_logs)):
            frame = ctk.CTkFrame(self.content, fg_color="transparent")
            builder(frame)
            self.pages[name] = frame
        self.show(self.page)
        self._render_logs()
        self._render_license()

    # ================= التفعيل =================
    def license_gate(self):
        """يخفي النافذة حتى يُفعَّل البرنامج. أثناء التطوير بلا license_server.json يعمل بدون تفعيل."""
        server = lic.server_config(BASE)
        if server is None:
            if getattr(sys, "frozen", False):
                self.withdraw()
                messagebox.showerror(t("error"), t("lic_err_unconfigured"))
                self.destroy()
            return
        self.lic_client = lic.LicenseClient(server, VERSION)
        self.show_activation(auto=True)

    def show_activation(self, message="", auto=False):
        if self.lic_client is None or (self._lic_dialog is not None and self._lic_dialog.winfo_exists()):
            return
        if not (self.license and self.license.ok):
            self.withdraw()
        self._lic_dialog = ActivationDialog(self, self.lic_client, self._licensed, message, auto)

    def _licensed(self, res):
        self.license = res
        self._lic_fails = 0
        self._render_license()
        self.deiconify()
        self.log(t("lic_ok", date=res.expires_local()))
        self._schedule_recheck()

    def _schedule_recheck(self):
        if self._lic_job:
            self.after_cancel(self._lic_job)
        self._lic_job = self.after(LICENSE_RECHECK_MS, self._recheck_license)

    def _recheck_license(self):
        self._lic_job = None
        key = self.lic_client.saved_key()

        def work():
            res = self.lic_client.check(key)
            self.ui_q.put(lambda: self._recheck_done(res))
        threading.Thread(target=work, daemon=True).start()

    def _recheck_done(self, res):
        if res.ok:
            self.license, self._lic_fails = res, 0
        else:
            self._lic_fails += 1
            if res.final or self._lic_fails >= LICENSE_MAX_NET_FAILS:
                msg = t("lic_err_" + (res.error or "invalid"))
                self.license = None
                if self.farmer_thread is not None:
                    self.stop()
                    self.log(t("log_lic_lost", e=msg))
                self._render_license()
                self.show_activation(msg)
                return
        self._render_license()
        self._schedule_recheck()

    def _render_license(self):
        if not hasattr(self, "sb_license"):
            return
        r = self.license
        if self.lic_client is None or r is None:
            self.sb_license.configure(text="")
            return
        days = r.days_left()
        text = t("lic_left", d=int(days)) if days >= 1 else t("lic_left_hours", h=max(1, int(days * 24)))
        self.sb_license.configure(text=rtl(text), text_color=OK if days >= 3 else WARN, cursor="hand2")

    def rebuild(self):
        self._collect()
        self.root.destroy()
        self.build()
        self.title(f"{t('app_title')}  {VERSION}" + (f"  —  {PROFILE}" if PROFILE else ""))

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self.root, fg_color=SIDEBAR, corner_radius=0, width=240,
                          border_width=0)
        sb.pack(side=self.S, fill="y")
        sb.pack_propagate(False)
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(20, 18))
        logo = os.path.join(RES, "assets", "logo.png")
        if os.path.isfile(logo):
            self.logo_img = ctk.CTkImage(Image.open(logo), size=(46, 46))
            ctk.CTkLabel(head, image=self.logo_img, text="").pack(side=self.S)
        names = ctk.CTkFrame(head, fg_color="transparent")
        names.pack(side=self.S, padx=10)
        self.label(names, t("app_title"), 18, "bold").pack(fill="x")
        self.label(names, t("app_sub"), 11, color=MUTED).pack(fill="x")

        self.nav = {}
        for key, icon in (("dashboard", "▦"), ("home", "⚔"), ("builder", "☾"), ("stats", "▤"),
                          ("calib", "◎"), ("settings", "⚙"), ("logs", "☰")):
            text = f"{t('nav_' + key)}   {icon}" if i18n.is_rtl() else f"{icon}   {t('nav_' + key)}"
            b = ctk.CTkButton(sb, text=rtl(text), anchor=self.A, font=font(14, "bold"), height=42,
                              corner_radius=10, fg_color="transparent", text_color=TEXT,
                              hover_color=("#e7edf3", "#1b2733"), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=3)
            self.nav[key] = b

        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=16)
        self.label(bottom, t("language"), 11, color=MUTED).pack(fill="x")
        lang = self.segmented(bottom, [("ar", "العربية"), ("en", "English")], i18n.LANG["code"],
                              command=self.set_language)
        lang.pack(fill="x", pady=(4, 12))
        st = ctk.CTkFrame(bottom, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER)
        st.pack(fill="x")
        self.label(st, t("emulator"), 11, color=MUTED).pack(fill="x", padx=12, pady=(8, 0))
        self.sb_status = self.label(st, "", 13, "bold")
        self.sb_status.pack(fill="x", padx=12, pady=(0, 8))
        self.sb_license = self.label(bottom, "", 11, "bold", color=MUTED)
        self.sb_license.pack(fill="x", pady=(10, 0))
        self.sb_license.bind("<Button-1>", lambda e: self.show_activation())
        self.label(bottom, f"{t('version')} {VERSION}", 10, color=MUTED).pack(fill="x", pady=(4, 0))

    def show(self, name):
        self.page = name
        for k, f in self.pages.items():
            f.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for k, b in self.nav.items():
            active = k == name
            b.configure(fg_color=ACCENT if active else "transparent",
                        text_color="#ffffff" if active else TEXT)

    def page_header(self, parent, key, sub=None):
        h = ctk.CTkFrame(parent, fg_color="transparent")
        h.pack(fill="x", pady=(0, 12))
        self.label(h, t(key), 24, "bold").pack(fill="x")
        if sub:
            self.label(h, sub, 12, color=MUTED, wraplength=820).pack(fill="x")
        return h

    # ================= لوحة التحكم =================
    def _page_dashboard(self, p):
        self.page_header(p, "nav_dashboard")
        self.stat_labels = {}
        for keys in (("state", "stat_attacks", "stat_skipped", "stat_uptime"),
                     ("stat_gold", "stat_elixir", "stat_dark", "stat_bb_gold")):
            stats = ctk.CTkFrame(p, fg_color="transparent")
            stats.pack(fill="x", pady=(0, 10))
            for key in keys:
                c = self.card(stats)
                c.pack(side=self.S, fill="x", expand=True, padx=(0, 10))
                self.label(c, t(key), 12, color=MUTED).pack(fill="x", padx=16, pady=(12, 0))
                color = {"stat_gold": "#e8b923", "stat_elixir": "#c64fe0", "stat_dark": ("#3b3f4a", "#a9b1bd"),
                         "stat_bb_gold": "#e0a030"}.get(key, TEXT)
                v = self.label(c, "—", 22, "bold", color=color)
                v.pack(fill="x", padx=16, pady=(0, 12))
                self.stat_labels[key] = v

        ctl = self.card(p)
        ctl.pack(fill="x", pady=12)
        row = ctk.CTkFrame(ctl, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=14)
        self.label(row, t("mode"), 13, "bold").pack(side=self.S, padx=(0, 8))
        self.mode_seg = self.segmented(row, [("home", t("nav_home")), ("builder", t("nav_builder"))],
                                       self.cfg.get("mode", "home"))
        self.mode_seg.pack(side=self.S, padx=8)
        self.btn_stop = self.button(row, f"■  {t('stop')}", self.stop, "danger", width=130, height=44)
        self.btn_stop.pack(side=self.E, padx=4)
        self.btn_start = self.button(row, f"▶  {t('start')}", self.start, "success", width=150, height=44)
        self.btn_start.pack(side=self.E, padx=4)
        self.button(row, t("launch_game"), self.launch_game, "ghost", width=120).pack(side=self.E, padx=4)
        self.button(row, t("connect"), self.connect, "primary", width=150).pack(side=self.E, padx=4)

        recent = self.card(p, t("recent_log"))
        recent.pack(fill="both", expand=True)
        self.recent_box = self._log_box(recent)
        self.recent_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _log_box(self, parent):
        box = ctk.CTkTextbox(parent, font=font(12), wrap="word", fg_color=FIELD, corner_radius=10,
                             border_width=0)
        box.tag_config("line", justify="right" if i18n.is_rtl() else "left")
        box.configure(state="disabled")
        return box

    # ================= القرية الرئيسية =================
    def option_row(self, parent, key, path, options, width=220):
        """قائمة منسدلة تحفظ المعرّف (لا النص المترجم) في الإعدادات."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=4)
        self.label(row, t(key), width=200).pack(side=self.S)
        texts = {oid: t(tk_) for oid, tk_ in options}
        rev = {v: k for k, v in texts.items()}
        menu = ctk.CTkOptionMenu(row, values=list(texts.values()), width=width, font=font(13),
                                 fg_color=ACCENT, button_color=ACCENT_HOVER, dropdown_font=font(13))
        menu.set(texts.get(self._get(path), list(texts.values())[0]))
        menu.pack(side=self.S, padx=8)

        class Field:  # get() يرجع المعرّف
            def get(self_inner):
                return rev.get(menu.get(), options[0][0])
        self.fields[path] = Field()
        return menu

    def _page_home(self, p):
        self.page_header(p, "nav_home")
        body = ctk.CTkScrollableFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        strat = self.card(top, t("strategy"))
        strat.pack(side=self.S, fill="both", expand=True, padx=(0, 6) if not i18n.is_rtl() else (6, 0))
        self.option_row(strat, "strategy", "attack.strategy",
                        [(k, "strat_" + k) for k in ("custom", "edrag", "dragons", "goblins")])
        self.option_row(strat, "method", "attack.method",
                        [(k, "method_" + k) for k in ("auto", "one_side", "two_sides", "three_sides", "all_sides")])
        self.option_row(strat, "side", "attack.side",
                        [(k, "side_" + k) for k in ("auto", "rotate", "top_left", "top_right",
                                                     "bottom_right", "bottom_left")])
        self.switch_row(strat, "zoom_out", "farm.zoom_out")
        ctk.CTkFrame(strat, height=8, fg_color="transparent").pack()
        area = self.card(top, t("area"))
        area.pack(side=self.S, fill="both", expand=True)
        self.label(area, t("area_hint"), 12, color=MUTED, wraplength=380).pack(fill="x", padx=18)
        self.area_lbl = self.label(area, "", 12, "bold")
        self.area_lbl.pack(fill="x", padx=18, pady=8)
        self.button(area, t("area_btn"), self._pick_area, "primary", width=200).pack(anchor=self.A, padx=18, pady=(0, 14))
        self._render_area()

        scan = self.card(body, t("army_scan"))
        scan.pack(fill="x", pady=(0, 12))
        self.label(scan, t("scan_hint"), 12, color=MUTED, wraplength=820).pack(fill="x", padx=18)
        self.button(scan, t("scan_btn"), self._scan_army, "primary", width=180).pack(anchor=self.A, padx=18, pady=8)
        self.scan_frame = ctk.CTkFrame(scan, fg_color="transparent")
        self.scan_frame.pack(fill="x", padx=12, pady=(0, 12))
        self._render_scan()

        army = self.card(body, t("army"))
        army.pack(fill="x", pady=(0, 12))
        self.label(army, t("army_hint"), 12, color=MUTED, wraplength=800).pack(fill="x", padx=18)
        self.army_frame = ctk.CTkFrame(army, fg_color="transparent")
        self.army_frame.pack(fill="x", padx=12, pady=8)
        bar = ctk.CTkFrame(army, fg_color="transparent")
        bar.pack(fill="x", padx=18, pady=(0, 14))
        self.button(bar, t("add_slot"), self._add_slot, "ghost", width=140).pack(side=self.S)
        self.line_lbl = self.label(bar, "", 12, color=MUTED)
        self.button(bar, t("pick_line"), self._pick_deploy_line, "primary", width=150).pack(side=self.E)
        self.line_lbl.pack(side=self.E, padx=10)
        self._render_army()

        two = ctk.CTkFrame(body, fg_color="transparent")
        two.pack(fill="x")
        battle = self.card(two, t("battle"))
        battle.pack(side=self.S, fill="both", expand=True, padx=(0, 6) if not i18n.is_rtl() else (6, 0))
        self.form_row(battle, "battle_seconds", "farm.battle_seconds", 110)
        self.form_row(battle, "max_skips", "farm.max_skips", 110)
        self.form_row(battle, "ability_after", "farm.ability_after", 110)
        ctk.CTkFrame(battle, height=10, fg_color="transparent").pack()
        loot = self.card(two, t("loot_filter"))
        loot.pack(side=self.S, fill="both", expand=True)
        self.switch_row(loot, "loot_enable", "loot.enabled")
        self.form_row(loot, "min_gold", "loot.min_gold", 110)
        self.form_row(loot, "min_elixir", "loot.min_elixir", 110)
        self.form_row(loot, "min_dark", "loot.min_dark", 110)
        ctk.CTkFrame(loot, height=10, fg_color="transparent").pack()
        self.button(body, t("save"), self._save, "success", width=160).pack(anchor=self.A, pady=12)

    def _render_army(self):
        for w in self.army_frame.winfo_children():
            w.destroy()
        self.army_rows = []
        hdr = ctk.CTkFrame(self.army_frame, fg_color="transparent")
        hdr.pack(fill="x")
        for key, w in (("col_on", 50), ("col_name", 200), ("col_qty", 70), ("col_type", 120),
                       ("col_pos", 150), ("", 40)):
            ctk.CTkLabel(hdr, text=rtl(t(key)) if key else "", font=font(12, "bold"),
                         text_color=MUTED, width=w).pack(side=self.S, padx=3)
        types = [("troop", t("type_troop")), ("hero", t("type_hero")), ("spell", t("type_spell"))]
        for i, slot in enumerate(self.cfg["army"]):
            row = ctk.CTkFrame(self.army_frame, fg_color=FIELD, corner_radius=10)
            row.pack(fill="x", pady=3)
            en = tk.BooleanVar(value=slot.get("enabled", True))
            ctk.CTkCheckBox(row, text="", variable=en, width=50, fg_color=ACCENT,
                            checkbox_width=22, checkbox_height=22).pack(side=self.S, padx=(14, 3), pady=6)
            name = ctk.CTkEntry(row, width=200, font=font(13), justify="right" if i18n.is_rtl() else "left",
                                border_color=BORDER)
            name.insert(0, slot["label"])
            name.pack(side=self.S, padx=3)
            qty = ctk.CTkEntry(row, width=70, font=font(13), justify="center", border_color=BORDER)
            qty.insert(0, str(slot["quantity"]))
            qty.pack(side=self.S, padx=3)
            kind = ctk.CTkOptionMenu(row, values=[x[1] for x in types], width=120, font=font(12),
                                     fg_color=ACCENT, button_color=ACCENT_HOVER)
            kind.set(dict(types)[slot_type(slot)])
            kind.pack(side=self.S, padx=3)
            self.button(row, f"{t('pick')}  {pt((slot['x'], slot['y']))}", lambda i=i: self._pick_slot(i),
                        "ghost", width=150, height=30).pack(side=self.S, padx=3)
            self.button(row, "✕", lambda i=i: self._del_slot(i), "danger", width=40, height=30
                        ).pack(side=self.S, padx=3)
            self.army_rows.append((en, name, qty, kind, {v: k for k, v in types}))
        line = self.cfg["deploy_line"]
        if hasattr(self, "line_lbl"):
            arrow = "←" if i18n.is_rtl() else "→"
            self.line_lbl.configure(text=rtl(f"{t('deploy_line')}: {pt(line[0])} {arrow} {pt(line[1])}"))

    def _collect_army(self):
        if not getattr(self, "army_rows", None):
            return
        for slot, (en, name, qty, kind, rev) in zip(self.cfg["army"], self.army_rows):
            try:
                slot["enabled"] = en.get()
                slot["label"] = name.get().strip() or t("new_slot")
                slot["quantity"] = max(1, int(qty.get()))
                slot["type"] = rev.get(kind.get(), "troop")
            except (ValueError, tk.TclError):
                pass

    def _add_slot(self):
        self._collect_army()
        self.cfg["army"].append({"label": t("new_slot"), "quantity": 1, "x": 800, "y": 815,
                                 "type": "troop", "enabled": True})
        self._render_army()

    def _del_slot(self, i):
        self._collect_army()
        del self.cfg["army"][i]
        self._render_army()

    def _with_screen(self, callback):
        if not self._need_adb():
            return

        def work():
            img = self.adb.screenshot()
            # النتيجة تُنفَّذ في الخيط الرئيسي عبر _tick (Tkinter لا يقبل الاستدعاء من خيط آخر)
            self.ui_q.put(lambda: callback(img) if img is not None else
                          messagebox.showerror(t("error"), t("shot_failed")))
        threading.Thread(target=work, daemon=True).start()

    def _pick_slot(self, i):
        self._collect_army()

        def done(p):
            self.cfg["army"][i].update(x=p[0], y=p[1])
            self._render_army()
        self._with_screen(lambda img: ScreenPicker(self, img, done, "point"))

    def _pick_deploy_line(self):
        self._collect_army()
        messagebox.showinfo(t("deploy_line"), t("pick_line_hint"))

        def done(p1, p2):
            self.cfg["deploy_line"] = [list(p1), list(p2)]
            self._render_army()
            self.log(t("log_line", line=self.cfg["deploy_line"]))
        self._with_screen(lambda img: ScreenPicker(self, img, done, "line"))

    # ---------- منطقة الإنزال ----------
    def _render_area(self):
        a = self.cfg["attack"]["area"]
        names = ("left", "top", "right", "bottom")
        self.area_lbl.configure(text=rtl("   ".join(f"{t('corner_' + n)} {pt(a[n])}" for n in names)))

    def _pick_area(self):
        messagebox.showinfo(t("area"), t("area_hint"))
        names = ("left", "top", "right", "bottom")

        def done(points):
            self.cfg["attack"]["area"] = {n: list(p) for n, p in zip(names, points)}
            self._render_area()
            cfgmod.save(CONFIG_PATH, self.cfg)
            self.log(t("log_area"))
        self._with_screen(lambda img: ScreenPicker(self, img, done, "points",
                                                   steps=[t("corner_" + n) for n in names]))

    # ---------- مسح الجيش ----------
    def _scan_army(self):
        def done(img):
            book = ArmyBook(self.templates.folder, self.cfg["attack"].get("army_dir", "army"))
            slots = book.scan(img)
            if not slots:
                messagebox.showwarning(t("warning"), t("scan_none"))
                return
            self.cfg["attack"]["slots"] = slots
            cfgmod.save(CONFIG_PATH, self.cfg)
            self._render_scan()
            self.log(t("scan_done", n=len(slots)))
        self._with_screen(done)

    def _render_scan(self):
        for w in self.scan_frame.winfo_children():
            w.destroy()
        self.scan_rows = []
        self.scan_imgs = []
        slots = self.cfg["attack"].get("slots", [])
        if not slots:
            return
        book = ArmyBook(self.templates.folder, self.cfg["attack"].get("army_dir", "army"))
        types = [("troop", t("type_troop")), ("siege", t("type_siege")), ("hero", t("type_hero")),
                 ("spell", t("type_spell"))]
        spells = [(k, t("spell_" + k)) for k in ("rage", "haste", "freeze", "heal", "other")]
        grid = ctk.CTkFrame(self.scan_frame, fg_color="transparent")
        grid.pack(fill="x")
        per_row = 4
        for i, s in enumerate(slots):
            cell = ctk.CTkFrame(grid, fg_color=FIELD, corner_radius=10)
            col = i % per_row if not i18n.is_rtl() else per_row - 1 - i % per_row
            cell.grid(row=i // per_row, column=col, padx=4, pady=4, sticky="nsew")
            grid.grid_columnconfigure(col, weight=1)
            head = ctk.CTkFrame(cell, fg_color="transparent")
            head.pack(fill="x", padx=8, pady=(8, 2))
            img = book.get(s["id"])
            if img is not None:
                pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                ci = ctk.CTkImage(pil, size=(44, 44))
                self.scan_imgs.append(ci)
                ctk.CTkLabel(head, image=ci, text="").pack(side=self.S)
            en = tk.BooleanVar(value=s.get("enabled", True))
            ctk.CTkCheckBox(head, text="", variable=en, width=24, fg_color=ACCENT).pack(side=self.E)
            name = ctk.CTkEntry(head, width=110, font=font(12), placeholder_text=s["id"],
                                justify="right" if i18n.is_rtl() else "left", border_color=BORDER)
            if s.get("label"):
                name.insert(0, s["label"])
            name.pack(side=self.S, padx=6)
            kind = ctk.CTkOptionMenu(cell, values=[x[1] for x in types], width=150, font=font(12),
                                     fg_color=ACCENT, button_color=ACCENT_HOVER)
            kind.set(dict(types).get(s.get("type", "troop")))
            kind.pack(padx=8, pady=2)
            sp = ctk.CTkOptionMenu(cell, values=[x[1] for x in spells], width=150, font=font(12),
                                   fg_color=("#7c4dbe", "#6a3fae"), button_color=("#6a3fae", "#57338f"))
            sp.set(dict(spells).get(s.get("spell", "rage")))
            sp.pack(padx=8, pady=(2, 8))
            self.scan_rows.append((s, en, name, kind, sp, {v: k for k, v in types}, {v: k for k, v in spells}))

    def _collect_scan(self):
        for s, en, name, kind, sp, rt, rs in getattr(self, "scan_rows", []):
            try:
                s["enabled"] = en.get()
                s["label"] = name.get().strip()
                s["type"] = rt.get(kind.get(), "troop")
                s["spell"] = rs.get(sp.get(), "rage")
            except tk.TclError:
                pass

    # ================= الإحصائيات =================
    def _page_stats(self, p):
        h = self.page_header(p, "nav_stats")
        self.button(h, t("stat_reset"), self._reset_stats, "ghost", width=100).pack(anchor=self.A, pady=(6, 0))
        self.stats_cards = ctk.CTkFrame(p, fg_color="transparent")
        self.stats_cards.pack(fill="x")
        table = self.card(p, t("stat_recent"))
        table.pack(fill="both", expand=True, pady=(12, 0))
        self.stats_box = self._log_box(table)
        self.stats_box.configure(font=("Consolas", 13))
        self.stats_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._render_stats()

    def _render_stats(self):
        if not hasattr(self, "stats_cards"):
            return
        for w in self.stats_cards.winfo_children():
            w.destroy()
        tot = self.stats_db["totals"]
        hist = self.stats_db["history"]
        hours = max(1 / 60, (hist[-1]["time"] - hist[0]["time"]) / 3600) if len(hist) > 1 else None
        for key, k, color in (("stat_attacks", "attacks", TEXT), ("stat_gold", "gold", "#e8b923"),
                              ("stat_elixir", "elixir", "#c64fe0"), ("stat_dark", "dark", ("#3b3f4a", "#a9b1bd")),
                              ("stat_bb_gold", "bb_gold", "#e0a030")):
            c = self.card(self.stats_cards)
            c.pack(side=self.S, fill="x", expand=True, padx=(0, 10))
            self.label(c, f"{t(key)} — {t('stat_total')}", 11, color=MUTED).pack(fill="x", padx=14, pady=(12, 0))
            self.label(c, f"{int(tot.get(k, 0)):,}", 20, "bold", color=color).pack(fill="x", padx=14)
            per = f"{int(tot.get(k, 0) / hours):,} {t('stat_per_hour')}" if hours else "—"
            self.label(c, per, 11, color=MUTED).pack(fill="x", padx=14, pady=(0, 12))
        box = self.stats_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        head = f"{t('col_time'):<10}{t('col_village'):<16}{t('stat_gold'):>12}{t('stat_elixir'):>12}{t('stat_dark'):>9}"
        box.insert("end", head + "\n" + "─" * 60 + "\n")
        for h in reversed(hist[-100:]):
            village = t("nav_builder") if h.get("village") == "builder" else t("nav_home")
            gold = h.get("gold", h.get("bb_gold", 0)) or 0
            box.insert("end", f"{time.strftime('%H:%M', time.localtime(h['time'])):<10}{village:<16}"
                              f"{gold:>12,}{h.get('elixir', 0) or 0:>12,}{h.get('dark', 0) or 0:>9,}\n")
        box.configure(state="disabled")

    def _reset_stats(self):
        self.stats_db = {"totals": {"attacks": 0, "gold": 0, "elixir": 0, "dark": 0, "bb_gold": 0}, "history": []}
        try:
            with open(STATS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.stats_db, f)
        except OSError:
            pass
        self._render_stats()

    # ================= القرية الليلية =================
    def _page_builder(self, p):
        self.page_header(p, "nav_builder", t("bb_hint"))
        body = ctk.CTkScrollableFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        two = ctk.CTkFrame(body, fg_color="transparent")
        two.pack(fill="x")
        army = self.card(two, t("bb_army"))
        army.pack(side=self.S, fill="both", expand=True, padx=(0, 6) if not i18n.is_rtl() else (6, 0))
        self.form_row(army, "troop_slots", "builder.troop_slots", 90)
        self.form_row(army, "reinf_slots", "builder.reinforcement_slots", 90)
        self.switch_row(army, "use_hero", "builder.use_hero")
        self.form_row(army, "ability_after", "builder.ability_after", 90)
        self.form_row(army, "stage_seconds", "builder.stage_seconds", 90)
        ctk.CTkFrame(army, height=10, fg_color="transparent").pack()
        pts = self.card(two, t("deploy_points"))
        pts.pack(side=self.S, fill="both", expand=True)
        self.point_lbls = {}
        for key in ("stage1_point", "stage2_point"):
            row = ctk.CTkFrame(pts, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=8)
            self.label(row, t(key), width=150).pack(side=self.S)
            lbl = self.label(row, pt(self.cfg["builder"][key]), 13, "bold", width=110)
            lbl.pack(side=self.S, padx=8)
            self.button(row, t("pick"), lambda k=key: self._pick_bb_point(k), "primary",
                        width=90, height=30).pack(side=self.S, padx=8)
            self.point_lbls[key] = lbl
        self.button(body, t("save"), self._save, "success", width=160).pack(anchor=self.A, pady=12)

    def _pick_bb_point(self, key):
        def done(p):
            self.cfg["builder"][key] = list(p)
            self.point_lbls[key].configure(text=rtl(pt(p)))
            self.log(t("log_point", name=t(key), pt=pt(p)))
        self._with_screen(lambda img: ScreenPicker(self, img, done, "point"))

    # ================= المعايرة =================
    def _page_calib(self, p):
        self.page_header(p, "nav_calib", t("calib_hint"))
        body = ctk.CTkScrollableFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        self.calib_rows = {}
        for group, keys in BUTTON_GROUPS.items():
            c = self.card(body, t(group))
            c.pack(fill="x", pady=(0, 12))
            for key in keys:
                row = ctk.CTkFrame(c, fg_color=FIELD, corner_radius=10)
                row.pack(fill="x", padx=14, pady=3)
                thumb = ctk.CTkLabel(row, text="", width=120, height=44, fg_color=CARD, corner_radius=8)
                thumb.pack(side=self.S, padx=8, pady=6)
                self.label(row, btn_name(key), 13, "bold", width=230).pack(side=self.S, padx=6)
                info = self.label(row, "", 12, color=MUTED, width=230)
                info.pack(side=self.S, padx=6)
                self.button(row, t("capture"), lambda k=key: self._capture(k), "primary",
                            width=90, height=30).pack(side=self.E, padx=8)
                self.button(row, t("delete"), lambda k=key: self._del_template(k), "ghost",
                            width=80, height=30).pack(side=self.E, padx=2)
                self.calib_rows[key] = (thumb, info)
            ctk.CTkFrame(c, height=8, fg_color="transparent").pack()
        self._refresh_calib()

    def _refresh_calib(self):
        self.thumbs = {}
        for key, (thumb, info) in self.calib_rows.items():
            tpl = self.templates.get(key)
            if tpl is not None:
                img = Image.fromarray(cv2.cvtColor(tpl, cv2.COLOR_BGR2RGB))
                img.thumbnail((112, 40))
                self.thumbs[key] = ctk.CTkImage(img, size=img.size)
                thumb.configure(image=self.thumbs[key], text="")
            else:
                thumb.configure(image="", text="—")
            c = self.cfg["buttons"].get(key)
            pos = pt((c["x"], c["y"])) if c else "—"
            state = "✓ " + t("has_template") if tpl is not None else "○ " + t("no_template")
            info.configure(text=rtl(f"{state}   {pos}"),
                           text_color=OK if tpl is not None else MUTED)

    def _capture(self, key):
        def done(p, crop):
            self.cfg["buttons"][key] = {"x": p[0], "y": p[1]}
            if crop is not None:
                self.templates.save(key, crop)
            cfgmod.save(CONFIG_PATH, self.cfg)
            self._refresh_calib()
            self.log(t("log_saved_btn", name=btn_name(key)))
        self._with_screen(lambda img: ScreenPicker(self, img, done, "region"))

    def _del_template(self, key):
        p = self.templates.path(key)
        if os.path.isfile(p):
            os.remove(p)
            self.templates._cache.pop(key, None)
        self._refresh_calib()

    # ================= الإعدادات =================
    def _page_settings(self, p):
        self.page_header(p, "nav_settings")
        body = ctk.CTkScrollableFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        two = ctk.CTkFrame(body, fg_color="transparent")
        two.pack(fill="x")
        left = ctk.CTkFrame(two, fg_color="transparent")
        left.pack(side=self.S, fill="both", expand=True, padx=(0, 6) if not i18n.is_rtl() else (6, 0))
        right = ctk.CTkFrame(two, fg_color="transparent")
        right.pack(side=self.S, fill="both", expand=True)

        conn = self.card(left, t("conn"))
        conn.pack(fill="x", pady=(0, 12))
        self.form_row(conn, "serial", "adb.serial", 170)
        self.form_row(conn, "adb_path", "adb.path", 170)
        self.button(conn, t("instances_btn"), self._show_instances, "ghost", width=200).pack(
            anchor=self.A, padx=18, pady=(4, 4))
        self.label(conn, t("profile_hint"), 11, color=MUTED, wraplength=420).pack(fill="x", padx=18, pady=(0, 10))
        gen = self.card(left, t("general"))
        gen.pack(fill="x", pady=(0, 12))
        self.form_row(gen, "max_attacks", "farm.max_attacks", 110)
        self.form_row(gen, "threshold", "farm.match_threshold", 110)
        row = ctk.CTkFrame(gen, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(6, 14))
        self.label(row, t("appearance"), width=280).pack(side=self.S)
        self.appearance_seg = self.segmented(row, [("dark", t("dark")), ("light", t("light"))],
                                             self.cfg.get("appearance", "dark"), command=self.set_appearance)
        self.appearance_seg.pack(side=self.S, padx=8)

        br = self.card(right, t("breaks"))
        br.pack(fill="x", pady=(0, 12))
        self.switch_row(br, "breaks_enable", "breaks.enabled")
        self.form_row(br, "break_after_min", "breaks.attacks_min", 90)
        self.form_row(br, "break_after_max", "breaks.attacks_max", 90)
        self.form_row(br, "break_min", "breaks.minutes_min", 90)
        self.form_row(br, "break_max", "breaks.minutes_max", 90)
        ctk.CTkFrame(br, height=10, fg_color="transparent").pack()
        col = self.card(right, t("collect"))
        col.pack(fill="x", pady=(0, 12))
        self.switch_row(col, "collect_resources", "collect.resources")
        self.switch_row(col, "collect_cart", "collect.elixir_cart")
        ctk.CTkFrame(col, height=8, fg_color="transparent").pack()
        cl = self.card(right, t("clan"))
        cl.pack(fill="x", pady=(0, 12))
        self.switch_row(cl, "clan_request", "clan.request")
        self.form_row(cl, "clan_request_every", "clan.request_every_min", 90)
        self.label(cl, t("clan_hint"), 11, color=MUTED).pack(fill="x", padx=18, pady=(0, 12))

        nt = self.card(body, t("notify"))
        nt.pack(fill="x", pady=(0, 12))
        self.switch_row(nt, "notify_enable", "notify.enabled")
        self.form_row(nt, "discord_webhook", "notify.discord_webhook", 460)
        self.form_row(nt, "telegram_token", "notify.telegram_token", 460)
        self.form_row(nt, "telegram_chat", "notify.telegram_chat", 200)
        self.form_row(nt, "notify_every", "notify.every", 90)
        self.button(nt, t("notify_test"), self._test_notify, "primary", width=150).pack(anchor=self.A, padx=18, pady=(4, 14))
        self.button(body, t("save_settings"), self._save, "success", width=180).pack(anchor=self.A, pady=12)

    def _show_instances(self):
        rows = ldplayer_instances()
        if not rows:
            messagebox.showinfo(t("instances_btn"), t("instances_none"))
            return
        text = "\n".join(f"#{i}  {name}  —  {serial}  {'● ' + t('state_running') if on else ''}"
                         for i, name, on, serial in rows)
        messagebox.showinfo(t("instances_btn"), text)

    def _test_notify(self):
        self._collect()

        def work():
            res = Notifier(self.cfg).send(t("notify_test_msg"), "test", wait=True)
            text = "\n".join(f"{n}: {'OK' if r in (200, 204) else r}" for n, r in res) or "—"
            self.ui_q.put(lambda: messagebox.showinfo(t("notify"), t("notify_result", r=text)))
        threading.Thread(target=work, daemon=True).start()

    # ================= السجل =================
    def _page_logs(self, p):
        h = self.page_header(p, "nav_logs")
        bar = ctk.CTkFrame(h, fg_color="transparent")
        bar.pack(fill="x", pady=(6, 0))
        self.button(bar, t("clear"), self._clear_logs, "ghost", width=90).pack(side=self.S)
        self.button(bar, t("logs_save"), self._save_logs, "primary", width=110).pack(side=self.S, padx=8)
        c = self.card(p)
        c.pack(fill="both", expand=True)
        self.full_box = self._log_box(c)
        self.full_box.pack(fill="both", expand=True, padx=12, pady=12)

    def _render_logs(self):
        for box, lines in ((self.full_box, self.log_lines), (self.recent_box, self.log_lines[-60:])):
            box.configure(state="normal")
            box.delete("1.0", "end")
            for line in lines:
                box.insert("end", rtl(line) + "\n", "line")
            box.see("end")
            box.configure(state="disabled")

    def _append_log(self, line):
        for box in (self.full_box, self.recent_box):
            box.configure(state="normal")
            box.insert("end", rtl(line) + "\n", "line")
            box.see("end")
            box.configure(state="disabled")

    def _clear_logs(self):
        self.log_lines.clear()
        self._render_logs()

    def _save_logs(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="skysimple_log.txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log_lines))

    # ================= التشغيل =================
    def log(self, msg):
        self.logq.put(f"{msg}   {time.strftime('%H:%M:%S')}" if i18n.is_rtl()
                      else f"{time.strftime('%H:%M:%S')}   {msg}")

    def _tick(self):
        try:
            while not self.ui_q.empty():
                self.ui_q.get()()
            while not self.logq.empty():
                line = self.logq.get()
                self.log_lines.append(line)
                if len(self.log_lines) > 2000:
                    del self.log_lines[:500]
                    self._render_logs()
                else:
                    self._append_log(line)
            self._update_status()
            self._sync_stats()
        finally:
            self.after(400, self._tick)

    def _update_status(self):
        running = self.farmer_thread is not None and self.farmer_thread.is_alive()
        if self.farmer_thread is not None and not running:
            self.farmer_thread = None
        stopping = running and self.farmer.stop_event.is_set()
        state, color = ((t("state_stopping"), WARN) if stopping else
                        (t("state_running"), OK) if running else (t("state_idle"), MUTED))
        self.stat_labels["state"].configure(text=rtl(state), text_color=color)
        s = self.farmer.stats if self.farmer else {"attacks": 0, "skipped": 0, "started": None}
        self.stat_labels["stat_attacks"].configure(text=str(s["attacks"]))
        self.stat_labels["stat_skipped"].configure(text=str(s["skipped"]))
        if running and s["started"]:
            secs = int(time.time() - s["started"])
            self.stat_labels["stat_uptime"].configure(text=f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}")
        elif not self.farmer:
            self.stat_labels["stat_uptime"].configure(text="00:00:00")
        can_stop = running and not stopping
        self.btn_start.configure(state="disabled" if running else "normal",
                                 fg_color=("#9aa5b1", "#2a3644") if running else OK)
        self.btn_stop.configure(state="normal" if can_stop else "disabled",
                                fg_color=DANGER if can_stop else ("#9aa5b1", "#2a3644"))
        if self.connected:
            res = "  " + ltr(f"{self.resolution[0]}×{self.resolution[1]}") if self.resolution else ""
            self.sb_status.configure(text=rtl("● " + t("connected") + res), text_color=OK)
        else:
            self.sb_status.configure(text=rtl("● " + t("disconnected")), text_color=DANGER)

    # ================= الإحصائيات الدائمة =================
    def _load_stats_db(self):
        try:
            with open(STATS_PATH, encoding="utf-8") as f:
                db = json.load(f)
        except (OSError, ValueError):
            db = {}
        db.setdefault("totals", {"attacks": 0, "gold": 0, "elixir": 0, "dark": 0, "bb_gold": 0})
        db.setdefault("history", [])
        return db

    def _sync_stats(self):
        """ينقل الهجمات الجديدة من البوت إلى stats.json ويحدّث البطاقات."""
        s = self.farmer.stats if self.farmer else {}
        hist = s.get("history", [])
        new = hist[self._stats_seen:] if self.farmer else []
        if new:
            self._stats_seen = len(hist)
            for h in new:
                self.stats_db["totals"]["attacks"] += 1
                for k in ("gold", "elixir", "dark", "bb_gold"):
                    self.stats_db["totals"][k] += int(h.get(k, 0) or 0)
                self.stats_db["history"].append(h)
            del self.stats_db["history"][:-500]
            try:
                with open(STATS_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.stats_db, f)
            except OSError:
                pass
            self._render_stats()
        for key, k in (("stat_gold", "gold"), ("stat_elixir", "elixir"), ("stat_dark", "dark"),
                       ("stat_bb_gold", "bb_gold")):
            self.stat_labels[key].configure(text=f"{int(s.get(k, 0) or 0):,}")

    def connect(self):
        path = find_adb(self.cfg["adb"]["path"])
        if not path:
            messagebox.showerror("ADB", t("adb_missing"))
            return
        self._collect()
        self.adb = ADB(path, self.cfg["adb"]["serial"])

        def work():
            ok, text = self.adb.connect()
            img = self.adb.screenshot() if ok else None
            if ok and img is not None:
                h, w = img.shape[:2]
                self.connected, self.resolution = True, (w, h)
                self.log(t("log_connected", serial=ltr(self.adb.serial), res=ltr(f"{w}×{h}")))
                if (w, h) != (1600, 900):
                    self.log(t("log_res_warn"))
            else:
                self.connected = False
                self.log(t("log_conn_fail", msg=text or "—"))
        threading.Thread(target=work, daemon=True).start()

    def launch_game(self):
        if self._need_adb():
            threading.Thread(target=lambda: self.adb.start_app(self.cfg["package"]), daemon=True).start()

    def _need_adb(self):
        if self.adb is None or not self.connected:
            messagebox.showwarning(t("warning"), t("need_connect"))
            return False
        return True

    def start(self):
        if self.lic_client is not None and not (self.license and self.license.ok):
            self.show_activation()
            return
        if not self._need_adb() or self.farmer_thread is not None:
            return
        self._collect()
        cfgmod.save(CONFIG_PATH, self.cfg)
        cls = BuilderFarmer if self.cfg["mode"] == "builder" else Farmer
        mode = t("nav_builder") if self.cfg["mode"] == "builder" else t("nav_home")
        self.log(t("log_started", mode=mode))
        self.farmer = cls(self.adb, self.cfg, self.templates, self.log)
        self._stats_seen = 0
        self.farmer_thread = threading.Thread(target=self.farmer.run, daemon=True)
        self.farmer_thread.start()

    def stop(self):
        if self.farmer:
            self.farmer.stop_event.set()

    # ================= الإعدادات: قراءة / كتابة =================
    def _get(self, path):
        node = self.cfg
        for part in path.split("."):
            node = node[part]
        return node

    def _set(self, path, value):
        parts = path.split(".")
        node = self.cfg
        for part in parts[:-1]:
            node = node[part]
        old = node[parts[-1]]
        try:
            if isinstance(old, bool):
                node[parts[-1]] = bool(value)
            elif isinstance(old, int):
                node[parts[-1]] = int(float(value))
            elif isinstance(old, float):
                node[parts[-1]] = float(value)
            else:
                node[parts[-1]] = str(value).strip()
        except ValueError:
            pass  # قيمة غير صالحة: نُبقي القديمة

    def _collect(self):
        for path, w in self.fields.items():
            try:
                self._set(path, w.get())
            except tk.TclError:
                pass
        if hasattr(self, "mode_seg"):
            self.cfg["mode"] = self.mode_seg.get_id()
        self._collect_army()
        self._collect_scan()

    def _save(self):
        self._collect()
        cfgmod.save(CONFIG_PATH, self.cfg)
        self.log(t("saved"))

    def set_language(self, code):
        if code == i18n.LANG["code"]:
            return
        self._collect()
        self.cfg["lang"] = code
        i18n.set_lang(code)
        cfgmod.save(CONFIG_PATH, self.cfg)
        self.rebuild()

    def set_appearance(self, mode):
        self.cfg["appearance"] = mode
        ctk.set_appearance_mode(mode)

    def _close(self):
        self.stop()
        try:
            self._collect()
            cfgmod.save(CONFIG_PATH, self.cfg)
        finally:
            self.destroy()


def selftest(app):
    """فحص ذاتي للنسخة المجمّعة: يتصل بالمحاكي ويكتب النتيجة في selftest.txt ثم يغلق."""
    def finish():
        lines = [f"connected={app.connected}", f"resolution={app.resolution}",
                 f"templates={sum(app.templates.exists(k) for k in i18n.BUTTON_NAMES)}",
                 f"assets={os.path.isfile(os.path.join(RES, 'assets', 'logo.png'))}"] + app.log_lines
        with open(os.path.join(BASE, "selftest.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        app.destroy()
    app.after(1500, app.connect)
    app.after(12000, finish)


if __name__ == "__main__":
    main = App()
    if "--selftest" in sys.argv:
        selftest(main)
    else:
        main.license_gate()
    main.mainloop()
