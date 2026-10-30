"""إشعارات Discord (Webhook) و Telegram (Bot API). ترسل في الخلفية ولا تعطّل البوت عند الفشل."""
import json
import threading
import urllib.parse
import urllib.request


def _post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def send_discord(webhook, text):
    body = json.dumps({"content": text[:1900], "username": "Sky Simple"}).encode()
    return _post(webhook, body, {"Content-Type": "application/json", "User-Agent": "SkySimple"})


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000]}).encode()
    return _post(url, body, {"Content-Type": "application/x-www-form-urlencoded"})


class Notifier:
    def __init__(self, cfg, log=None):
        self.cfg = cfg
        self.log = log or (lambda m: None)

    def conf(self):
        return self.cfg.get("notify", {})

    def enabled(self, event):
        c = self.conf()
        return c.get("enabled") and c.get("on_" + event, True)

    def send(self, text, event="attack", wait=False):
        """يرسل لكل قناة مفعّلة. wait=True للاختبار من الواجهة (يرجع قائمة النتائج)."""
        c = self.conf()
        jobs = []
        if c.get("discord_webhook"):
            jobs.append(("Discord", lambda: send_discord(c["discord_webhook"], text)))
        if c.get("telegram_token") and c.get("telegram_chat"):
            jobs.append(("Telegram", lambda: send_telegram(c["telegram_token"], c["telegram_chat"], text)))

        def run():
            results = []
            for name, job in jobs:
                try:
                    results.append((name, job()))
                except Exception as e:  # الشبكة أو الإعدادات: نسجل ولا نوقف البوت
                    results.append((name, str(e)))
                    self.log(f"🔔 {name}: {e}")
            return results

        if wait:
            return run()
        if event == "test" or self.enabled(event):
            threading.Thread(target=run, daemon=True).start()
        return None
