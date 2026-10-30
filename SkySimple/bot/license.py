"""تفعيل الاشتراك: كل مفتاح يُربط بأول جهاز يفعّله، ويُتحقق منه عند خادم Supabase."""
import ctypes
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# لوحة التحكم تلصق عنوان الخادم في نهاية SkySimple.exe بين هاتين العلامتين
MARKER = b"SKYLIC1"
END = b"SKYEND"
TAIL = 16384


def read_stamp(path):
    """يقرأ إعدادات الخادم الملصقة في نهاية الملف التنفيذي، أو None."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL))
            tail = f.read()
    except OSError:
        return None
    if not tail.endswith(END):
        return None
    i = tail.rfind(MARKER)
    if i < 0:
        return None
    try:
        data = json.loads(tail[i + len(MARKER):-len(END)].decode("utf-8"))
    except ValueError:
        return None
    return data if data.get("url") and data.get("key") else None


def write_stamp(src, dst, url, key):
    """ينسخ src إلى dst مع إعدادات الخادم (يستبدل أي إعدادات سابقة)."""
    with open(src, "rb") as f:
        data = f.read()
    if data.endswith(END):
        i = data.rfind(MARKER, max(0, len(data) - TAIL))
        if i >= 0:
            data = data[:i]
    payload = json.dumps({"url": url.rstrip("/"), "key": key}, separators=(",", ":")).encode("utf-8")
    with open(dst, "wb") as f:
        f.write(data + MARKER + payload + END)


def server_config(base):
    """في النسخة المجمّعة من الملف التنفيذي نفسه، وأثناء التطوير من license_server.json."""
    if getattr(sys, "frozen", False):
        return read_stamp(sys.executable)
    path = os.path.join(base, "license_server.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _reg(path, name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def _volume_serial():
    try:
        serial = ctypes.c_uint32()
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        ok = ctypes.windll.kernel32.GetVolumeInformationW(drive, None, 0, ctypes.byref(serial),
                                                           None, None, None, 0)
        return f"{serial.value:08X}" if ok else ""
    except (AttributeError, OSError):
        return ""


def machine_id():
    """بصمة ثابتة للجهاز: معرّف ويندوز + اللوحة الأم + قرص النظام. لا تتغير مع الإنترنت أو الراوتر."""
    bios = r"HARDWARE\DESCRIPTION\System\BIOS"
    parts = [_reg(r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"),
             _reg(bios, "SystemManufacturer"), _reg(bios, "SystemProductName"),
             _reg(bios, "BaseBoardProduct"), _volume_serial()]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32].upper()


def short_id(hwid):
    return "-".join(hwid[i:i + 4] for i in range(0, 16, 4))


def _parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


class Result:
    def __init__(self, ok, error="", expires_at=None, server_time=None):
        self.ok = ok
        self.error = error            # invalid / revoked / other_device / expired / network / server
        self.expires_at = expires_at  # بتوقيت UTC
        self.server_time = server_time

    def days_left(self):
        if not (self.expires_at and self.server_time):
            return 0
        return max(0.0, (self.expires_at - self.server_time).total_seconds() / 86400)

    def expires_local(self):
        return self.expires_at.astimezone().strftime("%Y-%m-%d %H:%M") if self.expires_at else ""

    @property
    def final(self):
        """خطأ نهائي يوقف البرنامج (لا خطأ إنترنت مؤقت)."""
        return not self.ok and self.error not in ("network", "server")


class LicenseClient:
    def __init__(self, server, version="", store_dir=None):
        self.url = server["url"].rstrip("/")
        self.anon = server["key"]
        self.version = version
        self.hwid = machine_id()
        self.store = os.path.join(store_dir or os.path.join(os.environ.get("APPDATA", "."), "SkySimple"),
                                  "license.json")

    def saved_key(self):
        try:
            with open(self.store, encoding="utf-8") as f:
                return json.load(f).get("key", "")
        except (OSError, ValueError):
            return ""

    def save_key(self, key):
        os.makedirs(os.path.dirname(self.store), exist_ok=True)
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump({"key": key}, f)

    def forget(self):
        try:
            os.remove(self.store)
        except OSError:
            pass

    def check(self, key):
        body = json.dumps({"p_key": key.strip().upper(), "p_hwid": self.hwid,
                           "p_version": self.version}).encode("utf-8")
        headers = {"apikey": self.anon, "Content-Type": "application/json"}
        if self.anon.startswith("eyJ"):  # مفاتيح Supabase القديمة (JWT) تُرسل أيضاً في Authorization
            headers["Authorization"] = "Bearer " + self.anon
        req = urllib.request.Request(self.url + "/rest/v1/rpc/activate_license", data=body,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return Result(False, "server")
        except (urllib.error.URLError, OSError, ValueError):
            return Result(False, "network")
        if not isinstance(data, dict):
            return Result(False, "server")
        return Result(bool(data.get("ok")), data.get("error", ""),
                      _parse_time(data.get("expires_at")), _parse_time(data.get("server_time")))
