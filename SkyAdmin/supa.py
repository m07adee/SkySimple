"""اتصال لوحة التحكم بقاعدة Supabase (بالمفتاح السري)."""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بلا O/0 و I/1 حتى لا تختلط


class SupaError(Exception):
    pass


def new_key():
    return "SKY-" + "-".join("".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(4))


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def status_of(row, now=None):
    """unused / active / expired / revoked"""
    if row.get("status") == "revoked":
        return "revoked"
    if not row.get("hwid"):
        return "unused"
    exp = parse_time(row.get("expires_at"))
    return "expired" if exp and exp <= (now or datetime.now(timezone.utc)) else "active"


def _headers(key):
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):  # مفاتيح Supabase القديمة (JWT)
        h["Authorization"] = "Bearer " + key
    return h


class Supa:
    def __init__(self, url, secret):
        self.url = url.strip().rstrip("/")
        self.secret = secret.strip()

    def _req(self, method, path, body=None, prefer=None, key=None):
        headers = _headers(key or self.secret)
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except (ValueError, AttributeError):
                pass
            raise SupaError(f"HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            raise SupaError(str(getattr(e, "reason", e))) from None
        return json.loads(raw) if raw.strip() else None

    @staticmethod
    def _eq(key):
        return "key=eq." + urllib.parse.quote(key, safe="")

    def list(self):
        return self._req("GET", "/rest/v1/licenses?select=*&order=created_at.desc")

    def create(self, count, days, note):
        rows = [{"key": new_key(), "duration_days": int(days), "note": note} for _ in range(int(count))]
        return self._req("POST", "/rest/v1/licenses", rows, prefer="return=representation")

    def update(self, key, fields):
        return self._req("PATCH", "/rest/v1/licenses?" + self._eq(key), fields, prefer="return=representation")

    def delete(self, key):
        return self._req("DELETE", "/rest/v1/licenses?" + self._eq(key))

    def extend(self, key, days):
        return self._req("POST", "/rest/v1/rpc/admin_extend", {"p_key": key, "p_days": int(days)})

    def check_public(self, anon_key):
        """يتحقق أن المفتاح العام يستطيع استدعاء دالة التفعيل (كما يفعل برنامج العميل)."""
        return self._req("POST", "/rest/v1/rpc/activate_license",
                         {"p_key": "SKY-TEST", "p_hwid": "0" * 32, "p_version": "admin"}, key=anon_key)
