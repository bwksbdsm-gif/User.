import platform
import loader
from core import *

NAME = "Пинг"
ORDER = 90
HELP = "🏓 `.ping` — пинг и состояние бота"


def uptime_str(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    parts = [f"{d}д" if d else "", f"{h}ч" if h or d else "", f"{m}м" if m or h or d else "", f"{sec}с"]
    return " ".join(x for x in parts if x)


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.ping$"))
async def ping_cmd(event):
    delete_later(event)
    t0 = time.perf_counter()
    await event.edit("🏓 Пинг...")
    ms = (time.perf_counter() - t0) * 1000
    extra = []
    for key, item in loader.MODULES.items():
        fn = getattr(item["mod"], "status", None)
        if fn:
            try:
                extra.append(fn())
            except Exception as e:
                extra.append(f"⚠️ {key}: {e}")
    await event.edit(
        "🏓 **Pong!**\n"
        f"📡 Пинг: {ms:.0f} мс\n"
        f"⏱ Работает: {uptime_str(time.time() - START_TIME)}\n"
        f"🧩 Модулей: {len(loader.MODULES)}\n"
        + "\n".join(extra) + "\n"
        f"🧹 Автоудаление: {AUTO_DELETE_SEC} с\n"
        f"🐍 Python {platform.python_version()} · Telethon {getattr(telethon, '__version__', '?')}")
