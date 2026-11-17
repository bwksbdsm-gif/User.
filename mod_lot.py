import core
from core import *


# ---------- Lot1fybot: чат с ботом и формы с кнопками (по модулю друга Lot1fyChat) ----------
# Чтобы в чате появлялись сообщения с рабочими кнопками, нужен свой бот-помощник:
#   1) @BotFather -> /newbot, 2) /setinline (включить), 3) /setinlinefeedback (Enabled, 100%),
#   4) токен записать в переменную HELPER_BOT_TOKEN. Без него .lot отвечает копией без кнопок.
LOT_BOT = os.environ.get("LOT_BOT", "Lot1fybot")
lot_peer = "@" + LOT_BOT      # после запуска заменится числовым id бота
bot_client = None
HELPER_USERNAME = None
forms = {}          # id формы -> {"html", "buttons", "actions", "bot_msg_id", "chat_id", ...}
lot_sessions = {}   # (chat_id, id сообщения-формы в чате) -> id формы
lot_state = {"future": None, "handlers": [], "forwarded": 0}  # ожидание ответа бота (одно за раз)


def lot_remove(handler):
    try:
        client.remove_event_handler(handler)
    except Exception:
        pass


def lot_cancel_pending():
    for h in lot_state["handlers"]:
        lot_remove(h)
    lot_state["handlers"] = []
    fut = lot_state["future"]
    if fut and not fut.done():
        fut.cancel()
    lot_state["future"] = None


async def lot_send_wait(text, bot_msg_id=None, dest_chat=None, accept_plain=False):
    """Написать боту и дождаться ответа с кнопками. Сообщения без кнопок по пути
    пересылаются в dest_chat. Возвращает сообщение бота или None."""
    lot_cancel_pending()
    lot_state["forwarded"] = 0  # сколько сообщений бота уже показали в чате
    loop = asyncio.get_running_loop()
    box = {"fut": loop.create_future()}
    lot_state["future"] = box["fut"]
    seen = set()

    async def on_new(event):
        fut = box["fut"]
        if not fut.done():
            if not event.message.reply_markup and not accept_plain:
                seen.add(event.message.id)
                if dest_chat:
                    lot_state["forwarded"] += 1
                    asyncio.create_task(client.send_message(dest_chat, event.message))
            else:
                fut.set_result(event.message)

    async def on_edit(event):
        fut = box["fut"]
        if fut.done():
            return
        if event.message.id == bot_msg_id or event.message.id in seen:
            if event.message.reply_markup or accept_plain:
                fut.set_result(event.message)

    handlers = [on_new, on_edit]
    client.add_event_handler(on_new, events.NewMessage(
        incoming=True, from_users=lot_peer, func=lambda e: e.is_private))
    client.add_event_handler(on_edit, events.MessageEdited(
        from_users=lot_peer, func=lambda e: e.is_private))
    lot_state["handlers"] = handlers

    await client.send_message(lot_peer, text, reply_to=bot_msg_id)
    try:
        response = await asyncio.wait_for(box["fut"], 5 if bot_msg_id else 10)
        if response and response.media and not response.reply_markup and not accept_plain:
            if dest_chat:  # картинку отдаём сразу и ждём вторую часть — сообщение с кнопками
                lot_state["forwarded"] += 1
                await client.send_message(dest_chat, response)
            box["fut"] = loop.create_future()
            lot_state["future"] = box["fut"]
            try:
                response = await asyncio.wait_for(box["fut"], 5)
            except asyncio.TimeoutError:
                return None
        return response
    except asyncio.TimeoutError:
        if bot_msg_id is not None:
            try:
                msgs = await client.get_messages(lot_peer, ids=[bot_msg_id])
                return msgs[0] if msgs and msgs[0] else None
            except Exception:
                return None
        return None
    except asyncio.CancelledError:
        return None
    finally:
        for h in handlers:
            lot_remove(h)
        lot_state["future"] = None
        lot_state["handlers"] = []


def lot_btn_info(btn):
    try:
        d = {k: v for k, v in btn.to_dict().items() if k not in ("text", "_")}
        return f"{type(btn).__name__} {d}"[:150]
    except Exception:
        return type(btn).__name__


