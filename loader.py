"""Загрузчик модулей. Любой файл mod_<имя>.py рядом с userbot.py подхватывается сам.

В модуле можно задать (всё необязательно):
  NAME      — красивое название
  ORDER     — порядок в .help (меньше = выше)
  HELP      — текст для .help
  on_load() — async, вызывается после загрузки
  on_unload() — async, вызывается при выгрузке
  status()  — строка для .ping
"""
import glob
import importlib
import os
import sys

import core
from core import *
from config import config, save_config

MODULES = {}  # ключ -> {"mod": модуль, "handlers": [(callback, event), ...]}
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)


def available():
    return sorted(os.path.basename(p)[4:-3] for p in glob.glob(os.path.join(_DIR, "mod_*.py")))


def find(text):
    text = (text or "").strip().lower()
    keys = available()
    if text in keys:
        return text
    hits = [k for k in keys if k.startswith(text)] if text else []
    return hits[0] if len(hits) == 1 else None


def _ids():
    return {(id(cb), id(ev)) for cb, ev in client.list_event_handlers()}


async def load(key):
    """Вернёт None при успехе или текст ошибки."""
    if key in MODULES:
        return None
    name = "mod_" + key
    before = _ids()
    try:
        if name in sys.modules:
            mod = importlib.reload(sys.modules[name])
        else:
            mod = importlib.import_module(name)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    handlers = [(cb, ev) for cb, ev in client.list_event_handlers() if (id(cb), id(ev)) not in before]
    MODULES[key] = {"mod": mod, "handlers": handlers}
    try:
        if hasattr(mod, "on_load"):
            await mod.on_load()
    except Exception as e:
        await unload(key)
        return f"on_load: {type(e).__name__}: {e}"
    return None


async def unload(key):
    item = MODULES.pop(key, None)
    if not item:
        return False
    try:
        if hasattr(item["mod"], "on_unload"):
            await item["mod"].on_unload()
    except Exception as e:
        print(f"Модуль {key}: ошибка выгрузки: {e}", flush=True)
    for cb, ev in item["handlers"]:
        client.remove_event_handler(cb, ev)
    return True


async def load_all():
    off = set(config.get("modules_off", []))
    for key in available():
        if key in off:
            continue
        err = await load(key)
        print(f"Модуль {key}: " + (f"ОШИБКА {err}" if err else "ok"), flush=True)


def _name(key):
    mod = MODULES[key]["mod"] if key in MODULES else None
    return getattr(mod, "NAME", key) if mod else key


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.mods$"))
async def mods_cmd(event):
    delete_later(event)
    off = set(config.get("modules_off", []))
    lines = []
    for key in available():
        mark = "✅" if key in MODULES else ("⛔" if key in off else "❌")
        lines.append(f"{mark} `{key}` — {_name(key)}")
    await event.edit("🧩 **Модули**\n" + "\n".join(lines) +
                     "\n\n`.unloadmod имя` · `.loadmod имя` · `.reloadmod имя`")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.(loadmod|unloadmod|reloadmod)\s+(\S+)$"))
async def mod_ctl_cmd(event):
    delete_later(event)
    action, arg = event.pattern_match.group(1).lower(), event.pattern_match.group(2)
    key = find(arg)
    if not key:
        return await event.edit(f"⚠️ нет модуля «{arg}». Список: `.mods`")
    off = config.setdefault("modules_off", [])
    if action == "unloadmod":
        await unload(key)
        if key not in off:
            off.append(key)
        text = f"⛔ {key} выгружен"
    else:
        if action == "reloadmod":
            await unload(key)
        if key in off:
            off.remove(key)
        err = await load(key)
        text = f"⚠️ {key}: {err}" if err else f"✅ {key} загружен"
    try:
        await save_config()
    except Exception as e:
        print("Не удалось сохранить настройки:", e, flush=True)
    await event.edit(text)


HELP_HEAD = "🤖 **Юзербот · команды**\n━━━━━━━━━━━━━━━\n\n"
HELP_TAIL = (
    "\n\n━━━━━━━━━━━━━━━\n"
    "🧩 `.mods` — список модулей, `.help имя` — справка по одному\n"
    "ℹ️ Команды видишь только ты\n"
    f"🧹 Всё, кроме .timer и .click, удаляется через {AUTO_DELETE_SEC} с"
)


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.help(?:\s+(\S+))?$"))
async def help_cmd(event):
    delete_later(event)
    arg = event.pattern_match.group(1)
    if arg:
        key = find(arg)
        if key not in MODULES:
            return await event.edit(f"⚠️ модуль «{arg}» не загружен. Список: `.mods`")
        return await event.edit(getattr(MODULES[key]["mod"], "HELP", "нет описания"))
    items = sorted(MODULES.items(), key=lambda kv: (getattr(kv[1]["mod"], "ORDER", 50), kv[0]))
    blocks = [getattr(m["mod"], "HELP", None) for _, m in items]
    await event.edit(HELP_HEAD + "\n\n".join(b for b in blocks if b) + HELP_TAIL)
