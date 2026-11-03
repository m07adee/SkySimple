"""مراقبة تجمّد اللعبة: إذا بقيت الشاشة ثابتة تماماً أو تعذّر التقاطها لفترة، أو طال الهجوم أكثر من اللازم."""
import time

import cv2


class GameFrozen(Exception):
    """اللعبة متجمّدة أو عالقة: الحل إغلاقها وإعادة تشغيلها."""


class Watchdog:
    # اللعبة تتحرك دائماً (مؤقت المعركة، الغيوم، أعلام القرية)، فالشاشة المتطابقة تماماً تعني تجمّداً
    CHANGED_PIXELS = 20
    PIXEL_DIFF = 10

    def __init__(self, freeze_seconds=60, attack_seconds=720):
        self.freeze_seconds = freeze_seconds
        self.attack_seconds = attack_seconds
        self.deadline = None
        self.reset()

    def reset(self):
        self.last = None
        self.last_at = None
        self.alive_at = time.time()

    def start_attack(self):
        # لا نصفّر عدّاد الثبات هنا: محاولات فاشلة متتالية على شاشة متجمّدة يجب أن تُكشف
        self.deadline = time.time() + self.attack_seconds if self.attack_seconds else None

    def end_attack(self):
        self.deadline = None

    def observe(self, img):
        now = time.time()
        # فجوة طويلة بين لقطتين (انتظار أو استراحة): لم نكن نراقب، فنبدأ العدّ من جديد
        if img is not None and self.last_at is not None and now - self.last_at > self.freeze_seconds:
            self.reset()
        self.last_at = now
        if img is not None:
            small = cv2.cvtColor(cv2.resize(img, (400, 225), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            if self.last is None or self.changed(small, self.last):
                self.alive_at = now
            self.last = small
        if now - self.alive_at > self.freeze_seconds:
            raise GameFrozen("frozen" if img is not None else "no_screen")
        if self.deadline and now > self.deadline:
            self.deadline = None
            raise GameFrozen("stuck")

    def changed(self, a, b):
        return int((cv2.absdiff(a, b) > self.PIXEL_DIFF).sum()) >= self.CHANGED_PIXELS


class WatchedADB:
    """يمرّر كل أوامر ADB كما هي، ويفحص كل لقطة شاشة بالمراقب."""

    def __init__(self, adb, watchdog):
        self._adb = adb
        self._watch = watchdog

    def screenshot(self):
        img = self._adb.screenshot()
        self._watch.observe(img)
        return img

    def __getattr__(self, name):
        return getattr(self._adb, name)