def lot_build(msg, fid):
    """Кнопки сообщения бота -> (ряды кнопок для помощника, действия по номеру кнопки)."""
    rm = getattr(msg, "reply_markup", None)
    if not rm or not getattr(rm, "rows", None):
        return [], {}
    rows, actions, n = [], {}, 0
    for row in rm.rows:
        line = []
        for btn in row.buttons:
            kind = type(btn).__name__
            src = getattr(btn, "type", None) or btn  # в новых слоях данные лежат в btn.type
            data = getattr(src, "data", None)
            url = getattr(src, "url", None)
            copy_text = getattr(src, "copy_text", None) or getattr(src, "text_to_copy", None)
            tag = f"lot:{fid}:{n}".encode()
            if data is not None:
                actions[n] = ("cb", data)
                line.append(Button.inline(btn.text, tag))
            elif url:
                line.append(Button.url(btn.text, url))
            elif copy_text:
                actions[n] = ("copy", copy_text)
                line.append(Button.inline(btn.text, tag))
            elif kind == "KeyboardButton":  # кнопка обычной клавиатуры: шлём её текст боту
                actions[n] = ("text", btn.text)
                line.append(Button.inline(btn.text, tag))
            else:
                actions[n] = ("bad", lot_btn_info(btn))
                line.append(Button.inline(btn.text, tag))
            n += 1
        if line:
            rows.append(line)
    return rows, actions


def lot_html(msg):
    entities = [e for e in (msg.entities or []) if type(e).__name__ != "MessageEntityCustomEmoji"]
    try:
        body = tg_html.unparse(msg.message or "", entities)
    except Exception:
        body = html_lib.escape(msg.message or "")
    return body or "🤖"


def lot_apply(form, fid, msg):
    rows, actions = lot_build(msg, fid)
    form.update({"html": lot_html(msg), "buttons": rows or None,
                 "actions": actions, "bot_msg_id": msg.id})
    return rows


def lot_drop(fid):
    forms.pop(fid, None)
    for key in [k for k, v in lot_sessions.items() if v == fid]:
        lot_sessions.pop(key, None)


async def lot_push(form, call=None):
    """Обновить форму в чате: через нажатую кнопку (call) или по id inline-сообщения."""
    kwargs = dict(parse_mode="html", buttons=form["buttons"], link_preview=False)
    try:
        if call is not None:
            await call.edit(form["html"], **kwargs)
        elif form.get("inline_id") is not None and bot_client is not None:
            await bot_client.edit_message(form["inline_id"], form["html"], **kwargs)
    except Exception as e:
        if type(e).__name__ != "MessageNotModifiedError":
            print("Форма не обновилась:", type(e).__name__, e, flush=True)


async def lot_copy(chat_id, msg, reply_to=None):
    """Копия ответа бота без кнопок (текст + картинка/файл)."""
    text = msg.message or ""
    media = msg.photo or msg.document
    if not text and not media:
        return None
    try:
        return await client.send_message(chat_id, text, file=media,
                                         formatting_entities=msg.entities, reply_to=reply_to)
    except Exception:
        try:
            return await client.send_message(chat_id, text or "(вложение не скопировалось)",
                                             reply_to=reply_to)
        except Exception:
            return None


async def lot_run(event, args):
    """.lot текст — написать боту и показать ответ (формой с кнопками, если можно)."""
    if not args:
        delete_later(event)
        return await event.edit("🤖 Напиши команду! Например: `.lot Грааль`")
    chat_id = event.chat_id
    msg = await lot_send_wait(args, dest_chat=chat_id)
    if msg is None:
        if lot_state["forwarded"]:  # бот ответил без кнопок — ответ уже в чате
            return await event.delete()
        delete_later(event)
        return await event.edit("🤖 Бот не ответил!")
    fid = secrets.token_hex(4)
    rows, actions = lot_build(msg, fid)
    if rows and bot_client is not None and HELPER_USERNAME:
        forms[fid] = {"html": lot_html(msg), "buttons": rows, "actions": actions,
                      "bot_msg_id": msg.id, "chat_id": chat_id}
        while len(forms) > 100:
            lot_drop(next(iter(forms)))
        try:
            results = await client.inline_query(HELPER_USERNAME, fid, entity=chat_id)
            sent = await results[0].click(chat_id, reply_to=event.reply_to_msg_id)
            if getattr(sent, "id", None):
                lot_sessions[(chat_id, sent.id)] = fid
            return await event.delete()  # команду убираем, остаётся форма
        except Exception as e:
            lot_drop(fid)
            print("Форма не отправилась:", type(e).__name__, e, flush=True)
    await lot_copy(chat_id, msg, event.reply_to_msg_id)  # запасной вариант: без кнопок
    await event.delete()


