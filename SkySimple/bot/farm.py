"""حلقة الهجوم التلقائي في القرية الرئيسية، مع أدوات مشتركة للقرية الليلية."""
import random
import threading
import time

import os

from . import touch, vision
from .clan import ClanMixin
from .deploy import StrategyDeployer
from .i18n import btn_name, t
from .notify import Notifier
from .ocr import DigitReader
from .watchdog import GameFrozen, Watchdog, WatchedADB

MAX_ERRORS_IN_ROW = 5
ERRORS_BEFORE_RESTART = 3
# إعادات تشغيل متتالية للعبة بلا هجوم ناجح: بعدها نعيد تشغيل المحاكي، ثم نتوقف
RESTARTS_BEFORE_REBOOT = 2
MAX_RESTARTS_IN_ROW = 4
# عناصر الخريطة (القارب، الفقاعات، العربة) يتغير حجمها مع تقريب الكاميرا
MAP_SCALES = (0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.3)
BOAT_SCALES = MAP_SCALES
# مناطق أرقام الغنائم (x, y, w, h) بدقة 1600×900
LOOT_REGIONS = {"gold": (82, 110, 160, 36), "elixir": (82, 157, 160, 36), "dark": (82, 204, 160, 36)}
RESULT_REGIONS = {"gold": (690, 392, 150, 44), "elixir": (690, 452, 150, 44), "dark": (690, 512, 150, 44)}
BB_RESULT_REGIONS = {"bb_gold": (900, 538, 160, 42)}


class Stopped(Exception):
    pass


class AttackAborted(Exception):
    """الهجوم لم يكتمل لسبب يمكن التعافي منه (شاشة غير متوقعة...)."""


