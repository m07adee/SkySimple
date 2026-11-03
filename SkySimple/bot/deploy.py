"""تنفيذ الاستراتيجيات: إنزال كل خانة حتى تفرغ، وتوقيت الأبطال والتعويذات."""
import time

from . import strategy as st
from .army import is_empty, read_bar
from .i18n import t

MAX_TAPS_PER_SLOT = 60
SLOT_Y = 815  # منتصف شريط الجيش عمودياً


def safe_point(p):
    """نستبعد النقاط الواقعة تحت شريط الجيش أو أزرار إنهاء المعركة والتالي."""
    x, y = p
    if y >= 735 or (x < 215 and y > 630) or (x > 1320 and y > 575):
        return False
    return True


class StrategyDeployer:
    """يُدمج مع Farmer: يعتمد على self.tap و self.sleep و self.adb و self.cfg و self.log."""

    def _points(self, area, edges, n, spread):
        pts = []
        per = max(2, n // len(edges) + 1)
        for e in edges:
            pts += [p for p in st.edge_points(area, e, per, spread) if safe_point(p)]
        return pts or [st.edge_mid(area, edges[0])]

    def _drain(self, x, pts, interleave=False, max_taps=MAX_TAPS_PER_SLOT, check_every=3):
        """يختار الخانة ثم ينقر نقاط الإنزال بالتناوب حتى تفرغ (أو تنتهي المحاولات)."""
        self.tap(x, SLOT_Y)
        order = pts
        if interleave and len(pts) > 2:
            # العفاريت: نقطة من كل جهة بالتناوب حتى تتوزع المجموعات
            half = len(pts) // 2
            order = [p for pair in zip(pts[:half], pts[half:]) for p in pair] + pts[2 * half:]
        taps = 0
        while taps < max_taps:
            for p in order:
                self.tap(*p)
                taps += 1
                if taps % check_every == 0:
                    if is_empty(self.adb.screenshot(), x):
                        return taps
                if taps >= max_taps:
                    break
        return taps

    def deploy_strategy(self, screen):
        """ينزل الجيش كما يظهر في الشريط الآن. يرجع False إن لم يجد أي خانة."""
        a = self.cfg["attack"]
        slots = read_bar(screen)
        if not slots:
            return False
        area = st.DEFAULT_AREA
        name = a.get("strategy", "smart")
        prof, edges = st.plan(name, a.get("method", "auto"), a.get("side", "auto"),
                              screen, area, self.stats["attacks"])
        by_type = {"troop": [], "siege": [], "hero": [], "spell": []}
        for s in slots:
            by_type[s["type"]].append(s["x"])
        self.log(t("log_army", troops=len(by_type["troop"]), siege=len(by_type["siege"]),
                   heroes=len(by_type["hero"]), spells=len(by_type["spell"])))
        self.log(t("log_strategy", name=t("strat_" + name),
                   sides=", ".join(t("side_" + e) for e in edges)))

        start = time.time()
        troop_pts = self._points(area, edges, 10, prof["spread"])
        for i, x in enumerate(by_type["troop"]):
            n = self._drain(x, troop_pts, interleave=name == "goblins")
            self.log(t("log_deploy", name=t("type_troop") + f" {i + 1}", qty=n))
        for x in by_type["siege"]:
            self.tap(x, SLOT_Y)
            self.tap(*st.edge_mid(area, edges[0]))

        heroes = by_type["hero"]
        if heroes:
            self.sleep(max(0, prof["hero_delay"] - (time.time() - start)))
            hero_pts = self._points(area, edges, len(heroes), prof["spread"] * 0.6)
            for i, x in enumerate(heroes):
                self.tap(x, SLOT_Y)
                self.tap(*hero_pts[i % len(hero_pts)])
        heroes_at = time.time()

        spells = by_type["spell"]
        if spells:
            self.sleep(max(0, prof["spell_delay"] - (time.time() - start)))
            # على مسار الهجوم نحو المركز: كل تعويذة أعمق قليلاً من السابقة
            path = st.edge_mid(area, edges[0])
            for i, x in enumerate(spells):
                frac = prof["spell_frac"] + 0.1 * (i % 3)
                targets = [st.toward_center(area, path, frac)] + \
                          [st.toward_center(area, st.edge_mid(area, e), frac) for e in edges[1:]]
                self._drain(x, targets, max_taps=12, check_every=2)
        self.log(t("log_deployed"))

        # قدرات الأبطال
        if heroes:
            self.sleep(max(0, self.cfg["farm"].get("ability_after", 8) - (time.time() - heroes_at)))
            self.log(t("log_abilities"))
            for x in heroes:
                self.tap(x, SLOT_Y)

        # تحقق أخير: جنود بقوا لأن النقرات وقعت في منطقة ممنوعة → ننزلهم عند أطراف الخريطة
        check = self.adb.screenshot()
        left = [x for x in by_type["troop"] if not is_empty(check, x)]
        if left:
            corners = [tuple(p) for p in (area["left"], area["top"], area["right"]) if safe_point(p)]
            for x in left:
                self._drain(x, corners, max_taps=20)
        return True
