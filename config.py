from core import *


# ---------- Доступ для других людей и триггеры ----------
# Настройки доступа хранятся в «Избранном» в сообщении с тегом #ub_config,
# поэтому не пропадают при перезапуске на Railway. Это сообщение не удаляй.
CONFIG_TAG = "#ub_config"
config = {"access": {}, "log_chat": None, "log": True, "triggers": True, "modules_off": [], "afk": None, "timers": [], "clicks": []}
# access: id человека -> {"name": ..., "perms": [триггеры или "*"]}
# log_chat: куда писать логи триггеров (None = «Избранное»), log: включены ли логи
config_msg_ids = []   # id сообщений #ub_config (настройки могут занимать несколько)
_saved_texts = []
CONFIG_CHUNK = 3500   # символов в одном сообщении (лимит Telegram 4096)


def norm(text):
    return " ".join((text or "").lower().split())


# Триггеры: фраза -> ответ. Свои добавляй сюда.
TRIGGERS = {norm(k): v for k, v in {
    "аид мозг": "кинуть мог",
}.items()}
TRIGGER_COOLDOWN = 5  # сек между ответами на один и тот же триггер в одном чате
_last_trigger = {}


HEADER_RE = re.compile(r"^" + re.escape(CONFIG_TAG) + r"(?: (\d+)/(\d+))?\n")


async def load_config():
    global config_msg_ids, _saved_texts
    try:
        parts, total = {}, None  # номер части -> (id сообщения, текст)
        async for m in client.iter_messages("me", search=CONFIG_TAG, limit=80):
            text = m.raw_text or ""
            h = HEADER_RE.match(text)
            if not h:
                continue
            idx, n = int(h.group(1) or 1), int(h.group(2) or 1)
            if total is None:
                total = n  # берём самую свежую версию настроек
            if n != total or idx > total or idx in parts:
                continue
            parts[idx] = (m.id, text)
            if len(parts) == total:
                break
        if not total or len(parts) != total:
            return
        ordered = [parts[k] for k in range(1, total + 1)]
        data = parse_config([t[HEADER_RE.match(t).end():] for _, t in ordered])
        if isinstance(data.get("access"), dict):
            config["access"] = data["access"]
        if "log_chat" in data:
            config["log_chat"] = data["log_chat"]
        if "log" in data:
            config["log"] = bool(data["log"])
        if "triggers" in data:
            config["triggers"] = bool(data["triggers"])
        if "modules_off" in data:
            config["modules_off"] = list(data["modules_off"])
        if isinstance(data.get("afk"), dict):
            config["afk"] = data["afk"]
        for field in ("timers", "clicks"):
            if isinstance(data.get(field), list):
                config[field] = data[field]
        config_msg_ids = [mid for mid, _ in ordered]
        _saved_texts = [t for _, t in ordered]
    except Exception as e:
        print("Не удалось загрузить настройки:", e, flush=True)


save_lock = asyncio.Lock()


CONFIG_HEAD = "⚙️ Данные бота — не удалять и не править"
_legacy_format = False  # прочитали старый вид (JSON) — при запуске перепишем красиво


def _text(value):
    """Свободный текст в одну строку; пустое значение пишем как «-»."""
    return " ".join(str(value or "").split()) or "-"


def _untext(value):
    return "" if value.strip() == "-" else value.strip()


def config_texts():
    """Настройки в виде читаемого текста. Одна строка = одна запись."""
    tz = timezone(timedelta(hours=LOG_TZ_HOURS))
    sections = []
    state = "вкл" if config.get("log", True) else "выкл"
    sections.append(("📋 Логи", [f"📋 | {state} | {config.get('log_chat') or 'me'}"]))
    if config.get("afk"):
        sections.append(("💤 AFK", [f"💤 | {int(config['afk']['since'])} | {_text(config['afk'].get('reason'))}"]))
    if config.get("modules_off"):
        sections.append(("🧩 Модули", ["🧩 | " + ",".join(config["modules_off"])]))
    sections.append(("🎯 Триггеры", [f"🎯 | {'вкл' if config.get('triggers', True) else 'выкл'}"]))

    lines = []
    for uid, entry in config["access"].items():
        perms = entry.get("perms", [])
        what = "все" if "*" in perms else "; ".join(perms) or "-"
        lines.append(f"🔑 | {uid} | {what} | {_text(entry.get('name'))}")
    if lines:
        sections.append(("🔑 Доступ", lines))

    lines = []
    for t in config.get("timers", []):
        end = int(t.get("end", 0))
        human = datetime.fromtimestamp(end, tz).strftime("%d.%m %H:%M")
        lines.append(f"⏳ | {human} | {end} | {t.get('mode', 'local')} | "
                     f"{t.get('chat')} | {t.get('msg')} | {_text(t.get('label'))}")
    if lines:
        sections.append(("⏳ Таймеры", lines))

    lines = []
    for c in config.get("clicks", []):
        lines.append(f"🖱 | {c['chat']} | {c['msg']} | {c['button']} | {c['interval']:g} | "
                     f"{int(c.get('since', 0))} | {c.get('done', 0)} | "
                     f"{c.get('bot') or '-'} | {_text(c.get('name'))}")
    if lines:
        sections.append(("🖱 Автонажатия", lines))

    # раскладываем по сообщениям: строки не режем, у каждого сообщения свой заголовок
    limit = CONFIG_CHUNK - 40
    size = lambda ls: sum(len(x) + 1 for x in ls)
    msgs, cur = [], [CONFIG_HEAD]
    for heading, lines in sections:
        need_heading = True
        for line in lines:
            add = ["", heading, line] if need_heading else [line]
            if size(cur) + size(add) > limit:
                msgs.append(cur)
                cur = [CONFIG_HEAD]
                add = ["", heading, line]
            cur += add
            need_heading = False
    msgs.append(cur)
    return [f"{CONFIG_TAG} {k}/{len(msgs)}\n" + "\n".join(m) for k, m in enumerate(msgs, 1)]


