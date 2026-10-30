"""قراءة أرقام اللعبة (الغنائم والمكافآت) بمقارنة الرموز بقوالب أرقام مأخوذة من شاشة المستخدم.

لا يحتاج Tesseract: يفصل الأرقام الفاتحة ذات الحدود الداكنة، يقطّعها إلى رموز، ثم يقارن كل رمز بالقوالب.
"""
import json
import os

import cv2
import numpy as np

GLYPH = (16, 24)  # حجم الرمز بعد التوحيد (عرض، ارتفاع)


def binarize(crop):
    """الأرقام فاتحة (كريمي/وردي/أبيض): أصغر القنوات الثلاث مرتفع، والخلفية الخضراء/الترابية لا."""
    mn = crop.min(axis=2)
    mask = (mn > 165).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def _split(cols, a, b, digit_w):
    """يقسم مقطعاً عريضاً (رقمان متلاصقان) عند أضعف عمود في وسطه."""
    # عرض رقم صغير جداً يعني أن المنطقة ليست أرقاماً أصلاً: لا تقسيم (يمنع التكرار اللانهائي)
    if digit_w < 5 or b - a <= digit_w * 1.35:
        return [(a, b)]
    lo, hi = a + int(digit_w * 0.6), b - int(digit_w * 0.6)
    if hi <= lo:
        return [(a, b)]
    cut = lo + int(np.argmin(cols[lo:hi]))
    return _split(cols, a, cut, digit_w) + _split(cols, cut, b, digit_w)


def glyphs(crop, min_fill=0.45):
    """يرجع قائمة الرموز (x، العرض، صورة موحدة الحجم) من اليسار لليمين."""
    mask = binarize(crop)
    rows = np.where(mask.max(axis=1) > 0)[0]
    if len(rows) == 0:
        return []
    # نطاق الأسطر الأكثر امتلاءً هو سطر الأرقام (نتجاهل بقعاً فاتحة صغيرة في الخلفية)
    row_fill = (mask > 0).sum(axis=1)
    band = np.where(row_fill > row_fill.max() * 0.15)[0]
    top, bottom = band[0], band[-1] + 1
    digit_h = bottom - top
    if digit_h < crop.shape[0] * 0.3:
        return []  # لا يوجد سطر أرقام بارتفاع معقول
    m = mask[top:bottom]
    cols = (m > 0).sum(axis=0)
    segs, start = [], None
    for x, c in enumerate(list(cols) + [0]):
        if c and start is None:
            start = x
        elif not c and start is not None:
            segs.append((start, x))
            start = None
    out = []
    for a, b in segs:
        for sa, sb in _split(cols, a, b, digit_h * 0.72):
            g = m[:, sa:sb]
            # استبعاد الشوائب: رموز ضيقة جداً أو قليلة الامتلاء في الارتفاع
            filled = np.where(g.max(axis=1) > 0)[0]
            if sb - sa < 3 or len(filled) < digit_h * min_fill:
                continue
            g = g[filled[0]:filled[-1] + 1]  # كل رمز بارتفاعه الحقيقي حتى لا يتشوه عند التوحيد
            out.append((sa, sb - sa, cv2.resize(g, GLYPH, interpolation=cv2.INTER_AREA)))
    return out


def _score(a, b):
    a = a.astype(np.float32).ravel() - a.mean()
    b = b.astype(np.float32).ravel() - b.mean()
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d else 0.0


class DigitReader:
    def __init__(self, path=None):
        self.path = path
        self.protos = {}  # الرقم -> قائمة صور
        if path and os.path.isfile(path):
            data = np.load(path)
            for k in data.files:
                self.protos[k] = list(data[k])

    def ready(self):
        return len(self.protos) == 10

    def learn(self, crop, text):
        """يتعلم من منطقة رقمها معروف. يرجع True إذا تطابق عدد الرموز مع عدد الأرقام."""
        digits = [ch for ch in str(text) if ch.isdigit()]
        gs = glyphs(crop)
        if len(gs) != len(digits):
            return False
        for d, (_, _, g) in zip(digits, gs):
            self.protos.setdefault(d, []).append(g)
        return True

    def save(self, path=None):
        np.savez_compressed(path or self.path, **{k: np.array(v) for k, v in self.protos.items()})

    def read(self, crop, min_score=0.55):
        """يرجع الرقم المقروء (int) أو None."""
        if not self.protos:
            return None
        out = []
        for _, _, g in glyphs(crop):
            best, best_s = None, -1
            for d, protos in self.protos.items():
                s = max(_score(g, p) for p in protos)
                if s > best_s:
                    best, best_s = d, s
            if best_s >= min_score:
                out.append(best)
        return int("".join(out)) if out else None