class Farmer(StrategyDeployer, ClanMixin):
    village = "home"

    def __init__(self, adb, cfg, templates, log, on_stats=None):
        f = cfg["farm"]
        self.watchdog = Watchdog(f.get("freeze_seconds", 60), f.get("attack_max_seconds", 720))
        self.adb = WatchedADB(adb, self.watchdog)
        self.cfg = cfg
        self.tpl = templates
        self.log = log
        self.on_stats = on_stats or (lambda s: None)
        self.stop_event = threading.Event()
        self.stats = {"attacks": 0, "skipped": 0, "errors": 0, "started": time.time(),
                      "gold": 0, "elixir": 0, "dark": 0, "history": []}
        self.digits = DigitReader(os.path.join(templates.folder, "digits.npz"))
        self.notifier = Notifier(cfg, log)
        self._touch_dev = None

    # ---------- أدوات مساعدة ----------
    def sleep(self, seconds):
        if self.stop_event.wait(seconds):
            raise Stopped()

    def check_stop(self):
        if self.stop_event.is_set():
            raise Stopped()

    def jitter(self, x, y):
        p = self.cfg["farm"].get("click_jitter", 4)
        return x + random.randint(-p, p), y + random.randint(-p, p)

    def tap(self, x, y):
        self.check_stop()
        self.adb.tap(*self.jitter(x, y))
        self.sleep(self.cfg["farm"].get("click_delay", 0.15))

    def find_now(self, name, screen):
        tpl = self.tpl.get(name)
        if tpl is None:
            return None
        hit = vision.find(screen, tpl, self.cfg["farm"].get("match_threshold", 0.8))
        return (hit[0], hit[1]) if hit else None

    def wait_any(self, names, timeout):
        """ينتظر ظهور أي قالب من القائمة ويرجع (الاسم، الموقع) أو (None, None)."""
        names = [n for n in names if self.tpl.exists(n)]
        if not names:
            return None, None
        end = time.time() + timeout
        while True:
            screen = self.adb.screenshot()
            for n in names:
                pos = self.find_now(n, screen)
                if pos:
                    return n, pos
            if time.time() >= end:
                return None, None
            self.sleep(0.7)

    def wait_for(self, name, timeout):
        """ينتظر ظهور قالب الزر ويرجع موقعه، أو None عند انتهاء المهلة."""
        return self.wait_any([name], timeout)[1]

    def press(self, name, timeout=10, wait_after=1.0):
        """يضغط الزر: بالقالب إن وُجد، وإلا بالإحداثيات المحفوظة."""
        pos = self.wait_for(name, timeout) if self.tpl.exists(name) else None
        if pos is None:
            c = self.cfg["buttons"].get(name)
            if not c:
                self.log(t("log_no_btn", name=btn_name(name)))
                return False
            pos = c["x"], c["y"]
        self.tap(*pos)
        self.sleep(wait_after)
        return True

    # ---------- حالة اللعبة ----------
    def ensure_game(self):
        """يتأكد أن ADB يعمل وأن اللعبة هي التطبيق الظاهر، ويعيد تشغيلها إن لزم."""
        focus = self.adb.current_app()
        if not focus:
            self.log(t("log_reconnect"))
            self.adb.connect()
            self.sleep(2)
            focus = self.adb.current_app()
        package = self.cfg.get("package", "com.supercell.clashofclans")
        # تعذّر معرفة التطبيق الظاهر (خدمة النوافذ لا تستجيب): نشغّل اللعبة احتياطاً، فتشغيلها وهي مفتوحة لا يضر
        if package not in focus:
            self.log(t("log_game_restart"))
            self.adb.start_app(package)
            self.sleep(self.cfg["farm"].get("game_boot_seconds", 35))

    def close_popups(self):
        """يعيد تحميل اللعبة عند انقطاع الاتصال، ويغلق النوافذ المنبثقة (تغيير المظهر، العروض...)."""
        for _ in range(4):
            screen = self.adb.screenshot()
            pos = self.find_now("reload_game", screen)
            if pos:
                self.log(t("log_reload"))
                self.tap(*pos)
                self.sleep(self.cfg["farm"].get("reload_wait", 25))
                continue
            pos = self.find_now("close_popup", screen)
            if not pos:
                return
            self.log(t("log_popup"))
            self.tap(*pos)
            self.sleep(1.5)

    def current_village(self, screen=None):
        screen = self.adb.screenshot() if screen is None else screen
        if self.find_now("attack", screen):
            return "home"
        if self.find_now("bb_attack", screen):
            return "builder"
        return None

    def ensure_village(self, target):
        """ينتقل بالقارب إلى القرية المطلوبة إن لزم."""
        if not (self.tpl.exists("attack") and self.tpl.exists("bb_attack")):
            return True  # لا يمكن التمييز بين القريتين بدون القالبين
        for _ in range(4):
            screen = self.adb.screenshot()
            where = self.current_village(screen)
            if where == target:
                return True
            if where is None:
                # شاشة تحميل (بعد القارب أو إعادة التشغيل): ننتظر قبل «رجوع» الذي قد يقطع الانتقال
                if not self.wait_any(["attack", "bb_attack"], 12)[0]:
                    self.recover_screen(self.adb.screenshot())
                continue
            boat = "boat_to_builder" if target == "builder" else "boat_to_home"
            if not self.tpl.exists(boat):
                self.log(t("log_no_boat_tpl", name=btn_name(boat)))
                return False
            pos = self.find_boat(boat)
            if not pos:
                self.log(t("log_no_boat", name=btn_name(boat)))
                return False
            self.log(t("log_boat"))
            self.tap(*pos)
            self.sleep(8)
        return self.current_village() == target

    # اتجاه سحب الكاميرا لإظهار القارب: قارب الرئيسية أسفل اليسار، وقارب الليلية أعلى اليمين
    BOAT_PAN = {"boat_to_builder": (700, 450, 1200, 150), "boat_to_home": (1000, 300, 600, 650)}

    def find_boat(self, boat):
        """يبحث عن القارب، ويسحب الكاميرا نحوه إن لم يكن ظاهراً (بعد الانتقال تبدأ الكاميرا مقرّبة)."""
        threshold = self.cfg["farm"].get("match_threshold", 0.8)
        # القارب دائماً عند حافة الخريطة: الليلي في أقصى اليمين، والرئيسي في أقصى اليسار.
        # ندفع العرض نحو تلك الحافة (الكاميرا تتوقف عند حدود الخريطة) ثم نمسح للأسفل وللأعلى.
        side = 1 if boat == "boat_to_home" else -1
        view = [(side, 0)] * 3 + [(0, 1)] * 2 + [(0, -1)] * 4
        pans = [(-vx * 450, -vy * 300) for vx, vy in view]  # الإصبع يتحرك عكس اتجاه العرض
        for attempt in range(len(pans) + 1):
            hit = vision.find(self.adb.screenshot(), self.tpl.get(boat), threshold, scales=BOAT_SCALES)
            if hit:
                return hit[0], hit[1]
            if attempt == 0:
                # مبنى محدد يمنع تحريك الكاميرا: نقرة على شريط اللاعب العلوي تلغي التحديد دون فتح شيء
                self.adb.tap(800, 12)
                self.sleep(0.5)
                # ثم تصغير كامل يُظهر القارب غالباً دون تحريك (نحن نغادر هذه القرية على أي حال)
                self.pinch_out()
                continue
            if attempt < len(pans):
                self.log(t("log_pan"))
                px, py = pans[attempt]
                self.adb.swipe(800 - px // 2, 450 - py // 2, 800 + px // 2, 450 + py // 2, 500)
                self.sleep(1.2)
        return None

    def recover_screen(self, screen):
        """شاشة غير معروفة: ننهي شاشة نتائج عالقة، أو نغلق النوافذ، أو نضغط «رجوع» لإغلاق أي حوار."""
        for name in ("return_home", "bb_return_home"):
            pos = self.find_now(name, screen)
            if pos:
                self.tap(*pos)
                self.sleep(4)
                return
        if self.find_now("reload_game", screen) or self.find_now("close_popup", screen):
            self.close_popups()
            return
        pos = self.find_now("clan_chat_close", screen)
        if pos:  # دردشة الكلان مفتوحة
            self.tap(*pos)
            self.sleep(1)
            return
        self.log(t("log_back"))
        self.adb.back()
        self.sleep(1.5)

    def prepare(self):
        self.ensure_game()
        self.close_popups()
        if not self.ensure_village(self.village):
            name = t("nav_builder") if self.village == "builder" else t("nav_home")
            raise AttackAborted(t("log_wrong_village", name=name))
        self.zoom_out()
        self.collect()
        self.clan_request()

    def zoom_out(self):
        """تصغير الكاميرا بإصبعين حتى تظهر الخريطة كاملة: القارب والعربة والفقاعات وكل حواف ساحة المعركة."""
        # في القرية الليلية نقاط الإنزال مُعايَرة على التقريب الافتراضي، فلا نصغّر هناك
        if self.village != "home" or not self.cfg["farm"].get("zoom_out", True):
            return
        self.pinch_out()

    def pinch_out(self):
        if not hasattr(self.adb, "_run"):
            return
        if self._touch_dev is None:
            self._touch_dev = touch.find_touch_device(self.adb) or ""
        if not self._touch_dev:
            return
        for _ in range(2):
            touch.pinch(self.adb, self._touch_dev)
            self.sleep(0.6)

    # ---------- جمع الموارد ----------
    COLLECT_KEYS = {"home": ("collect_gold", "collect_elixir", "collect_dark"),
                    "builder": ("bb_collect_gold", "bb_collect_elixir")}

    def collect(self):
        c = self.cfg.get("collect", {})
        every = max(1, int(c.get("every", 1)))
        if self.stats["attacks"] % every:
            return
        if c.get("resources", True):
            self.collect_resources()
        if self.village == "builder" and c.get("elixir_cart", True):
            self.collect_cart()

    def collect_resources(self):
        """ينقر كل فقاعات الذهب والإكسير الظاهرة فوق المجمّعات."""
        screen = self.adb.screenshot()
        hits = []
        for key in self.COLLECT_KEYS[self.village]:
            hits += vision.find_all(screen, self.tpl.get(key), self.cfg["farm"].get("match_threshold", 0.8),
                                    scales=MAP_SCALES)
        if not hits:
            return 0
        self.log(t("log_collect", n=len(hits)))
        for x, y, _ in hits:
            self.tap(x, y)
            self.sleep(0.25)
            # فقاعة عربة الإكسير تشبه فقاعات المجمّعات، والنقر عليها يفتح نافذة العربة
            if self.village == "builder" and self.find_now("bb_cart_title", self.adb.screenshot()):
                self._cart_dialog()
        self.stats["collected"] = self.stats.get("collected", 0) + len(hits)
        return len(hits)

    def collect_cart(self):
        """عربة الإكسير في القرية الليلية: تقع خارج العرض الافتراضي بجانب القارب."""
        if not self.tpl.exists("bb_cart") and not self.tpl.exists("bb_cart_bubble"):
            return False
        threshold = self.cfg["farm"].get("match_threshold", 0.8)
        swipes = 0
        result = None
        try:
            for attempt in range(4):
                screen = self.adb.screenshot()
                # عندما تمتلئ العربة تظهر فوقها فقاعة إكسير تغطي جزءاً منها، فنبحث عن أي منهما
                hit = (vision.find(screen, self.tpl.get("bb_cart"), threshold, scales=BOAT_SCALES)
                       or vision.find(screen, self.tpl.get("bb_cart_bubble"), threshold, scales=BOAT_SCALES))
                if hit:
                    self.tap(*hit[:2])
                    if self.wait_for("bb_cart_title", 4):
                        result = self._cart_dialog()
                        return result
                    # الفقاعة كانت لمجمّع إكسير (نفس الشكل) وجُمعت مباشرة؛ نتابع البحث عن العربة
                # سحب قصير نحو القارب (أعلى اليمين) حتى لا نتجاوز العربة
                self.adb.swipe(1000, 300, 800, 480, 500)
                swipes += 1
                self.sleep(1.2)
            self.log(t("log_no_cart"))
            return False
        finally:
            # إرجاع الكاميرا لموضعها حتى يجد البوت القارب والأزرار كما كانت
            for _ in range(swipes):
                self.adb.swipe(800, 480, 1000, 300, 500)
                self.sleep(0.6)

    def _cart_dialog(self):
        screen = self.adb.screenshot()
        bx, by = self.cfg["buttons"].get("bb_cart_collect", {"x": 1176, "y": 758}).values()
        b, g, r = screen[by - 25:by + 25, bx - 80:bx + 80].reshape(-1, 3).mean(axis=0)
        collected = bool(g > r + 25 and g > b + 25)  # الزر أخضر فقط عندما توجد مكافآت
        if collected:
            self.tap(bx, by)
            self.sleep(2)
            self.log(t("log_cart_collected"))
            self.stats["cart"] = self.stats.get("cart", 0) + 1
        else:
            self.log(t("log_cart_empty"))
        self.adb.back()  # إغلاق نافذة العربة
        self.sleep(1.2)
        return collected

    # ---------- خطوات الهجوم ----------
    def loot_ok(self, screen):
        loot = self.cfg["loot"]
        if not loot.get("enabled"):
            return True
        values = self.read_loot(screen, LOOT_REGIONS)
        if values["gold"] is None:
            self.log(t("log_loot_fail"))
            return True
        g, e, d = values["gold"], values["elixir"] or 0, values["dark"] or 0
        self.log(t("log_loot", g=g, e=e, d=d))
        return g >= loot["min_gold"] and e >= loot["min_elixir"] and d >= loot["min_dark"]

    def read_stable_loot(self, regions, guard, tries=6):
        """أرقام شاشة النتائج تتصاعد لثوانٍ: نقرأ حتى تتطابق قراءتان متتاليتان.

        guard: قالب يجب أن يبقى ظاهراً (زر العودة)، حتى لا نقرأ أرقاماً من شاشة أخرى.
        """
        last = None
        for _ in range(tries):
            screen = self.adb.screenshot()
            if self.tpl.exists(guard) and not self.find_now(guard, screen):
                break
            cur = self.read_loot(screen, regions)
            if cur == last and any(v is not None for v in cur.values()):
                return cur
            last = cur
            self.sleep(0.8)
        return last or {}

    def read_loot(self, screen, regions):
        """قراءة الأرقام بقوالب الأرقام المتعلمة (بدون Tesseract)."""
        out = {}
        for k, (x, y, w, h) in regions.items():
            ok = self.digits.ready() and screen is not None
            out[k] = self.digits.read(screen[y:y + h, x:x + w]) if ok else None
        return out

    def search_base(self):
        """يرجع لقطة القرية المختارة (تُستخدم لاختيار جهة الهجوم)."""
        f = self.cfg["farm"]
        for _ in range(f.get("max_skips", 30)):
            self.human_wait(f.get("search_wait", 4))
            screen = self.adb.screenshot()
            if self.loot_ok(screen):
                return screen
            self.stats["skipped"] += 1
            self.on_stats(self.stats)
            self.log(t("log_skip"))
            self.press("next_button", timeout=5, wait_after=0.5)
            # بعد «التالي» يجب أن تظهر قرية جديدة، وإلا فالشاشة غير متوقعة
            if self.tpl.exists("next_button") and not self.wait_for("next_button", 20):
                raise AttackAborted(t("log_no_battle"))
        self.log(t("log_max_skip"))
        return self.adb.screenshot()

    def finish_battle(self, deployed_at):
        f = self.cfg["farm"]
        remaining = max(10, f.get("battle_seconds", 200) - (time.time() - deployed_at))
        if self.tpl.exists("return_home"):
            pos = self.wait_for("return_home", remaining)
            if pos:
                self.last_gains = self.read_stable_loot(RESULT_REGIONS, "return_home")
                self.tap(*pos)
                self.sleep(3)
                return
        else:
            self.sleep(remaining)
        self.log(t("log_timeout_end"))
        self.press("end_button", timeout=3)
        self.press("end_confirm", timeout=3, wait_after=3)
        self.press("return_home", timeout=15, wait_after=3)

    def human_wait(self, seconds):
        """انتظار بمدة متغيرة قليلاً كل مرة، فلا يتكرر الإيقاع نفسه بين الهجمات."""
        self.sleep(seconds * random.uniform(0.8, 1.5))

    # ---------- التعافي من التجمّد ----------
    def restart_game(self):
        package = self.cfg.get("package", "com.supercell.clashofclans")
        self.adb.stop_app(package)
        self.sleep(3)
        self.adb.start_app(package)
        self.sleep(self.cfg["farm"].get("game_boot_seconds", 35))
        self.watchdog.reset()

    def reboot_emulator(self):
        if not self.adb.reboot_emulator():
            return False
        self.sleep(self.cfg["farm"].get("emulator_boot_seconds", 70))
        for _ in range(10):
            if self.adb.connect()[0] and self.adb._adb.screenshot() is not None:
                break
            self.sleep(10)
        self.adb.start_app(self.cfg.get("package", "com.supercell.clashofclans"))
        self.sleep(self.cfg["farm"].get("game_boot_seconds", 35))
        self.watchdog.reset()
        return True

    def recover_frozen(self, reason, restarts):
        """يرجع False إن يجب إيقاف البوت."""
        self.stats["restarts"] = self.stats.get("restarts", 0) + 1
        self.on_stats(self.stats)
        self.log(t("log_frozen_" + reason, s=self.cfg["farm"].get("freeze_seconds", 60)))
        if restarts > MAX_RESTARTS_IN_ROW:
            self.log(t("log_frozen_give_up"))
            self.notifier.send(t("notify_frozen") + "\n" + self.summary(), "error")
            return False
        if restarts > RESTARTS_BEFORE_REBOOT:
            self.log(t("log_emulator_reboot"))
            if self.reboot_emulator():
                return True
        self.log(t("log_game_kill"))
        self.restart_game()
        return True

    def one_attack(self):
        self.log(t("log_attack"))
        self.watchdog.start_attack()
        self.prepare()
        self.press("attack", timeout=10)
        self.press("find_a_match", timeout=10)
        self.press("attack_button", timeout=8, wait_after=2)
        # لا إنزال قبل التأكد من شاشة المعركة، وإلا ستقع النقرات على أزرار القرية
        if self.tpl.exists("next_button") or self.tpl.exists("end_button"):
            found, _ = self.wait_any(["next_button", "end_button"], self.cfg["farm"].get("battle_wait", 45))
            if not found:
                raise AttackAborted(t("log_no_battle"))
        else:
            self.sleep(8)
        self.zoom_out()
        self.search_base()
        self.last_gains = {}
        # لقطة جديدة بعد اختيار القرية: الشريط يظهر كاملاً ولا تغطيه رسائل البحث
        if not self.deploy_strategy(self.adb.screenshot()):
            # لا جيش في الشريط: ننهي المعركة قبل الإنزال (بلا خسارة) بدل البقاء عالقين في البحث
            self.press("end_button", timeout=3)
            self.press("end_confirm", timeout=3)
            self.press("return_home", timeout=10, wait_after=3)
            raise AttackAborted(t("log_no_army"))
        self.finish_battle(time.time())
        self.watchdog.end_attack()
        self.finish_attack("log_attack_done")

    def finish_attack(self, key):
        self.stats["attacks"] += 1
        gains = {k: v for k, v in (getattr(self, "last_gains", None) or {}).items() if v is not None}
        for k, v in gains.items():
            self.stats[k] = self.stats.get(k, 0) + v
        self.stats["history"].append({"time": time.time(), "village": self.village, **gains})
        self.on_stats(self.stats)
        self.log(t(key, n=self.stats["attacks"]))
        if gains:
            gold = gains.get("gold", gains.get("bb_gold", 0))
            self.log(t("log_gains", g=gold, e=gains.get("elixir", 0), d=gains.get("dark", 0)))
        every = self.cfg.get("notify", {}).get("every", 1) or 1
        if self.stats["attacks"] % every == 0:
            self.notifier.send(self.summary(), "attack")
        self.human_wait(self.cfg["farm"].get("home_wait", 5))

    def summary(self):
        s = self.stats
        mins = max(1, int((time.time() - s["started"]) / 60))
        return t("notify_summary", n=s["attacks"], g=s.get("gold", 0), e=s.get("elixir", 0),
                 d=s.get("dark", 0), m=mins, err=s.get("errors", 0))

    # ---------- الحلقة الرئيسية ----------
    @staticmethod
    def _between(a, b):
        """رقم عشوائي بين حدّين حتى لو أُدخل الأكبر أولاً في الإعدادات."""
        a, b = int(a), int(b)
        return random.randint(min(a, b), max(a, b))

    def run(self):
        try:
            self._run()
        except Exception as e:  # أي خطأ غير متوقع يظهر في السجل بدل أن يتوقف البوت بصمت
            self.log(t("log_crash", e=f"{type(e).__name__}: {e}"))

    def _run(self):
        f = self.cfg["farm"]
        br = self.cfg["breaks"]
        next_break = self._between(br["attacks_min"], br["attacks_max"]) if br.get("enabled") else 0
        done_since_break = 0
        errors_in_row = 0
        restarts_in_row = 0
        try:
            while True:
                limit = f.get("max_attacks", 0)
                if limit and self.stats["attacks"] >= limit:
                    self.log(t("log_target"))
                    break
                try:
                    self.one_attack()
                    errors_in_row = restarts_in_row = 0
                except Stopped:
                    raise
                except GameFrozen as e:  # تجمّد: نغلق اللعبة ونشغّلها بدل الانتظار للأبد
                    self.watchdog.end_attack()
                    restarts_in_row += 1
                    if not self.recover_frozen(str(e), restarts_in_row):
                        break
                    continue
                except Exception as e:  # نتعافى بدل إيقاف البوت كله
                    errors_in_row += 1
                    self.stats["errors"] += 1
                    self.on_stats(self.stats)
                    self.log(t("log_error", e=e, n=errors_in_row, max=MAX_ERRORS_IN_ROW))
                    if errors_in_row >= MAX_ERRORS_IN_ROW:
                        self.log(t("log_too_many"))
                        self.notifier.send(t("notify_error", e=e) + "\n" + self.summary(), "error")
                        break
                    if errors_in_row == ERRORS_BEFORE_RESTART:  # لعبة جديدة قبل الإيقاف، بعدد محدود من المرات
                        restarts_in_row += 1
                        if not self.recover_frozen("errors", restarts_in_row):
                            break
                        errors_in_row = 0
                        continue
                    self.sleep(f.get("error_wait", 5))
                    continue
                done_since_break += 1
                if br.get("enabled") and done_since_break >= next_break:
                    mins = self._between(br["minutes_min"], br["minutes_max"])
                    self.log(t("log_break", m=mins))
                    self.sleep(mins * 60)
                    done_since_break = 0
                    next_break = self._between(br["attacks_min"], br["attacks_max"])
        except Stopped:
            self.log(t("log_stopped"))
            if self.stats["attacks"]:
                self.notifier.send(t("notify_stopped") + "\n" + self.summary(), "stop")
