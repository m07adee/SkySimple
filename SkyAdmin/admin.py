"""لوحة مفاتيح سكاي — إنشاء مفاتيح التفعيل وإدارتها وتجهيز نسخة العملاء."""
import json
import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
import zipfile
from datetime import datetime, timezone
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
    RES = getattr(sys, "_MEIPASS", BASE)
else:
    BASE = RES = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(BASE, "..", "SkySimple"))

from bot import license as lic  # noqa: E402
from supa import Supa, SupaError, parse_time, status_of  # noqa: E402

VERSION = "1.0"
SETTINGS = os.path.join(os.environ.get("APPDATA", BASE), "SkyAdmin", "admin.json")

BG = "#0d1218"
CARD = "#16202b"
BORDER = "#22303f"
FIELD = "#0f1720"
ACCENT = "#1d9bf0"
ACCENT_HOVER = "#1683cc"
TEXT = "#e6edf3"
MUTED = "#8b9bab"
OK = "#22c55e"
DANGER = "#ef4444"
WARN = "#f59e0b"
FONT = "Tahoma"

DURATIONS = [("day", "يوم", 1), ("week", "أسبوع", 7), ("month", "شهر", 30), ("custom", "مخصص", None)]
STATUS = {"unused": ("غير مفعّل", MUTED), "active": ("فعّال", OK),
          "expired": ("منتهي", WARN), "revoked": ("موقوف", DANGER)}
# أعمدة الجدول من اليمين لليسار
COLUMNS = [("key", "المفتاح", 300), ("note", "العميل / ملاحظة", 150), ("days", "المدة", 70),
           ("status", "الحالة", 80), ("expires", "ينتهي", 160), ("left", "المتبقي", 80),
           ("device", "الجهاز", 195), ("ip", "آخر IP", 120), ("seen", "آخر ظهور", 160)]
# ملفات لا تُرسل للعملاء
SKIP_DIRS = {"source", "army", "__pycache__"}
SKIP_FILES = {"license_server.json", "selftest.txt"}


def rtl(text):
    return "\n".join("‏" + line + "‏" for line in str(text).split("\n"))


def ltr(text):
    return "‪" + str(text) + "‬"


def fmt_time(s):
    d = parse_time(s)
    return d.astimezone().strftime("%Y-%m-%d %H:%M") if d else "—"


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"url": "", "anon": "", "secret": ""}


def save_settings(s):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


