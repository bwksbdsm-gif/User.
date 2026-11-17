import core
from core import *
from telethon.utils import get_display_name
from config import config, save_config
from utils import fmt

NAME = "AFK"
ORDER = 25
HELP = (
    "💤 **AFK**\n"
    "`.afk причина` — включить: бот ответит тем, кто пишет тебе в личку или упоминает тебя в чате\n"
    "`.unafk` — выключить (список, кто писал, придёт в «Избранное»)\n"
    "Одному чату отвечает не чаще раза в 10 минут"
)
COOLDOWN = int(os.environ.get("AFK_COOLDOWN", "600"))  # сек между ответами одному чату
_last = {}    # chat_id -> время последнего ответа
_missed = {}  # sender_id -> [имя, сколько раз написал]


def is_afk():
    return bool(config.get("afk"))


def afk_text():
    a = config["afk"]
    text = f"💤 Я сейчас AFK, уже {fmt(max(1, int(time.time() - a['since'])))}."
    if a.get("reason"):
        text += f"\nПричина: {a['reason']}"
    return text + "\nОтвечу, как вернусь."


async def _save():
    try:
        await save_config()
    except Exception as e:
        print("Не удалось сохранить AFK:", e, flush=True)


def status():
    if not is_afk():
        return "💤 AFK: выкл"
    return f"💤 AFK: вкл, уже {fmt(max(1, int(time.time() - config['afk']['since'])))}"


@client.on(events.NewMessage(outgoing=True, pattern=r"(?is)^\.afk(?:\s+(.+))?$"))
async def afk_cmd(event):
    delete_later(event)
    reason = (event.pattern_match.group(1) or "").strip()
    config["afk"] = {"since": int(time.time()), "reason": reason}
    _last.clear()
    _missed.clear()
    await _save()
    await event.edit("💤 AFK включён" + (f": {reason}" if reason else ""))


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.unafk$"))
async def unafk_cmd(event):
    delete_later(event)
    a = config.get("afk")
    if not a:
        return await event.edit("💤 AFK и так выключен")
    config["afk"] = None
    await _save()
    spent = fmt(max(1, int(time.time() - a["since"])))
    await event.edit(f"👋 AFK выключен, тебя не было {spent}")
    if _missed:
        people = sorted(_missed.values(), key=lambda x: -x[1])[:15]
        lines = "\n".join(f"• {name}: {n}" for name, n in people)
        try:
            await client.send_message("me", f"💤 Пока ты был AFK ({spent}), писали:\n{lines}", parse_mode=None)
        except Exception as e:
            print("Не удалось отправить список AFK:", e, flush=True)
    _missed.clear()
    _last.clear()


@client.on(events.NewMessage(incoming=True))
async def afk_incoming(event):
    if not is_afk() or event.out:
        return
    if not (event.is_private or event.mentioned):
        return
    if event.sender_id in (None, 777000, core.ME_ID):
        return
    try:
        sender = await event.get_sender()
        if getattr(sender, "bot", False):
            return
        name = get_display_name(sender) or str(event.sender_id)
    except Exception:
        name = str(event.sender_id)
    item = _missed.setdefault(event.sender_id, [name, 0])
    item[1] += 1
    now = time.time()
    if now - _last.get(event.chat_id, 0) < COOLDOWN:
        return
    _last[event.chat_id] = now
    try:
        await event.reply(afk_text())
    except Exception as e:
        print("AFK: не удалось ответить:", e, flush=True)
