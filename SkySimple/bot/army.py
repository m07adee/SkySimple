"""شريط الجيش في المعركة: قراءته مباشرة في كل معركة، ومعرفة نوع كل خانة والخانة الفارغة."""
import os

import cv2
import numpy as np

from . import vision

BAR = (745, 890)          # نطاق شريط الجيش عمودياً (دقة 1600×900)
CARD_W = 110              # عرض بطاقة الخانة
ICON = (12, 40, 98, 108)  # منطقة الصورة داخل البطاقة (x1, y1, x2, y2) بدون العدد والمستوى


def segment(screen, bar=BAR):
    """يقطع الشريط إلى بطاقات حسب السطوع. يرجع [(x1, x2)] لكل بطاقة."""
    band = screen[bar[0]:bar[1]]
    bright = band.mean(axis=2).mean(axis=0) > 70
    runs, start = [], None
    for x, on in enumerate(list(bright) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start > 55:
                # بطاقة جزء منها داكن (مثل آلة الحصار): نكمل عرضها الطبيعي من نهايتها
                a = x - CARD_W if x - start < CARD_W - 10 else start
                runs.append((max(0, a), x))
            start = None
    return [r for r in runs if r[1] - r[0] >= 90]


def icon(screen, x1, bar=BAR):
    y = bar[0]
    return screen[y + ICON[1]:y + ICON[3], x1 + ICON[0]:x1 + ICON[2]].copy()


def is_empty(screen, x, bar=BAR):
    """الخانة المستهلكة تصبح رمادية: تشبع لوني شبه معدوم."""
    x1 = max(0, int(x) - 40)
    region = screen[bar[0] + 30:bar[0] + 115, x1:x1 + 80]
    sat = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    return sat < 30


def guess_type(screen, a, b, bar=BAR):
    """تخمين نوع الخانة: الجنود والتعويذات عليها عدد (x14)، والجنود زرقاء والتعويذات بنفسجية."""
    card = screen[bar[0]:bar[0] + 140, a:b]
    hsv = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)
    hue = float(np.median(hsv[8:30, 8:max(9, (b - a) // 2), 0]))
    count = card[8:34, max(0, (b - a) - 55):(b - a) - 6]
    has_count = (count.min(axis=2) > 200).mean() > 0.14 if count.size else False
    if hue > 115:
        return "spell"
    return "troop" if has_count else "hero"


def is_placeholder(screen, a, b, bar=BAR):
    """خانة فارغة في آخر الشريط (إطار متقطع على خلفية حجرية): تكاد تخلو من الألوان.

    البطاقات الحقيقية ملونة بنسبة 33٪ فأكثر، والخانة الفارغة نحو 3٪.
    """
    hsv = cv2.cvtColor(screen[bar[0] + 50:bar[0] + 110, a + 15:max(a + 16, b - 15)], cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 90)).mean() < 0.12


def read_bar(screen, bar=BAR):
    """يقرأ شريط الجيش الحالي: [{"x", "type"}] بالترتيب، بدون الخانات الفارغة (رمادية).

    الأنواع: troop (عليها عدد)، spell (بنفسجية)، siege (أول بطاقة بلا عدد بعد الجنود بفراغ أوسع)،
    hero (بقية البطاقات بلا عدد: الأبطال وقوات القلعة).
    """
    slots, last_troop_end = [], None
    for a, b in segment(screen, bar):
        if is_placeholder(screen, a, b, bar):
            continue
        x = (a + b) // 2
        kind = guess_type(screen, a, b, bar)
        if kind == "hero" and last_troop_end is not None and a - last_troop_end > 25 \
                and not any(s["type"] == "siege" for s in slots):
            kind = "siege"
        if kind == "troop":
            last_troop_end = b
        if not is_empty(screen, x, bar):
            slots.append({"x": x, "type": kind})
    return slots


class ArmyBook:
    """صور خانات الجيش المحفوظة في templates/army/slot_N.png مع بياناتها في الإعدادات."""

    def __init__(self, folder, sub="army"):
        self.folder = os.path.join(folder, sub)
        os.makedirs(self.folder, exist_ok=True)
        self._cache = {}

    def path(self, sid):
        return os.path.join(self.folder, f"{sid}.png")

    def save(self, sid, img):
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(self.path(sid))
        self._cache.pop(sid, None)

    def get(self, sid):
        if sid not in self._cache:
            p = self.path(sid)
            self._cache[sid] = (cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
                                if os.path.isfile(p) else None)
        return self._cache[sid]

    def clear(self):
        for f in os.listdir(self.folder):
            if f.endswith(".png"):
                os.remove(os.path.join(self.folder, f))
        self._cache.clear()

    def scan(self, screen):
        """يمسح الشريط ويحفظ صورة كل خانة مع تخمين نوعها. يرجع قائمة الخانات."""
        self.clear()
        slots = []
        segs = segment(screen)
        last_troop_end = None
        for i, (a, b) in enumerate(segs):
            sid = f"slot_{i + 1}"
            self.save(sid, icon(screen, a))
            kind = guess_type(screen, a, b)
            # آلة الحصار: أول بطاقة بلا عدد بعد الجنود مباشرة، يفصلها عنهم فراغ أوسع
            if kind == "hero" and last_troop_end is not None and a - last_troop_end > 25 \
                    and not any(s["type"] == "siege" for s in slots):
                kind = "siege"
            if kind == "troop":
                last_troop_end = b
            slots.append({"id": sid, "x": (a + b) // 2, "type": kind, "spell": "rage",
                          "label": "", "enabled": True})
        return slots

    def locate(self, screen, slots, threshold=0.75):
        """يجد مكان كل خانة محفوظة في الشريط الحالي (قد يتغير الترتيب، أو يغيب بطل يتطور)."""
        band = screen[BAR[0]:BAR[1]]
        found = {}
        for s in slots:
            tpl = self.get(s["id"])
            hit = vision.find(band, tpl, threshold) if tpl is not None else None
            if hit:
                found[s["id"]] = (hit[0], BAR[0] + 70)
        return found
