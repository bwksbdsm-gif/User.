import core
from core import *
from config import TRIGGERS, TRIGGER_COOLDOWN, _last_trigger, config, norm, save_config

NAME = "Триггеры и доступ"
ORDER = 50
HELP = (
    "🎯 **Триггеры и доступ**\n"
    "Фраза «аид мозг» → бот отвечает «кинуть мог»\n"
    "Работает только у тех, кому ты выдал доступ\n"
    "`.grant @юзер аид мозг` — доступ только к этому триггеру\n"
    "`.grant @юзер all` — доступ ко всем триггерам\n"
    "`.revoke @юзер` — забрать весь доступ\n"
    "`.access` — кто что может\n"
    "`.trigger off` / `.trigger on` — выключить / включить триггеры\n"
    "Можно ответом на сообщение человека, без @\n"
    "`.log here` — писать логи триггеров в этот чат/канал\n"
    "`.log @канал` · `.log me` · `.log off` — куда писать и выключить"
)


def status():
    if not config.get("log", True):
        logs = "выключены"
    elif config.get("log_chat"):
        logs = f"в чат {config['log_chat']}"
    else:
        logs = "в «Избранное»"
    trig = "вкл" if config.get("triggers", True) else "выкл"
    return (f"🔑 Людей с доступом: {len(config['access'])}\n"
            f"🎯 Триггеры: {trig}\n"
            f"📋 Логи: {logs}")

def has_perm(user_id, trigger):
    entry = config["access"].get(str(user_id))
    if not entry:
        return False
    perms = entry.get("perms", [])
    return "*" in perms or trigger in perms


def display_name(ent):
    username = getattr(ent, "username", None)
    if username:
        return "@" + username
    return getattr(ent, "first_name", None) or str(getattr(ent, "id", "?"))


async def resolve_user(event, token):
    """Человек из ответа на сообщение или из @username / id."""
    if event.is_reply:
        replied = await event.get_reply_message()
        if replied and replied.sender_id:
            return replied.sender_id, display_name(await replied.get_sender())
    if token:
        ent = await client.get_entity(int(token) if token.isdigit() else token)
        return ent.id, display_name(ent)
    return None, None


def parse_perm(text):
    """'all' -> '*', иначе название триггера. None, если такого триггера нет."""
    perm = norm(text)
    if perm in ("all", "все", "*"):
        return "*"
    return perm if perm in TRIGGERS else None


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.grant(?:\s+(@\w+|\d{6,}))?\s+(.+)$"))
async def grant_cmd(event):
    delete_later(event)
    perm = parse_perm(event.pattern_match.group(2))
    if perm is None:
        names = ", ".join(f"«{k}»" for k in TRIGGERS)
        return await event.edit(f"⚠️ Нет такого триггера. Есть: {names} или all")
    try:
        uid, name = await resolve_user(event, event.pattern_match.group(1))
    except Exception:
        return await event.edit("⚠️ Не нашёл такого человека. Ответь командой на его сообщение")
    if uid is None:
        return await event.edit("⚠️ Ответь на сообщение человека или укажи @username")
    if uid == core.ME_ID:
        return await event.edit("⚠️ Это ты сам, тебе доступ не нужен")
    entry = config["access"].setdefault(str(uid), {"name": name, "perms": []})
    entry["name"] = name
    if perm == "*":
        entry["perms"] = ["*"]
    elif "*" not in entry["perms"] and perm not in entry["perms"]:
        entry["perms"].append(perm)
    await save_config()
    what = "ко всем триггерам" if perm == "*" else f"к триггеру «{perm}»"
    await event.edit(f"✅ {name}: доступ {what}")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.revoke(?:\s+(@\w+|\d{6,}))?(?:\s+(.+))?$"))
async def revoke_cmd(event):
    delete_later(event)
    perm_text = event.pattern_match.group(2)
    perm = parse_perm(perm_text) if perm_text else "*"
    if perm is None:
        return await event.edit("⚠️ Нет такого триггера")
    try:
        uid, name = await resolve_user(event, event.pattern_match.group(1))
    except Exception:
        return await event.edit("⚠️ Не нашёл такого человека. Ответь командой на его сообщение")
    if uid is None:
        return await event.edit("⚠️ Ответь на сообщение человека или укажи @username")
    entry = config["access"].get(str(uid))
    if not entry:
        return await event.edit(f"⚠️ У {name} и так нет доступа")
    if perm == "*":
        config["access"].pop(str(uid), None)
        what = "весь доступ забран"
    elif perm in entry["perms"]:
        entry["perms"].remove(perm)
        if not entry["perms"]:
            config["access"].pop(str(uid), None)
        what = f"доступ к «{perm}» забран"
    else:
        return await event.edit(f"⚠️ У {name} нет доступа к «{perm}»")
    await save_config()
    await event.edit(f"🚫 {name}: {what}")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.access$"))
