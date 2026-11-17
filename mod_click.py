from core import *
from config import config, save_config
from utils import fmt


# ---------- Автонажатие кнопок ----------
# Сколько автонажатий можно держать одновременно (можно задать в Railway: MAX_CLICKS)
MAX_CLICKS = int(os.environ.get("MAX_CLICKS", "100"))  # реальный предел, в интерфейсе не показываем
click_tasks = {}  # (chat_id, msg_id, номер_кнопки) -> asyncio.Task
click_meta = {}   # те же ключи -> {"interval", "bot", "name", "since", "done"}


async def persist_clicks():
    """Записать список запущенных автонажатий, чтобы они пережили перезапуск."""
    config["clicks"] = [
        {"chat": k[0], "msg": k[1], "button": k[2], "interval": m["interval"],
         "bot": m.get("bot", ""), "name": m.get("name", ""),
         "since": int(m.get("since", time.time())), "done": m.get("done", 0)}
        for k, m in click_meta.items()
    ]
    try:
        await save_config()
    except Exception as e:
        print("Не удалось сохранить автонажатия:", e, flush=True)


async def restore_clicks():
    items = config.get("clicks") or []
    if not items:
        return
    try:
        await client.get_dialogs()  # чтобы Telethon снова «узнал» чаты
    except Exception as e:
        print("Не удалось обновить список диалогов:", e, flush=True)
    started = 0
    for it in items:
        try:
            key = (it["chat"], it["msg"], it["button"])
            interval = it["interval"]
        except KeyError:
            continue
        if key in click_tasks or len(click_tasks) >= MAX_CLICKS:
            continue
        click_meta[key] = {"interval": interval, "bot": it.get("bot", ""),
                           "name": it.get("name", ""), "since": it.get("since", time.time()),
                           "done": it.get("done", 0)}
        click_tasks[key] = asyncio.create_task(
            click_loop(key, interval, start_delay=started * 0.3))  # старт по очереди
        started += 1
    print(f"Восстановлено автонажатий: {len(click_tasks)}", flush=True)


flood_until = 0.0  # если Telegram попросил подождать, ждут ВСЕ автонажатия


async def click_loop(key, interval, start_delay=0.0):
    global flood_until
    chat_id, msg_id, button = key
    errors = 0
    if start_delay:
        await asyncio.sleep(start_delay)
    while True:
        wait = flood_until - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            msg = await client.get_messages(chat_id, ids=msg_id)
            if not msg or not msg.buttons:
                break
            await msg.click(button - 1)
            meta = click_meta.get(key)
            if meta:
                meta["done"] += 1
            errors = 0
        except FloodWaitError as e:
            flood_until = max(flood_until, time.monotonic() + e.seconds + 1)
            continue
        except asyncio.CancelledError:
            raise
        except ValueError:  # после перезапуска Telethon мог не узнать чат
            try:
                await client.get_dialogs()
            except Exception:
                pass
            errors += 1
            if errors >= 5:
                break
        except Exception:
            errors += 1
            if errors >= 5:  # 5 ошибок подряд — останавливаемся
                break
        await asyncio.sleep(interval)
    click_tasks.pop(key, None)
    click_meta.pop(key, None)
    await persist_clicks()


@client.on(events.NewMessage(
    outgoing=True, pattern=r"(?i)^\.click\s+(\d+(?:\.\d+)?)\s+(\d+)(?:\s+(.+))?$"))