class Admin(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.settings = load_settings()
        self.rows = []
        self.q = queue.Queue()
        self.title(f"لوحة مفاتيح سكاي  {VERSION}")
        self.geometry("1280x760")
        self.minsize(1100, 640)
        self.configure(fg_color=BG)
        ico = os.path.join(RES, "icon.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except tk.TclError:
                pass
        self._style()
        self.build()
        self.after(100, self._tick)
        if self.ready():
            self.refresh()
        else:
            self.set_status("أدخل بيانات Supabase أولاً من تبويب «الإعدادات»", WARN)

    # ---------- أدوات ----------
    def label(self, parent, text, size=13, weight="normal", color=TEXT, **kw):
        return ctk.CTkLabel(parent, text=rtl(text), font=(FONT, size, weight), text_color=color,
                            anchor="e", justify="right", **kw)

    def button(self, parent, text, command, color=ACCENT, hover=ACCENT_HOVER, **kw):
        return ctk.CTkButton(parent, text=rtl(text), command=command, font=(FONT, 13, "bold"),
                             fg_color=color, hover_color=hover, corner_radius=10,
                             height=kw.pop("height", 36), **kw)

    def entry(self, parent, width=200, **kw):
        return ctk.CTkEntry(parent, width=width, font=(FONT, 13), fg_color=FIELD, border_color=BORDER,
                            corner_radius=8, **kw)

    def card(self, parent):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=30,
                    borderwidth=0, font=(FONT, 11))
        s.configure("Treeview.Heading", background="#1b2733", foreground=MUTED, relief="flat",
                    font=(FONT, 11, "bold"))
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        s.map("Treeview.Heading", background=[("active", "#22303f")])

    def ready(self):
        return all(self.settings.get(k) for k in ("url", "anon", "secret"))

    def supa(self):
        return Supa(self.settings["url"], self.settings["secret"])

    def run(self, work, done=None, busy="جارٍ التنفيذ…"):
        """ينفذ طلب الشبكة في خيط منفصل ثم يرجع النتيجة لواجهة المستخدم."""
        self.set_status(busy, MUTED)

        def target():
            try:
                res = work()
                self.q.put(lambda: done(res) if done else None)
            except SupaError as e:
                msg = str(e)
                self.q.put(lambda: self.set_status("خطأ: " + msg, DANGER))
            except Exception as e:  # خطأ غير متوقع: يظهر للمستخدم بدل أن يختفي
                msg = f"{type(e).__name__}: {e}"
                self.q.put(lambda: self.set_status("خطأ: " + msg, DANGER))
        threading.Thread(target=target, daemon=True).start()

    def _tick(self):
        try:
            while not self.q.empty():
                self.q.get()()
        finally:
            self.after(100, self._tick)

    def set_status(self, text, color=MUTED):
        self.status.configure(text=rtl(text), text_color=color)

    # ---------- البناء ----------
    def build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 4))
        self.label(top, "لوحة مفاتيح سكاي", 22, "bold").pack(side="right")
        self.button(top, "تحديث ⟳", self.refresh, width=100).pack(side="left")
        self.status = self.label(top, "", 12)
        self.status.pack(side="right", padx=20, fill="x", expand=True)

        self.tabs = ctk.CTkTabview(self, fg_color="transparent", segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color=ACCENT_HOVER, anchor="ne")
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tabs._segmented_button.configure(font=(FONT, 14, "bold"))
        names = ["المفاتيح", "إنشاء مفاتيح", "الإعدادات"]
        for n in reversed(names):
            self.tabs.add(rtl(n))
        self._tab_keys(self.tabs.tab(rtl(names[0])))
        self._tab_create(self.tabs.tab(rtl(names[1])))
        self._tab_settings(self.tabs.tab(rtl(names[2])))
        # تبويب واحد فقط عند البداية: استدعاء set مرتين متتاليتين يخفي التبويب الثاني (مؤقت داخلي في customtkinter)
        self.tabs.set(rtl(names[0] if self.ready() else names[2]))

    def _tab_keys(self, p):
        # الإحصاءات
        self.counts = {}
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        for k, (name, color) in [("all", ("الكل", TEXT))] + list(STATUS.items()):
            c = self.card(row)
            c.pack(side="right", fill="x", expand=True, padx=(8, 0))
            self.label(c, name, 11, color=MUTED).pack(fill="x", padx=14, pady=(8, 0))
            v = self.label(c, "—", 20, "bold", color=color)
            v.pack(fill="x", padx=14, pady=(0, 8))
            self.counts[k] = v

        # البحث والتصفية
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        self.label(bar, "بحث:").pack(side="right")
        self.search = self.entry(bar, 260, placeholder_text="مفتاح أو اسم أو IP")
        self.search.pack(side="right", padx=6)
        self.search.bind("<KeyRelease>", lambda e: self.render())
        self.filter = tk.StringVar(value=rtl("الكل"))
        seg_values = [rtl(n) for n in ["الكل"] + [v[0] for v in STATUS.values()]]
        ctk.CTkSegmentedButton(bar, values=seg_values[::-1], variable=self.filter, font=(FONT, 12, "bold"),
                               selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                               command=lambda v: self.render()).pack(side="left")

        # الجدول
        box = self.card(p)
        box.pack(fill="both", expand=True)
        cols = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(box, columns=cols, displaycolumns=cols[::-1], show="headings",
                                 selectmode="extended")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width, anchor="center", stretch=key == "note")
        for st, (_, color) in STATUS.items():
            self.tree.tag_configure(st, foreground=color)
        sb = ctk.CTkScrollbar(box, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="left", fill="y", padx=(4, 0), pady=8)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda e: self.copy_keys())
        self.tree.bind("<Control-c>", lambda e: self.copy_keys())

        # الإجراءات
        act = ctk.CTkFrame(p, fg_color="transparent")
        act.pack(fill="x", pady=(8, 0))
        self.button(act, "نسخ المفتاح", self.copy_keys, width=110).pack(side="right", padx=(6, 0))
        self.button(act, "إيقاف", lambda: self.set_revoked(True), DANGER, "#c93636", width=90).pack(side="right", padx=(6, 0))
        self.button(act, "إعادة تفعيل", lambda: self.set_revoked(False), OK, "#1a9e4b", width=110).pack(side="right", padx=(6, 0))
        self.button(act, "إعادة ضبط الجهاز", self.reset_device, "#475569", "#334155", width=140).pack(side="right", padx=(6, 0))
        self.label(act, "تمديد (يوم):").pack(side="right", padx=(18, 0))
        self.extend_days = self.entry(act, 60, justify="center")
        self.extend_days.insert(0, "7")
        self.extend_days.pack(side="right", padx=6)
        self.button(act, "تمديد", self.extend, "#7c3aed", "#6d28d9", width=80).pack(side="right")
        self.button(act, "حذف", self.delete, "#3b1d1d", "#5b2323", width=80).pack(side="left")

    def _tab_create(self, p):
        box = self.card(p)
        box.pack(fill="x", pady=(0, 10))
        self.label(box, "إنشاء مفاتيح جديدة", 16, "bold").pack(fill="x", padx=18, pady=(14, 4))
        self.label(box, "مدة المفتاح تبدأ من لحظة تفعيله عند العميل، لا من لحظة إنشائه.", 12, color=MUTED).pack(fill="x", padx=18)

        r1 = ctk.CTkFrame(box, fg_color="transparent")
        r1.pack(fill="x", padx=18, pady=(12, 4))
        self.label(r1, "المدة:", width=110).pack(side="right")
        self.duration = tk.StringVar(value=rtl("شهر"))
        ctk.CTkSegmentedButton(r1, values=[rtl(d[1]) for d in DURATIONS][::-1], variable=self.duration,
                               font=(FONT, 13, "bold"), selected_color=ACCENT,
                               selected_hover_color=ACCENT_HOVER).pack(side="right", padx=6)
        self.custom_days = self.entry(r1, 70, justify="center", placeholder_text="أيام")
        self.custom_days.pack(side="right", padx=6)
        self.label(r1, "(للمخصص: عدد الأيام)", 11, color=MUTED).pack(side="right")

        r2 = ctk.CTkFrame(box, fg_color="transparent")
        r2.pack(fill="x", padx=18, pady=4)
        self.label(r2, "العدد:", width=110).pack(side="right")
        self.count = self.entry(r2, 70, justify="center")
        self.count.insert(0, "1")
        self.count.pack(side="right", padx=6)

        r3 = ctk.CTkFrame(box, fg_color="transparent")
        r3.pack(fill="x", padx=18, pady=4)
        self.label(r3, "اسم العميل / ملاحظة:", width=110).pack(side="right")
        self.note = self.entry(r3, 320, justify="right")
        self.note.pack(side="right", padx=6)

        self.button(box, "إنشاء", self.create_keys, OK, "#1a9e4b", width=160, height=40).pack(anchor="e", padx=18, pady=(10, 16))

        out = self.card(p)
        out.pack(fill="both", expand=True)
        head = ctk.CTkFrame(out, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(12, 4))
        self.label(head, "المفاتيح الجديدة", 15, "bold").pack(side="right")
        self.button(head, "نسخ الكل", self.copy_new, width=100).pack(side="left")
        self.new_box = ctk.CTkTextbox(out, font=("Consolas", 15), fg_color=FIELD, border_color=BORDER,
                                      border_width=1, corner_radius=10)
        self.new_box.pack(fill="both", expand=True, padx=18, pady=(0, 16))

    def _tab_settings(self, p):
        box = self.card(p)
        box.pack(fill="x", pady=(0, 10))
        self.label(box, "اتصال Supabase", 16, "bold").pack(fill="x", padx=18, pady=(14, 4))
        self.label(box, "من Supabase: Project Settings ← API Keys. المفتاح السري يبقى على جهازك فقط ولا يُرسل للعملاء أبداً.",
                   12, color=MUTED).pack(fill="x", padx=18)
        self.set_fields = {}
        for key, title, hide in (("url", "Project URL", False),
                                 ("anon", "المفتاح العام (Publishable / anon)", False),
                                 ("secret", "المفتاح السري (Secret / service_role)", True)):
            r = ctk.CTkFrame(box, fg_color="transparent")
            r.pack(fill="x", padx=18, pady=4)
            self.label(r, title, width=280).pack(side="right")
            e = self.entry(r, 560, show="•" if hide else "")
            e.insert(0, self.settings.get(key, ""))
            e.pack(side="right", padx=8)
            self.set_fields[key] = e
        r = ctk.CTkFrame(box, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(10, 16))
        self.button(r, "حفظ واختبار الاتصال", self.save_and_test, width=180).pack(side="right")
        self.button(r, "نسخ كود الإعداد (SQL)", self.copy_sql, "#475569", "#334155", width=180).pack(side="right", padx=8)

        box2 = self.card(p)
        box2.pack(fill="x")
        self.label(box2, "تجهيز نسخة العملاء", 16, "bold").pack(fill="x", padx=18, pady=(14, 4))
        self.label(box2, "ينشئ ملف ZIP فيه البرنامج مربوطاً بخادمك، بدون أي أكواد. أرسله للعميل مع مفتاحه.",
                   12, color=MUTED).pack(fill="x", padx=18)
        r = ctk.CTkFrame(box2, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(10, 16))
        self.button(r, "إنشاء نسخة العملاء (ZIP)", self.export_client, OK, "#1a9e4b", width=220, height=40).pack(side="right")

    # ---------- المفاتيح ----------
    def refresh(self):
        if not self.ready():
            return
        self.run(self.supa().list, self._loaded, "جارٍ تحميل المفاتيح…")

    def _loaded(self, rows):
        self.rows = rows or []
        self.render()
        self.set_status(f"تم التحميل — {len(self.rows)} مفتاح  ({datetime.now().strftime('%H:%M:%S')})", OK)

    def render(self):
        now = datetime.now(timezone.utc)
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        counts = {k: 0 for k in ["all"] + list(STATUS)}
        flt = self.filter.get().strip("‏")
        q = self.search.get().strip().lower()
        for r in self.rows:
            st = status_of(r, now)
            counts["all"] += 1
            counts[st] += 1
            if flt != "الكل" and STATUS[st][0] != flt:
                continue
            hay = " ".join(str(r.get(k) or "") for k in ("key", "note", "last_ip", "hwid")).lower()
            if q and q not in hay:
                continue
            exp = parse_time(r.get("expires_at"))
            if st == "active":
                secs = (exp - now).total_seconds()
                left = f"{int(secs // 86400)} يوم" if secs >= 86400 else f"{max(1, int(secs // 3600))} ساعة"
            else:
                left = "—"
            hw = r.get("hwid") or ""
            self.tree.insert("", "end", iid=r["key"], tags=(st,), values=(
                r["key"], r.get("note") or "", f"{r['duration_days']} يوم", STATUS[st][0],
                fmt_time(r.get("expires_at")), left, lic.short_id(hw) if hw else "—",
                r.get("last_ip") or "—", fmt_time(r.get("last_seen"))))
        for k, v in counts.items():
            self.counts[k].configure(text=str(v))
        keep = [k for k in selected if self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)

    def selected(self):
        keys = list(self.tree.selection())
        if not keys:
            self.set_status("اختر مفتاحاً من الجدول أولاً", WARN)
        return keys

    def copy_keys(self):
        keys = self.selected()
        if keys:
            self.clipboard_clear()
            self.clipboard_append("\n".join(keys))
            self.set_status(f"تم نسخ {len(keys)} مفتاح", OK)

    def _bulk(self, keys, fn, msg):
        def work():
            for k in keys:
                fn(k)
            return self.supa().list()

        def done(rows):
            self._loaded(rows)
            self.set_status(msg.format(n=len(keys)), OK)
        self.run(work, done)

    def set_revoked(self, revoked):
        keys = self.selected()
        if not keys:
            return
        if revoked and not messagebox.askyesno("إيقاف", f"إيقاف {len(keys)} مفتاح؟ سيتوقف البرنامج عند العميل خلال نصف ساعة."):
            return
        s = self.supa()
        self._bulk(keys, lambda k: s.update(k, {"status": "revoked" if revoked else "active"}),
                   "تم إيقاف {n} مفتاح" if revoked else "تمت إعادة تفعيل {n} مفتاح")

    def reset_device(self):
        keys = self.selected()
        if not keys or not messagebox.askyesno(
                "إعادة ضبط الجهاز", "فك ربط المفتاح بجهازه الحالي؟ أول جهاز يفعّله بعد ذلك يُربط به (المدة لا تتغير)."):
            return
        s = self.supa()
        self._bulk(keys, lambda k: s.update(k, {"hwid": None}), "تم فك ربط {n} مفتاح بأجهزتها")

    def extend(self):
        keys = self.selected()
        if not keys:
            return
        try:
            days = int(self.extend_days.get())
            assert 0 < days <= 3650
        except (ValueError, AssertionError):
            self.set_status("عدد أيام التمديد غير صحيح", WARN)
            return
        s = self.supa()
        self._bulk(keys, lambda k: s.extend(k, days), f"تم تمديد {{n}} مفتاح {days} يوم")

    def delete(self):
        keys = self.selected()
        if not keys or not messagebox.askyesno("حذف", f"حذف {len(keys)} مفتاح نهائياً؟ لا يمكن التراجع."):
            return
        s = self.supa()
        self._bulk(keys, s.delete, "تم حذف {n} مفتاح")

    def create_keys(self):
        if not self.ready():
            self.set_status("أدخل بيانات Supabase أولاً", WARN)
            return
        choice = self.duration.get().strip("‏")
        days = next(d[2] for d in DURATIONS if d[1] == choice)
        try:
            if days is None:
                days = int(self.custom_days.get())
            count = int(self.count.get())
            assert 0 < days <= 3650 and 0 < count <= 500
        except (ValueError, AssertionError):
            self.set_status("المدة أو العدد غير صحيح", WARN)
            return
        note = self.note.get().strip()

        def done(rows):
            keys = [r["key"] for r in rows]
            self.new_box.delete("1.0", "end")
            self.new_box.insert("1.0", "\n".join(keys))
            self.clipboard_clear()
            self.clipboard_append("\n".join(keys))
            self.set_status(f"تم إنشاء {len(keys)} مفتاح لمدة {days} يوم ونسخها", OK)
            self.refresh()
        self.run(lambda: self.supa().create(count, days, note), done, "جارٍ إنشاء المفاتيح…")

    def copy_new(self):
        text = self.new_box.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.set_status("تم النسخ", OK)

    # ---------- الإعدادات ----------
    def save_and_test(self):
        self.settings = {k: e.get().strip() for k, e in self.set_fields.items()}
        if not self.ready():
            self.set_status("املأ الحقول الثلاثة", WARN)
            return
        save_settings(self.settings)
        anon = self.settings["anon"]

        def work():
            s = self.supa()
            res = s.check_public(anon)
            if not (isinstance(res, dict) and res.get("error") == "invalid"):
                raise SupaError("المفتاح العام لا يصل لدالة التفعيل — هل شغّلت كود SQL؟")
            return s.list()

        def done(rows):
            self._loaded(rows)
            self.set_status("✅ الاتصال يعمل: المفتاح السري والعام ودالة التفعيل", OK)
        self.run(work, done, "جارٍ اختبار الاتصال…")

    def copy_sql(self):
        with open(os.path.join(RES, "setup.sql"), encoding="utf-8") as f:
            sql = f.read()
        self.clipboard_clear()
        self.clipboard_append(sql)
        self.set_status("تم نسخ كود SQL — الصقه في Supabase ← SQL Editor ← Run", OK)

    def export_client(self):
        if not self.ready():
            self.set_status("احفظ بيانات Supabase أولاً", WARN)
            return
        src = os.path.join(BASE, "client")
        if not os.path.isfile(os.path.join(src, "SkySimple.exe")):
            src = filedialog.askdirectory(title="اختر مجلد برنامج SkySimple (الذي فيه SkySimple.exe)")
            if not src or not os.path.isfile(os.path.join(src, "SkySimple.exe")):
                self.set_status("لم أجد SkySimple.exe في المجلد", WARN)
                return
        out = filedialog.asksaveasfilename(title="حفظ نسخة العملاء", defaultextension=".zip",
                                           initialfile="SkySimple.zip", filetypes=[("ZIP", "*.zip")])
        if not out:
            return
        url, anon = self.settings["url"], self.settings["anon"]
        self.run(lambda: build_client_zip(src, out, url, anon),
                 lambda n: self.set_status(f"✅ تم إنشاء نسخة العملاء ({n} ملف): {out}", OK),
                 "جارٍ تجهيز نسخة العملاء…")


def build_client_zip(src, out, url, anon):
    """ينسخ مجلد البرنامج إلى ZIP، ويختم SkySimple.exe بعنوان الخادم، ويستبعد الإعدادات الشخصية."""
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        stamped = os.path.join(tmp, "SkySimple.exe")
        lic.write_stamp(os.path.join(src, "SkySimple.exe"), stamped, url, anon)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(stamped, "SkySimple/SkySimple.exe")
            n += 1
            for root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("army_")]
                for name in files:
                    rel = os.path.relpath(os.path.join(root, name), src)
                    if rel == "SkySimple.exe" or name in SKIP_FILES or \
                            (rel == name and name.endswith(".json") and name.split(".")[0].split("_")[0] in ("config", "stats")):
                        continue
                    z.write(os.path.join(root, name), "SkySimple/" + rel.replace("\\", "/"))
                    n += 1
    return n


if __name__ == "__main__":
    Admin().mainloop()
