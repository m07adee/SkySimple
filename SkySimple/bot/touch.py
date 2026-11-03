"""لمس متعدد عبر sendevent (لا يدعمه `input`): يُستخدم للتصغير بإصبعين حتى تظهر الخريطة كاملة."""

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
SLOT, TRACK, POS_X, POS_Y, PRESSURE, BTN_TOUCH, BTN_FINGER = 47, 57, 53, 54, 58, 330, 325
REL_WHEEL = 8
RELEASE = 4294967295  # -1 كعدد بلا إشارة


def find_touch_device(adb):
    """يبحث عن جهاز اللمس الذي يدعم ABS_MT_POSITION_X (0035)."""
    out = adb._run("shell", "getevent -p", timeout=15)
    device = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("add device"):
            device = line.split(":")[-1].strip()
        elif line.startswith("0035") or " 0035 " in line or line.endswith("0035"):
            if device and "max" in line:
                return device
        elif "ABS (0003): 0035" in line or "0035  :" in line:
            if device:
                return device
    return None


def _ev(dev, t, c, v):
    return f"sendevent {dev} {t} {c} {v}"


def pinch(adb, dev, center=(800, 450), start=420, end=40, steps=10):
    """إصبعان يقتربان من بعضهما (تصغير). start/end: نصف المسافة الأفقية بين الإصبعين.

    القيم مقيسة على 1600×900 وتُحوَّل لدقة المحاكي (إحداثيات اللمس = بكسلات الشاشة في LDPlayer).
    """
    sx, sy = getattr(adb, "sx", 1.0), getattr(adb, "sy", 1.0)
    cx, cy = int(center[0] * sx), int(center[1] * sy)
    start, end = int(start * sx), max(8, int(end * sx))
    cmds = [
        _ev(dev, EV_ABS, SLOT, 0), _ev(dev, EV_ABS, TRACK, 101), _ev(dev, EV_ABS, PRESSURE, 1),
        _ev(dev, EV_ABS, POS_X, cx - start), _ev(dev, EV_ABS, POS_Y, cy - start // 3),
        _ev(dev, EV_ABS, SLOT, 1), _ev(dev, EV_ABS, TRACK, 102), _ev(dev, EV_ABS, PRESSURE, 1),
        _ev(dev, EV_ABS, POS_X, cx + start), _ev(dev, EV_ABS, POS_Y, cy + start // 3),
        _ev(dev, EV_KEY, BTN_TOUCH, 1), _ev(dev, EV_KEY, BTN_FINGER, 1), _ev(dev, EV_SYN, 0, 0),
    ]
    for i in range(1, steps + 1):
        d = int(start + (end - start) * i / steps)
        cmds += [_ev(dev, EV_ABS, SLOT, 0), _ev(dev, EV_ABS, POS_X, cx - d), _ev(dev, EV_ABS, POS_Y, cy - d // 3),
                 _ev(dev, EV_ABS, SLOT, 1), _ev(dev, EV_ABS, POS_X, cx + d), _ev(dev, EV_ABS, POS_Y, cy + d // 3),
                 _ev(dev, EV_SYN, 0, 0)]
    cmds += [_ev(dev, EV_ABS, SLOT, 0), _ev(dev, EV_ABS, TRACK, RELEASE),
             _ev(dev, EV_ABS, SLOT, 1), _ev(dev, EV_ABS, TRACK, RELEASE),
             _ev(dev, EV_KEY, BTN_TOUCH, 0), _ev(dev, EV_KEY, BTN_FINGER, 0), _ev(dev, EV_SYN, 0, 0)]
    adb._run("shell", "; ".join(cmds), timeout=30)


def wheel(adb, dev, clicks=-5):
    """تدوير عجلة الفأرة (سالب = تصغير في أغلب الألعاب)."""
    step = -1 if clicks < 0 else 1
    cmds = []
    for _ in range(abs(clicks)):
        cmds += [_ev(dev, EV_REL, REL_WHEEL, step), _ev(dev, EV_SYN, 0, 0)]
    adb._run("shell", "; ".join(cmds), timeout=30)
