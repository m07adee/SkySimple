"""تحميل وحفظ الإعدادات (config.json) مع قيم افتراضية لدقة 1600×900."""
import copy
import json
import os

DEFAULTS = {
    "adb": {"path": "auto", "serial": "127.0.0.1:5555"},
    "package": "com.supercell.clashofclans",
    "buttons": {
        # مقاسة من اللعبة على LDPlayer بدقة 1600×900
        "attack": {"x": 105, "y": 802},
        "find_a_match": {"x": 274, "y": 667},
        "attack_button": {"x": 1415, "y": 802},
        "next_button": {"x": 1458, "y": 640},
        "end_button": {"x": 115, "y": 670},
        "end_confirm": {"x": 960, "y": 600},
        "return_home": {"x": 800, "y": 775},
        "reload_game": {"x": 492, "y": 527},
        "boat_to_builder": {"x": 393, "y": 714},
        "bb_attack": {"x": 105, "y": 805},
        "bb_find_now": {"x": 1190, "y": 592},
        "bb_return_home": {"x": 800, "y": 761},
        "bb_cart_collect": {"x": 1176, "y": 758},
    },
    "collect": {"resources": True, "elixir_cart": True, "every": 1},
    "clan": {"request": False, "request_every_min": 30},
    # الجيش يُقرأ من الشريط في كل معركة، ومنطقة الإنزال ثابتة بعد التصغير: لا معايرة
    "attack": {
        "strategy": "smart",    # smart (أي جيش) / edrag / dragons / goblins
        "method": "auto",       # auto (حسب الاستراتيجية) / one_side / two_sides / three_sides / all_sides
        "side": "auto",         # auto (حسب كثافة المباني) / rotate / top_left / top_right / bottom_right / bottom_left
    },
    "notify": {"enabled": False, "discord_webhook": "", "telegram_token": "", "telegram_chat": "",
               "every": 5, "on_attack": True, "on_error": True, "on_stop": True},
    "mode": "home",  # home = القرية الرئيسية، builder = القرية الليلية
    "builder": {
        "troop_slots": 6,          # عدد خانات الجنود في المرحلة الأولى
        "reinforcement_slots": 2,  # خانات التعزيز في المرحلة الثانية
        "use_hero": True,
        "hero_x": 160,
        "slot_y": 815,
        "first_slot_x": 303,
        "slot_step": 126.7,
        "ability_after": 6,
        "stage1_point": [165, 480],
        "stage2_point": [260, 560],
        "stage_seconds": 200,
        "end_button": [115, 625],
    },
    "lang": "ar",
    "appearance": "dark",
    "farm": {
        "click_delay": 0.15,
        "click_jitter": 4,
        "match_threshold": 0.8,
        "search_wait": 4,
        "max_skips": 30,
        "battle_seconds": 200,  # المعركة 3 دقائق بعد الإنزال
        "ability_after": 8,
        "zoom_out": True,
        "game_boot_seconds": 35,
        "home_wait": 5,
        "max_attacks": 0,
    },
    "loot": {
        "enabled": False,
        "min_gold": 800000,
        "min_elixir": 800000,
        "min_dark": 5000,
        "regions": {"gold": [82, 110, 140, 38], "elixir": [82, 157, 140, 38], "dark": [82, 204, 120, 38]},
    },
    "breaks": {"enabled": False, "attacks_min": 15, "attacks_max": 25, "minutes_min": 10, "minutes_max": 20},
}


def _merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(path):
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                _merge(cfg, json.load(f))
        except (ValueError, OSError):
            pass  # ملف تالف: نبدأ بالقيم الافتراضية بدل الانهيار
    # الإصدارات القديمة: خانات يدوية ومعايرة ومسح جيش لم تعد مستخدمة
    for key in ("army", "deploy_line"):
        cfg.pop(key, None)
    for key in ("area", "slots", "army_dir"):
        cfg["attack"].pop(key, None)
    if cfg["attack"].get("strategy") not in ("smart", "edrag", "dragons", "goblins"):
        cfg["attack"]["strategy"] = "smart"
    return cfg


def save(path, cfg):
    # الكتابة في ملف مؤقت ثم الاستبدال، حتى لا يتلف الملف إذا أُغلق البرنامج أثناء الحفظ
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