@client.on(events.NewMessage(outgoing=True, pattern=r"(?is)^[.,](?:lot|лф)(?:\s+(.*))?$"))
async def lot_cmd(event):
    await lot_run(event, (event.pattern_match.group(1) or "").strip())


@client.on(events.NewMessage(outgoing=True, pattern=r"(?is)^\.lotdebug(?:\s+(.*))?$"))
async def lotdebug_cmd(event):
    """Показать, какие кнопки реально присылает бот."""
    delete_later(event)
    args = (event.pattern_match.group(1) or "").strip() or "/start"
    msg = await lot_send_wait(args, accept_plain=True)
    if msg is None:
        return await event.edit("🤖 Бот не ответил!")
    rm = msg.reply_markup
    lines = [f"reply_markup: {type(rm).__name__ if rm else None}"]
    for row in (getattr(rm, "rows", None) or []):
        lines.append(" | ".join(f"{type(b).__name__}:{b.text}" for b in row.buttons))
    rows, _ = lot_build(msg, "x")
    lines.append(f"собрано рядов: {len(rows)}")
    lines.append(f"media: {type(msg.media).__name__ if msg.media else None}")
    await event.edit("```\n" + "\n".join(lines) + "\n```")


@client.on(events.NewMessage(outgoing=True))
async def lot_reply_watcher(event):
    """Ответ текстом на форму уходит боту (когда он просит что-то ввести)."""
    if not event.is_reply or not event.raw_text or event.raw_text.startswith((".", ",")):
        return
    fid = lot_sessions.get((event.chat_id, event.reply_to_msg_id))
    form = forms.get(fid) if fid else None
    if not form:
        return
    response = await lot_send_wait(event.raw_text, form["bot_msg_id"], dest_chat=event.chat_id)
    if response is None:
        return
    rows = lot_apply(form, fid, response)
    if rows:
        await lot_push(form)
    else:
        lot_drop(fid)


async def lot_proxy_callback(call, form, fid, data):
    """Нажатие кнопки формы -> то же нажатие в настоящем сообщении бота -> обновить форму."""
    loop = asyncio.get_running_loop()
    msg_id = form["bot_msg_id"]
    fut = loop.create_future()
    holder = {}

    async def on_edit(ev):
        if ev.message.id == msg_id and not fut.done():
            fut.set_result(ev.message)

    async def on_new(ev):
        if not fut.done():
            fut.set_result(ev.message)

    async def on_delete(ev):
        if msg_id in ev.deleted_ids:
            loop.call_later(0.5, lambda: None if fut.done() else fut.set_result(None))

    pairs = [
        (on_edit, events.MessageEdited(from_users=lot_peer, func=lambda e: e.is_private)),
        (on_new, events.NewMessage(incoming=True, from_users=lot_peer, func=lambda e: e.is_private)),
        (on_delete, events.MessageDeleted()),
    ]
    for handler, ev_filter in pairs:
        client.add_event_handler(handler, ev_filter)

    async def fire():
        try:
            result = await client(functions.messages.GetBotCallbackAnswerRequest(
                lot_peer, msg_id, data=data))
            holder["result"] = result
            if result and result.message and not fut.done():
                fut.set_result(None)
        except Exception:
            if not fut.done():
                fut.set_result(None)

    asyncio.create_task(fire())
    try:
        updated = await asyncio.wait_for(fut, 5)
    except asyncio.TimeoutError:
        try:
            msgs = await client.get_messages(lot_peer, ids=[msg_id])
            updated = msgs[0] if msgs and msgs[0] else None
        except Exception:
            updated = None
    finally:
        for handler, _ in pairs:
            lot_remove(handler)

    result = holder.get("result")
    popup = getattr(result, "message", None) if result else None
    try:
        if popup:
            await call.answer(popup, alert=bool(getattr(result, "alert", False)))
        else:
            await call.answer()
    except Exception:
        pass
    if popup and not updated:
        return
    if not updated:  # сообщение бота удалили — оставляем форму без кнопок
        form.update({"html": form["html"] + "\n\n🗑 Сообщение бота удалено", "buttons": None})
        await lot_push(form, call)
        return lot_drop(fid)
    rows = lot_apply(form, fid, updated)
    if rows:
        await lot_push(form, call)
    else:
        lot_drop(fid)


