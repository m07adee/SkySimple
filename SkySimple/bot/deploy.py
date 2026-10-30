"""تنفيذ الاستراتيجيات: إنزال كل خانة حتى تفرغ، وتوقيت الأبطال والتعويذات."""
import time

from . import strategy as st
from .army import is_empty
from .i18n import embed, t

MAX_TAPS_PER_SLOT = 60


def safe_point(p):
    """نستبعد النقاط الواقعة تحت شريط الجيش أو أزرار إنهاء المعركة والتالي."""
    x, y = p
    if y >= 735 or (x < 215 and y > 630) or (x > 1320 and y > 575):
        return False
    return True


class StrategyDeployer:
    """يُدمج مع Farmer: يعتمد على self.tap و self.sleep و self.adb و self.cfg و self.log."""

    def strategy_ready(self):
        a = self.cfg.get("attack", {})
        return a.get("strategy", "custom") != "custom" and bool(a.get("slots"))

    def _points(self, edges, n, spread):
        pts = []
        per = max(2, n // len(edges) + 1)
        for e in edges:
            pts += [p for p in st.edge_points(self.cfg["attack"]["area"], e, per, spread) if safe_point(p)]
        return pts or [st.edge_mid(self.cfg["attack"]["area"], edges[0])]

    def _drain(self, x, pts, interleave=False, max_taps=MAX_TAPS_PER_SLOT, check_every=3):
        """يختار الخانة ثم ينقر نقاط الإنزال بالتناوب حتى تفرغ (أو تنتهي المحاولات)."""
        self.tap(x, 815)
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
        a = self.cfg["attack"]
        area = a["area"]
        found = self.army_book.locate(screen, a["slots"])
        if not found:
            return False
        prof, edges = st.plan(a["strategy"], a.get("method", "auto"), a.get("side", "auto"),
                              screen, area, self.stats["attacks"])
        self.log(t("log_strategy", name=t("strat_" + a["strategy"]),
                   sides=", ".join(t("side_" + e) for e in edges)))
        by_type = {"troop": [], "siege": [], "hero": [], "spell": []}
        for s in a["slots"]:
            if s["id"] in found and s.get("enabled", True):
                by_type.setdefault(s.get("type", "troop"), []).append((s, found[s["id"]][0]))

        start = time.time()
        troop_pts = self._points(edges, 10, prof["spread"])
        for s, x in by_type["troop"]:
            n = self._drain(x, troop_pts, interleave=a["strategy"] == "goblins")
            self.log(t("log_deploy", name=embed(s.get("label") or s["id"]), qty=n))
        for s, x in by_type["siege"]:
            self.tap(x, 815)
            self.tap(*st.edge_mid(area, edges[0]))

        heroes = by_type["hero"]
        if heroes:
            self.sleep(max(0, prof["hero_delay"] - (time.time() - start)))
            hero_pts = self._points(edges, len(heroes), prof["spread"] * 0.6)
            for i, (s, x) in enumerate(heroes):
                self.tap(x, 815)
                self.tap(*hero_pts[i % len(hero_pts)])
        heroes_at = time.time()

        spells = by_type["spell"]
        if spells:
            self.sleep(max(0, prof["spell_delay"] - (time.time() - start)))
            for s, x in spells:
                kind = s.get("spell", "rage")
                frac = prof["spell_frac"].get(kind, 0.45)
                targets = [st.toward_center(area, st.edge_mid(area, e), frac) for e in edges]
                if kind in ("rage", "haste", "heal"):
                    # تعويذات متتالية على المسار نحو المركز
                    targets = [st.toward_center(area, st.edge_mid(area, edges[0]), frac + 0.1 * k)
                               for k in range(3)] + targets[1:]
                self._drain(x, targets, max_taps=12, check_every=2)
        self.log(t("log_deployed"))

        # قدرات الأبطال
        if heroes:
            self.sleep(max(0, self.cfg["farm"].get("ability_after", 8) - (time.time() - heroes_at)))
            self.log(t("log_abilities"))
            for s, x in heroes:
                self.tap(x, 815)

        # تحقق أخير: جنود بقوا لأن النقرات وقعت في منطقة ممنوعة → ننزلهم عند أطراف الخريطة
        check = self.adb.screenshot()
        left = [(s, x) for s, x in by_type["troop"] if not is_empty(check, x)]
        if left:
            corners = [p for p in (area["left"], area["top"], area["right"]) if safe_point(p)]
            for s, x in left:
                self._drain(x, [tuple(p) for p in corners], max_taps=20)
        return True