def parse_config(bodies):
    """Из текстов сообщений (без заголовков) собрать словарь настроек."""
    global _legacy_format
    if bodies[0].lstrip().startswith("{"):  # старый вид: JSON, порезанный на куски
        _legacy_format = True
        return json.loads("".join(bodies))
    data = {"access": {}, "log_chat": None, "log": True, "triggers": True, "modules_off": [], "afk": None, "timers": [], "clicks": []}
    for line in "\n".join(bodies).splitlines():
        line = line.rstrip()
        rest = line.split(" | ", 1)[1] if " | " in line else ""  # всё после значка записи
        try:
            if line.startswith("📋 | "):
                f = rest.split(" | ")
                data["log"] = f[0].strip() == "вкл"
                if len(f) > 1 and f[1].strip() not in ("me", ""):
                    data["log_chat"] = int(f[1])
            elif line.startswith("💤 | "):
                since, _, reason = rest.strip().partition(" | ")
                data["afk"] = {"since": int(since), "reason": _untext(reason)}
            elif line.startswith("🧩 | "):
                data["modules_off"] = [x for x in rest.strip().split(",") if x]
            elif line.startswith("🎯 | "):
                data["triggers"] = rest.strip() != "выкл"
            elif line.startswith("🔑 | "):
                uid, what, name = (rest.split(" | ", 2) + ["-"])[:3]
                perms = ["*"] if what.strip() == "все" else [x for x in what.split("; ") if x.strip() not in ("", "-")]
                data["access"][uid.strip()] = {"name": _untext(name), "perms": perms}
            elif line.startswith("⏳ | "):
                _, end, mode, chat, msg, label = rest.split(" | ", 5)
                data["timers"].append({"end": int(end), "label": _untext(label), "mode": mode.strip(),
                                       "chat": int(chat), "msg": int(msg)})
            elif line.startswith("🖱 | "):
                chat, msg, button, interval, since, done, bot, name = rest.split(" | ", 7)
                data["clicks"].append({
                    "chat": int(chat), "msg": int(msg), "button": int(button),
                    "interval": float(interval), "since": int(since), "done": int(done),
                    "bot": "" if bot.strip() == "-" else bot.strip(), "name": _untext(name)})
        except (ValueError, TypeError):
            print("Пропустил непонятную строку настроек:", line[:60], flush=True)
    return data


async def save_config():
    global config_msg_ids, _saved_texts
    texts = config_texts()
    async with save_lock:
        old_ids, old_saved = list(config_msg_ids), list(_saved_texts)
        new_ids, new_saved = [], []
        for k, text in enumerate(texts):
            mid = old_ids[k] if k < len(old_ids) else None
            if mid is not None and k < len(old_saved) and old_saved[k] == text:
                new_ids.append(mid)
                new_saved.append(text)
                continue  # эта часть не изменилась
            if mid is not None:
                try:
                    await client.edit_message("me", mid, text, parse_mode=None)
                    new_ids.append(mid)
                    new_saved.append(text)
                    continue
                except Exception as e:
                    if type(e).__name__ == "MessageNotModifiedError":
                        new_ids.append(mid)
                        new_saved.append(text)
                        continue
                    try:
                        await client.delete_messages("me", [mid])
                    except Exception:
                        pass
            msg = await client.send_message("me", text, parse_mode=None)
            new_ids.append(msg.id)
            new_saved.append(text)
        extra = old_ids[len(texts):]
        if extra:  # настройки стали короче — убираем лишние сообщения
            try:
                await client.delete_messages("me", extra)
            except Exception:
                pass
        config_msg_ids, _saved_texts = new_ids, new_saved
