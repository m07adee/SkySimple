"""البحث عن الأزرار في الشاشة بمطابقة القوالب (OpenCV) وقراءة الموارد (اختياري)."""
import os
import re

import cv2
import numpy as np


class Templates:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self._cache = {}

    def path(self, name):
        return os.path.join(self.folder, name + ".png")

    def exists(self, name):
        return os.path.isfile(self.path(name))

    def get(self, name):
        if name not in self._cache:
            p = self.path(name)
            if not os.path.isfile(p):
                return None
            # imdecode يدعم المسارات العربية على ويندوز بعكس imread
            self._cache[name] = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
        return self._cache[name]

    def save(self, name, img):
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(self.path(name))
            self._cache.pop(name, None)
        return ok


DIM_RATIO = 0.75


def find(screen, template, threshold=0.8, scales=None):
    """يرجع (x, y, الدقة) لمركز القالب أو None. scales: أحجام إضافية للقالب (لعناصر تتغير مع تقريب الكاميرا)."""
    if screen is None or template is None:
        return None
    if scales:
        best = None
        for s in scales:
            tpl = template if s == 1 else cv2.resize(template, None, fx=s, fy=s, interpolation=cv2.INTER_AREA
                                                     if s < 1 else cv2.INTER_LINEAR)
            hit = find(screen, tpl, threshold)
            if hit and (best is None or hit[2] > best[2]):
                best = hit
        return best
    th, tw = template.shape[:2]
    if th > screen.shape[0] or tw > screen.shape[1]:
        return None
    if template.std() < 2:
        # قالب بلون واحد: CCOEFF لا معنى له، نستخدم فرق المربعات
        res = cv2.matchTemplate(screen, template, cv2.TM_SQDIFF_NORMED)
        val, _, loc, _ = cv2.minMaxLoc(res)
        score = 1.0 - val
    else:
        res = np.nan_to_num(cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED), nan=0.0)
        _, score, _, loc = cv2.minMaxLoc(res)
    if score < threshold:
        return None
    # المطابقة لا تتأثر بالسطوع، فالزر المعتم خلف نافذة حوار يطابق أيضاً؛ نرفضه هنا
    region = screen[loc[1]:loc[1] + th, loc[0]:loc[0] + tw]
    if region.mean() < template.mean() * DIM_RATIO:
        return None
    return loc[0] + tw // 2, loc[1] + th // 2, float(score)


def find_all(screen, template, threshold=0.8, max_hits=40, scales=None):
    """كل مواقع القالب على الشاشة (لفقاعات الجمع المتعددة)، مرتبة من الأعلى دقة."""
    if screen is None or template is None:
        return []
    if scales:
        merged = []
        for s in scales:
            tpl = template if s == 1 else cv2.resize(template, None, fx=s, fy=s, interpolation=cv2.INTER_AREA
                                                     if s < 1 else cv2.INTER_LINEAR)
            for hit in find_all(screen, tpl, threshold, max_hits):
                r = template.shape[1] * s / 2
                # نفس الهدف بحجمين مختلفين: نحتفظ بالأدق فقط
                same = [m for m in merged if abs(m[0] - hit[0]) < r and abs(m[1] - hit[1]) < r]
                if not same:
                    merged.append(hit)
                elif hit[2] > same[0][2]:
                    merged[merged.index(same[0])] = hit
        return sorted(merged, key=lambda h: -h[2])[:max_hits]
    th, tw = template.shape[:2]
    if th > screen.shape[0] or tw > screen.shape[1]:
        return []
    res = np.nan_to_num(cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED), nan=0.0)
    hits = []
    tmean = template.mean()
    while len(hits) < max_hits:
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < threshold:
            break
        x, y = loc
        region = screen[y:y + th, x:x + tw]
        if region.mean() >= tmean * DIM_RATIO:
            hits.append((x + tw // 2, y + th // 2, float(score)))
        # كبت المنطقة المحيطة حتى لا يتكرر نفس الهدف
        res[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = 0
    return hits


def read_number(screen, region):
    """قراءة رقم من منطقة (x, y, w, h) باستخدام Tesseract إن كان مثبتاً، وإلا None."""
    try:
        import pytesseract
    except ImportError:
        return None
    x, y, w, h = region
    crop = screen[y:y + h, x:x + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # أرقام الموارد في اللعبة فاتحة اللون فوق خلفية متغيرة
    _, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    bw = cv2.resize(bw, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    text = pytesseract.image_to_string(bw, config="--psm 7 -c tessedit_char_whitelist=0123456789")
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None
