"""التحكم بالمحاكي (LDPlayer) عبر ADB: اتصال، لقطة شاشة، نقر، تشغيل اللعبة."""
import os
import shutil
import subprocess

import cv2
import numpy as np

LDPLAYER_DIRS = [
    r"C:\LDPlayer\LDPlayer9",
    r"C:\LDPlayer\LDPlayer4.0",
    r"D:\LDPlayer\LDPlayer9",
    r"C:\Program Files\LDPlayer\LDPlayer9",
    r"C:\Program Files (x86)\LDPlayer\LDPlayer9",
]

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_adb(configured="auto"):
    if configured and configured != "auto" and os.path.isfile(configured):
        return configured
    for d in LDPLAYER_DIRS:
        p = os.path.join(d, "adb.exe")
        if os.path.isfile(p):
            return p
    return shutil.which("adb")


def ldplayer_instances():
    """نسخ LDPlayer المثبتة: [(الرقم، الاسم، يعمل؟، عنوان ADB)]. منفذ ADB = 5555 + 2 × الرقم."""
    for d in LDPLAYER_DIRS:
        exe = os.path.join(d, "ldconsole.exe")
        if not os.path.isfile(exe):
            continue
        try:
            out = subprocess.run([exe, "list2"], capture_output=True, timeout=15,
                                 creationflags=NO_WINDOW).stdout.decode(errors="ignore")
        except (subprocess.TimeoutExpired, OSError):
            return []
        rows = []
        for line in out.splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 5 and parts[0].isdigit():
                i = int(parts[0])
                rows.append((i, parts[1], parts[4] == "1", f"127.0.0.1:{5555 + 2 * i}"))
        return rows
    return []


class ADB:
    def __init__(self, adb_path, serial):
        self.adb = adb_path
        self.serial = serial

    def _exec(self, cmd, timeout):
        """ينفذ الأمر ويرجع المخرجات، أو None عند انتهاء المهلة أو تعذر التشغيل."""
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                 creationflags=NO_WINDOW)
            return out.stdout
        except (subprocess.TimeoutExpired, OSError):
            return None

    def _run(self, *args, timeout=15, binary=False):
        data = self._exec([self.adb, "-s", self.serial, *args], timeout)
        if binary:
            return data or b""
        return (data or b"").decode(errors="ignore").strip()

    def connect(self):
        data = self._exec([self.adb, "connect", self.serial], 15)
        text = (data or b"").decode(errors="ignore").strip()
        return "connected" in text, text

    def screenshot(self):
        """يرجع صورة BGR (numpy) أو None. الصيغة الخام أسرع بمرتين ونصف من PNG."""
        data = self._run("exec-out", "screencap", binary=True, timeout=20)
        if len(data) > 16:
            w, h = np.frombuffer(data[:8], np.uint32)
            size = int(w) * int(h) * 4
            if 0 < size <= len(data) - 12:
                pixels = np.frombuffer(data[len(data) - size:], np.uint8).reshape(int(h), int(w), 4)
                return cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGR)
        data = self._run("exec-out", "screencap", "-p", binary=True, timeout=20)
        if not data:
            return None
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    def tap(self, x, y):
        self._run("shell", "input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1, y1, x2, y2, ms=300):
        self._run("shell", "input", "swipe", str(int(x1)), str(int(y1)),
                  str(int(x2)), str(int(y2)), str(ms))

    def back(self):
        self._run("shell", "input", "keyevent", "4")

    def start_app(self, package):
        self._run("shell", "monkey", "-p", package, "-c",
                  "android.intent.category.LAUNCHER", "1")

    def stop_app(self, package):
        self._run("shell", "am", "force-stop", package)

    def current_app(self):
        return self._run("shell", "dumpsys window | grep mCurrentFocus")

    def is_app_running(self, package):
        return package in self.current_app()
