# SkySimple — سكاي البسيط

بوت Clash of Clans على محاكي LDPlayer (القرية الرئيسية والليلية) بواجهة عربية وإنجليزية، مع نظام مفاتيح تفعيل.

| المجلد | المحتوى |
|---|---|
| [`SkySimple/`](SkySimple/) | البوت: الواجهة (`app.py`) والمنطق (`bot/`) وقوالب الأزرار. التفاصيل في [README](SkySimple/README.md) |
| [`SkyAdmin/`](SkyAdmin/) | لوحة المفاتيح: إنشاء مفاتيح التفعيل وإدارتها على Supabase، وكود قاعدة البيانات `setup.sql` |

## التشغيل من الكود
```bash
cd SkySimple
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```
تشغيل البوت من الكود لا يطلب تفعيلاً (إلا إذا وُضع `license_server.json` بجانب `app.py`). النسخة المجمّعة تطلب مفتاحاً.

لوحة المفاتيح:
```bash
SkySimple\.venv\Scripts\python SkyAdmin\admin.py
```

## البناء (PyInstaller)
```bash
cd SkySimple
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name SkySimple --icon assets\icon.ico --add-data "assets;assets" --collect-data customtkinter app.py
```

> استخدام البوتات يخالف شروط Supercell وقد يؤدي إلى حظر الحساب.
