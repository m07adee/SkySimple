"""استراتيجيات الإنزال في القرية الرئيسية وهندسة منطقة الإنزال.

منطقة الإنزال معيّن بأربع زوايا (يسار، أعلى، يمين، أسفل) على حافة ساحة المعركة،
وكل ضلع من أضلاعه الأربعة جهة هجوم محتملة.

بعد التصغير الكامل تظهر ساحة المعركة دائماً في المكان نفسه من الشاشة (1600×900)،
لذلك المنطقة ثابتة ولا تحتاج معايرة.
"""
import cv2
import numpy as np

EDGES = {
    "top_left": ("left", "top"),
    "top_right": ("top", "right"),
    "bottom_right": ("right", "bottom"),
    "bottom_left": ("bottom", "left"),
}
EDGE_ORDER = ["top_left", "top_right", "bottom_right", "bottom_left"]

# زوايا ساحة المعركة بعد التصغير الكامل، مقيسة على معارك حقيقية بدقة 1600×900
DEFAULT_AREA = {"left": [150, 448], "top": [800, 32], "right": [1460, 448], "bottom": [800, 860]}

# إعدادات كل استراتيجية: عدد الجهات، مدى انتشار الجنود على الضلع، متى تُرمى التعويذات،
# وكم تتعمق أول تعويذة على مسار الهجوم (0 = الحافة، 1 = المركز)
PROFILES = {
    # ذكي: يناسب أي جيش، جهتان متجاورتان بانتشار متوسط
    "smart": {"sides": 2, "spread": 0.8, "hero_delay": 5, "spell_delay": 12, "spell_frac": 0.4},
    # التنانين الكهربائية: جهة واحدة مركّزة، ثم تعويذات على مسارها نحو المركز
    "edrag": {"sides": 1, "spread": 0.7, "hero_delay": 4, "spell_delay": 10, "spell_frac": 0.35},
    # التنانين العادية: انتشار عريض على جهتين متجاورتين، والتعويذات أعمق قليلاً
    "dragons": {"sides": 2, "spread": 0.9, "hero_delay": 6, "spell_delay": 14, "spell_frac": 0.45},
    # العفاريت المتسللة: مجموعات سريعة من ثلاث جهات، وتسريع مبكر فوقها
    "goblins": {"sides": 3, "spread": 0.45, "hero_delay": 2, "spell_delay": 3, "spell_frac": 0.25},
}
METHOD_SIDES = {"one_side": 1, "two_sides": 2, "three_sides": 3, "all_sides": 4}


def corners(area):
    return {k: np.array(area[k], dtype=float) for k in ("left", "top", "right", "bottom")}


def center(area):
    c = corners(area)
    return sum(c.values()) / 4


def edge_points(area, edge, n, spread=0.8):
    """n نقطة موزعة على الضلع، في الجزء الأوسط منه بنسبة spread."""
    c = corners(area)
    a, b = c[EDGES[edge][0]], c[EDGES[edge][1]]
    lo, hi = (1 - spread) / 2, (1 + spread) / 2
    ts = [0.5] if n <= 1 else np.linspace(lo, hi, n)
    return [tuple(int(v) for v in a + (b - a) * k) for k in ts]


def edge_mid(area, edge):
    return edge_points(area, edge, 1)[0]


def toward_center(area, point, frac):
    p, c = np.array(point, float), center(area)
    return tuple(int(v) for v in p + (c - p) * frac)


def building_density(screen, area, edge):
    """نسبة المباني (غير العشب) قرب الضلع من الداخل: كلما زادت بدأ الهجوم أسرع وضاع وقت أقل في المشي."""
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    h, w = screen.shape[:2]
    samples = []
    for p in edge_points(area, edge, 7, 0.7):
        for frac in (0.1, 0.18, 0.26):
            x, y = toward_center(area, p, frac)
            x1, y1 = max(0, x - 20), max(0, y - 20)
            patch = hsv[y1:min(h, y + 20), x1:min(w, x + 20)]
            if patch.size == 0:
                continue
            grass = ((patch[:, :, 0] > 28) & (patch[:, :, 0] < 70) & (patch[:, :, 1] > 90)).mean()
            samples.append(1 - grass)
    return float(np.mean(samples)) if samples else 0.0


def choose_edges(screen, area, side, sides, attack_no=0):
    """يختار الجهة الأولى (تلقائياً حسب كثافة المباني، أو ثابتة، أو بالتناوب) ثم يضيف الجهات المجاورة."""
    if side == "auto" and screen is not None:
        first = max(EDGE_ORDER, key=lambda e: building_density(screen, area, e))
    elif side == "rotate":
        first = EDGE_ORDER[attack_no % 4]
    elif side in EDGES:
        first = side
    else:
        first = "top_left"
    i = EDGE_ORDER.index(first)
    order = [EDGE_ORDER[(i + k) % 4] for k in (0, 1, 3, 2)]  # الأولى، المجاورتان، ثم المقابلة
    return order[:max(1, min(4, sides))]


def plan(profile_name, method, side, screen, area, attack_no=0):
    """يرجع (ملف الاستراتيجية، قائمة الجهات)."""
    prof = PROFILES.get(profile_name, PROFILES["smart"])
    sides = METHOD_SIDES.get(method, prof["sides"])
    return prof, choose_edges(screen, area, side, sides, attack_no)