async def click_cmd(event):
    interval = max(float(event.pattern_match.group(1)), 1.0)  # не чаще 1 раза в сек
    button = int(event.pattern_match.group(2))
    name = (event.pattern_match.group(3) or "").strip()
    if len(name) > 30:
        return await event.edit("⚠️ Название слишком длинное (до 30 символов)")
    if button < 1:
        return await event.edit("⚠️ Номер кнопки начинается с 1")
    if not event.is_reply:
        return await event.edit("⚠️ Отправь команду ответом на сообщение с кнопками")
    replied = await event.get_reply_message()
    if not replied.buttons:
        return await event.edit("⚠️ В этом сообщении нет кнопок")
    sender = await replied.get_sender()
    bot_name = getattr(sender, "username", None) or ""
    if bot_name.lower() not in ALLOWED_CLICK_BOTS:
        return await event.edit("⛔ Автонажатие для этого бота отключено")
    total = sum(len(row) for row in replied.buttons)
    if button > total:
        return await event.edit(f"⚠️ В сообщении кнопок: {total}")
    key = (event.chat_id, replied.id, button)
    if name:
        for other, meta in click_meta.items():
            if other != key and meta.get("name", "").lower() == name.lower():
                return await event.edit(
                    f"⚠️ Название «{name}» уже занято. Останови: `.stop {name}`")
    if key in click_tasks:
        click_tasks[key].cancel()  # тот же клик запускаем заново
    elif len(click_tasks) >= MAX_CLICKS:
        return await event.edit("⚠️ Слишком много автонажатий. Останови лишние: .stop")
    click_meta[key] = {"interval": interval, "bot": bot_name, "name": name,
                       "since": time.time(), "done": 0}
    click_tasks[key] = asyncio.create_task(click_loop(key, interval))
    await persist_clicks()
    label = f"«{name}»: " if name else ""
    await event.edit(
        f"🖱 {label}кнопка {button} каждые {interval:g} с. "
        f"Активно: {len(click_tasks)}. Остановить: .stop")


def stop_click(key):
    task = click_tasks.pop(key, None)
    click_meta.pop(key, None)
    if task:
        task.cancel()


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.stop(?:\s+(.+))?$"))
async def stop_cmd(event):
    delete_later(event)
    arg = (event.pattern_match.group(1) or "").strip()
    if not arg:  # .stop — остановить все
        n = len(click_tasks)
        for key in list(click_tasks):
            stop_click(key)
        await persist_clicks()
        return await event.edit(f"🛑 Остановлено автонажатий: {n}")
    # .stop название — остановить одно по имени
    found = [k for k, m in click_meta.items() if m.get("name", "").lower() == arg.lower()]
    # запасной вариант: номер из .list click
    if not found and arg.isdigit():
        keys = list(click_tasks)
        idx = int(arg) - 1
        if 0 <= idx < len(keys):
            found = [keys[idx]]
    if not found:
        return await event.edit(f"⚠️ Автонажатие «{arg}» не найдено. Список: `.list click`")
    key = found[0]
    meta = click_meta.get(key, {})
    desc = f"«{meta['name']}»" if meta.get("name") else f"кнопка №{key[2]}"
    stop_click(key)
    await persist_clicks()
    await event.edit(f"🛑 Остановлено: {desc}")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.list\s+click$"))
async def list_click_cmd(event):
    delete_later(event)
    if not click_tasks:
        return await event.edit("🖱 **Автонажатия**\nСейчас ничего не запущено.")
    now = time.time()
    shown = 15  # длинный список не влезет в одно сообщение Telegram
    lines = [f"🖱 **Автонажатия: {len(click_tasks)}**", ""]
    for n, key in enumerate(click_tasks, 1):
        if n > shown:
            lines.append(f"…и ещё {len(click_tasks) - shown}")
            break
        meta = click_meta.get(key, {})
        name = f"«{meta['name']}» · " if meta.get("name") else ""
        lines.append(
            f"**{n}.** {name}кнопка №{key[2]} · каждые {meta.get('interval', 0):g} с · "
            f"@{meta.get('bot', '?')}\n"
            f"      ⏱ {fmt(int(now - meta.get('since', now)))} · "
            f"нажато: {meta.get('done', 0)}")
    lines += ["", "Остановить одно: `.stop название`", "Остановить все: `.stop`"]
    await event.edit("\n".join(lines))




NAME = "Автонажатие кнопок"
ORDER = 30
HELP = (
    "🖱 **Автонажатие кнопок**\n"
    "`.click 5 1` — жать кнопку №1 каждые 5 сек\n"
    "`.click 2 1 босс` — то же, с названием «босс»\n"
    "Отправляй ответом на сообщение с кнопками\n"
    f"⚠️ Работает только на: {ALLOWED_DISPLAY}\n"
    "♻️ После перезапуска бота автонажатия продолжатся\n"
    "`.list click` — что сейчас запущено\n"
    "`.stop босс` — остановить только «босс»\n"
    "`.stop` — остановить все автонажатия"
)


async def on_load():
    await restore_clicks()


async def on_unload():
    for task in list(click_tasks.values()):
        task.cancel()
    click_tasks.clear()
    click_meta.clear()


def status():
    return f"🖱 Автонажатия: {len(click_tasks)}"
