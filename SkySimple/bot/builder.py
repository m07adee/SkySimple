"""حلقة الهجوم التلقائي في القرية الليلية (قاعدة البنّاء) بمرحلتيها."""
import time

from .farm import BB_RESULT_REGIONS, AttackAborted, Farmer
from .i18n import t


class BuilderFarmer(Farmer):
    village = "builder"

    def bcfg(self):
        return self.cfg["builder"]

    def slot_x(self, index):
        """موقع خانة الجندي رقم index (يبدأ من 1) في شريط المعركة."""
        b = self.bcfg()
        return int(b["first_slot_x"] + b["slot_step"] * (index - 1))

    def deploy(self, slots, point):
        b = self.bcfg()
        y = b["slot_y"]
        if b.get("use_hero", True):
            self.tap(b["hero_x"], y)
            self.tap(*point)
        for i in slots:
            self.tap(self.slot_x(i), y)
            self.tap(*point)
        self.deployed_at = time.time()
        self.ability_used = False

    def maybe_ability(self):
        b = self.bcfg()
        if (b.get("use_hero", True) and not self.ability_used
                and time.time() - self.deployed_at >= b.get("ability_after", 6)):
            self.tap(b["hero_x"], b["slot_y"])
            self.ability_used = True
            self.log(t("log_abilities"))

    def one_attack(self):
        b = self.bcfg()
        self.log(t("log_bb_attack"))
        self.watchdog.start_attack()
        self.last_gains = {}
        self.prepare()
        self.press("bb_attack", timeout=10, wait_after=2)
        self.press("bb_find_now", timeout=10, wait_after=1)

        # لا إنزال قبل ظهور ساحة المعركة
        if self.tpl.exists("bb_battle_starts"):
            if not self.wait_for("bb_battle_starts", self.cfg["farm"].get("battle_wait", 45) + 15):
                raise AttackAborted(t("log_no_battle"))
        else:
            self.sleep(8)

        troops = int(b["troop_slots"])
        self.log(t("log_stage1", n=troops))
        self.deploy(range(1, troops + 1), b["stage1_point"])

        stage = 1
        deadline = time.time() + b.get("stage_seconds", 200)
        while True:
            self.sleep(2)
            self.maybe_ability()
            screen = self.adb.screenshot()
            pos = self.find_now("bb_return_home", screen)
            if pos:
                self.log(t("log_battle_over"))
                self.last_gains = self.read_stable_loot(BB_RESULT_REGIONS, "bb_return_home")
                self.tap(*pos)
                break
            # المهلة تمنع الخلط مع عدّاد المرحلة الأولى الذي يبقى لحظات بعد الإنزال
            if (stage == 1 and time.time() - self.deployed_at > 10
                    and self.find_now("bb_battle_starts", screen)):
                stage = 2
                extra = int(b.get("reinforcement_slots", 0))
                self.log(t("log_stage2", n=extra))
                self.deploy(range(troops + 1, troops + extra + 1), b["stage2_point"])
                deadline = time.time() + b.get("stage_seconds", 200)
            if time.time() > deadline:
                self.log(t("log_timeout_end"))
                self.tap(*b["end_button"])
                self.sleep(2)
                self.press("end_confirm", timeout=3, wait_after=3)
                self.press("bb_return_home", timeout=15, wait_after=3)
                break

        self.watchdog.end_attack()
        self.finish_attack("log_bb_done")