async def lot_proxy_text(call, form, fid, text):
    try:
        await call.answer()
    except Exception:
        pass
    response = await lot_send_wait(text, accept_plain=True)
    if response is None:
        return
    lot_apply(form, fid, response)
    await lot_push(form, call)


async def on_form_inline(event):
    """Помощник отдаёт готовую форму на inline-запрос (только тебе)."""
    form = forms.get((event.text or "").strip())
    if not form or event.sender_id != core.ME_ID:
        return await event.answer([], cache_time=0)
    result = event.builder.article("Lot1fybot", text=form["html"], parse_mode="html",
                                   buttons=form["buttons"], link_preview=False)
    await event.answer([result], cache_time=0)


async def on_form_sent(update):
    """Помощник узнаёт id отправленного inline-сообщения (нужен /setinlinefeedback)."""
    form = forms.get(getattr(update, "query", ""))
    if form is not None and getattr(update, "msg_id", None) is not None:
        form["inline_id"] = update.msg_id


async def on_lot_callback(event):
    try:
        _, fid, n = event.data.decode().split(":")
        n = int(n)
    except ValueError:
        return await event.answer()
    if event.sender_id != core.ME_ID:
        return await event.answer("Нажимать может только владелец", alert=True)
    form = forms.get(fid)
    if not form:
        return await event.answer("Форма устарела, вызови .lot заново", alert=True)
    form["inline_id"] = getattr(event.query, "msg_id", None) or form.get("inline_id")
    kind, value = form["actions"].get(n, ("bad", "неизвестная кнопка"))
    if kind == "cb":
        await lot_proxy_callback(event, form, fid, value)
    elif kind == "text":
        await lot_proxy_text(event, form, fid, value)
    elif kind == "copy":
        await event.answer(str(value), alert=True)
    else:
        await event.answer(f"Не поддерживается: {value}", alert=True)


async def lot_init():
    global lot_peer
    try:
        lot_peer = (await client.get_entity("@" + LOT_BOT)).id
    except Exception as e:
        print("Не удалось найти бота:", type(e).__name__, e, flush=True)


async def start_helper_bot():
    global bot_client, HELPER_USERNAME
    token = os.environ.get("HELPER_BOT_TOKEN", "").strip()
    if not token:
        return
    try:
        bot_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await bot_client.start(bot_token=token)
        HELPER_USERNAME = (await bot_client.get_me()).username
        bot_client.add_event_handler(on_form_inline, events.InlineQuery())
        bot_client.add_event_handler(on_lot_callback, events.CallbackQuery(pattern=rb"lot:"))
        bot_client.add_event_handler(on_form_sent, events.Raw(types.UpdateBotInlineSend))
        print(f"Бот-помощник запущен: @{HELPER_USERNAME}", flush=True)
    except Exception as e:
        bot_client = None
        print("Бот-помощник не запустился:", type(e).__name__, e, flush=True)




NAME = "Lot1fybot"
ORDER = 40
HELP = (
    "🤖 **Lot1fybot**\n"
    "`.lot Грааль` (или `.лф Грааль`) — написать боту, ответ придёт формой с кнопками\n"
    "Ответь на форму текстом, если бот просит что-то ввести\n"
    "Кнопки работают через бота-помощника (HELPER_BOT_TOKEN), жать может только владелец\n"
    "`.lotdebug текст` — показать, какие кнопки прислал бот"
)


async def on_load():
    await lot_init()
    await start_helper_bot()


async def on_unload():
    if bot_client is not None:
        try:
            await bot_client.disconnect()
        except Exception:
            pass
