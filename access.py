import core
from core import *
from config import TRIGGERS, config, norm, save_config


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


