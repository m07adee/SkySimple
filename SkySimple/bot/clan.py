"""طلب تعزيزات قلعة الكلان من نافذة الدردشة (يُدمج مع Farmer)."""
import time

from .i18n import t


class ClanMixin:
    _last_request = 0.0

    def clan_request(self):
        """يفتح الدردشة، ويرسل طلب التعزيزات إن كان الزر متاحاً، ثم يغلق الدردشة. يرجع True عند الإرسال."""
        c = self.cfg.get("clan", {})
        if not c.get("request"):
            return False
        if time.time() - self._last_request < c.get("request_every_min", 30) * 60:
            return False
        if not (self.tpl.exists("clan_chat_btn") and self.tpl.exists("clan_request_btn")):
            return False
        pos = self.wait_for("clan_chat_btn", 3)
        if not pos:
            return False
        self.tap(*pos)
        sent = False
        try:
            btn = self.wait_for("clan_request_btn", 4)
            if not btn:
                # لا زر طلب: القلعة ممتلئة أو الطلب السابق ما زال قائماً
                self.log(t("log_request_unavailable"))
                self._last_request = time.time()
                return False
            self.tap(*btn)
            if not self.wait_for("clan_request_title", 4):
                return False
            send = self.wait_for("clan_send", 3)
            if send:
                self.tap(*send)
                self.sleep(1.5)
                sent = True
                self._last_request = time.time()
                self.stats["requests"] = self.stats.get("requests", 0) + 1
                self.log(t("log_request_sent"))
            else:
                self.adb.back()
        finally:
            self.sleep(0.8)
            close = self.find_now("clan_chat_close", self.adb.screenshot())
            if close:
                self.tap(*close)
            elif self.find_now("clan_request_title", self.adb.screenshot()):
                self.adb.back()
            self.sleep(1)
        return sent