async def access_cmd(event):
    delete_later(event)
    lines = ["🔑 **Доступ**", ""]
    access = config["access"]
    if not access:
        lines.append("Пока никому не выдан.")
    for n, entry in enumerate(access.values(), 1):
        perms = entry.get("perms", [])
        what = "все триггеры" if "*" in perms else ", ".join(f"«{p}»" for p in perms)
        lines.append(f"**{n}.** {entry.get('name', '?')} — {what}")
    lines += ["", "**Триггеры:**"]
    lines += [f"«{k}» → «{v}»" for k, v in TRIGGERS.items()]
    lines += ["", "Выдать: `.grant @юзер аид мозг`", "Забрать: `.revoke @юзер`"]
    await event.edit("\n".join(lines))


# ---------- Логи использования триггеров ----------


async def send_to_log(text):
    """Отправить текст в лог-чат (или в «Избранное», если чат не задан)."""
    target = config.get("log_chat") or "me"
    try:
        await client.send_message(target, text, parse_mode=None, link_preview=False)
    except ValueError:  # после перезапуска Telethon не знает чат — обновим список диалогов
        await client.get_dialogs()
        await client.send_message(target, text, parse_mode=None, link_preview=False)


def message_link(event):
    chat = getattr(event, "chat", None)
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{event.id}"
    cid = str(event.chat_id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{event.id}"
    return None


async def log_trigger(event, trigger):
    if not config.get("log", True):
        return
    try:
        sender = await event.get_sender()
        who = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None)
        if last:
            who += " " + last
        who = who.strip() or getattr(sender, "title", None) or "без имени"
        username = getattr(sender, "username", None)
        if username:
            who += f" (@{username})"
        if event.is_private:
            where = "личные сообщения"
        else:
            chat = await event.get_chat()
            where = getattr(chat, "title", None) or str(event.chat_id)
        tz = timezone(timedelta(hours=LOG_TZ_HOURS))
        when = event.date.astimezone(tz).strftime("%d.%m.%Y %H:%M:%S")
        lines = [
            f"🎯 Триггер «{trigger}»",
            f"👤 {who} · id {event.sender_id}",
            f"💬 {where}",
        ]
        link = message_link(event)
        if link:
            lines.append(f"🔗 {link}")
        lines.append(f"🕒 {when} (UTC{LOG_TZ_HOURS:+g})")
        await send_to_log("\n".join(lines))
    except Exception as e:
        print("Не удалось записать лог:", e, flush=True)


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.log(?:\s+(.+))?$"))
async def log_cmd(event):
    delete_later(event)
    arg = (event.pattern_match.group(1) or "").strip()
    low = arg.lower()
    if not arg:
        if not config.get("log", True):
            where = "выключены"
        elif config.get("log_chat"):
            where = f"включены, чат id {config['log_chat']}"
        else:
            where = "включены, приходят в «Избранное»"
        return await event.edit(
            f"📋 **Логи триггеров:** {where}\n\n"
            "`.log here` — писать логи в этот чат или канал\n"
            "`.log @канал` — писать логи в канал по юзернейму\n"
            "`.log me` — писать в «Избранное»\n"
            "`.log off` — выключить")
    if low in ("off", "выкл"):
        config["log"] = False
        await save_config()
        return await event.edit("🔕 Логи триггеров выключены. Включить: `.log me` или `.log here`")
    if low in ("me", "я"):
        config["log"], config["log_chat"] = True, None
        await save_config()
        return await event.edit("📥 Логи триггеров будут приходить в «Избранное»")
    if low in ("here", "тут", "здесь"):
        config["log"], config["log_chat"] = True, event.chat_id
        await save_config()
        return await event.edit("📥 Сюда будут приходить логи триггеров")
    try:
        ent = await client.get_entity(arg)
        new_chat = utils.get_peer_id(ent)
        await client.send_message(ent, "📥 Сюда будут приходить логи триггеров", parse_mode=None)
    except Exception:
        return await event.edit(
            "⚠️ Не получилось. Проверь юзернейм и права на публикацию. "
            "Для приватного канала отправь `.log here` прямо в нём")
    config["log"], config["log_chat"] = True, new_chat
    await save_config()
    await event.edit(f"✅ Логи триггеров теперь идут в {arg}")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.trigger(?:\s+(on|off|вкл|выкл))?$"))
async def trigger_cmd(event):
    delete_later(event)
    arg = (event.pattern_match.group(1) or "").lower()
    if arg in ("on", "вкл"):
        config["triggers"] = True
        await save_config()
    elif arg in ("off", "выкл"):
        config["triggers"] = False
        await save_config()
    await event.edit("🎯 Триггеры: " + ("включены" if config.get("triggers", True) else "выключены"))


@client.on(events.NewMessage())
async def trigger_handler(event):
    text = norm(event.raw_text)
    if not config.get("triggers", True):
        return
    answer = TRIGGERS.get(text)
    if not answer:
        return
    # отвечаем людям с доступом; сам ты можешь проверить триггер в «Избранном»
    owner_test = event.out and event.chat_id == core.ME_ID
    if not owner_test and (event.out or not has_perm(event.sender_id, text)):
        return
    now = time.monotonic()
    key = (event.chat_id, text)
    if now - _last_trigger.get(key, -1e9) < TRIGGER_COOLDOWN:
        return
    _last_trigger[key] = now
    await event.reply(answer)
    if not owner_test:
        await log_trigger(event, text)
