import core
import urllib.request
from core import *
from utils import calc, fmt
from config import config, save_config


# ---------- Таймер ----------
MIN_SCHEDULE_SEC = 30  # короче — используем запасной режим без отложенного сообщения
UNITS = {"s": 1, "с": 1, "m": 60, "м": 60, "h": 3600, "ч": 3600}


def parse_duration(text: str) -> int:
    text = text.lower().strip()
    if text.isdigit():
        return int(text)
    parts = re.findall(r"(\d+)\s*([smhсмч])", text)
    if not parts or "".join(f"{n}{u}" for n, u in parts) != text.replace(" ", ""):
        raise ValueError("формат: 30s, 5m, 1h30m или просто секунды")
    return sum(int(n) * UNITS[u] for n, u in parts)




def bot_token():
    return os.environ.get("HELPER_BOT_TOKEN", "").strip()


def _bot_send(token, chat_id, text):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


async def bot_notify(text):
    """Личное сообщение от бота-помощника (даёт обычное уведомление). Нужен /start у бота."""
    token = bot_token()
    if not token or not core.ME_ID:
        return False
    try:
        await asyncio.to_thread(_bot_send, token, core.ME_ID, text)
        return True
    except Exception as e:
        print("Бот не смог написать (нажми /start у бота):", e, flush=True)
        return False


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.timer\s+(\S+)\s*(.*)$"))
async def timer_cmd(event):
    try:
        seconds = parse_duration(event.pattern_match.group(1))
    except ValueError as e:
        return await event.edit(f"⚠️ {e}")
    if seconds <= 0:
        return await event.edit("⚠️ время должно быть больше нуля")
    label = event.pattern_match.group(2).strip()
    title = f"⏳ Таймер на {fmt(seconds)}" + (f": {label}" if label else "")
    prune_timers()
    entry = {"end": time.time() + seconds, "label": label, "mode": "local",
             "chat": event.chat_id, "msg": event.id}

    # Режим бота: по окончании напишет бот-помощник (обычное уведомление)
    if bot_token():
        entry["mode"] = "bot"
        config["timers"].append(entry)
        try:
            await save_config()
        except Exception as e:
            print("Не удалось сохранить таймер:", e, flush=True)
        await event.edit(f"{title}\n🔔 Напомнит бот-помощник")
        return await run_local_timer(entry)

    # Основной режим: отложенное сообщение в «Избранное». Его отправляет сам
    # Telegram в нужное время, поэтому приходит обычное уведомление (как напоминание),
    # и оно сработает, даже если бот в этот момент перезапустится.
    if seconds >= MIN_SCHEDULE_SEC:
        try:
            await client.send_message("me", timer_done_text(label),
                                      schedule=timedelta(seconds=seconds))
        except Exception:
            pass  # не вышло — уходим в запасной режим ниже
        else:
            entry["mode"] = "sched"
            config["timers"].append(entry)
            try:
                await save_config()
            except Exception as e:
                print("Не удалось сохранить таймер:", e, flush=True)
            return await event.edit(f"{title}\n🔔 Напомню уведомлением в «Избранном»")

    # Запасной режим: ждём и пишем сообщение (уведомления может не быть)
    note = ("короткий таймер — без уведомления" if seconds < MIN_SCHEDULE_SEC
            else "не удалось поставить напоминание — без уведомления")
    config["timers"].append(entry)
    try:
        await save_config()
    except Exception as e:
        print("Не удалось сохранить таймер:", e, flush=True)
    await event.edit(f"{title}\n({note})")
    await run_local_timer(entry)


TIMER_MAX = 25  # сколько таймеров помним (список хранится в одном сообщении)


def timer_done_text(label):
    return "⏰ Таймер закончился!" + (f"\n{label}" if label else "")


def prune_timers():
    now = time.time()
    config["timers"] = [t for t in config.get("timers", []) if t.get("end", 0) > now][-TIMER_MAX:]


async def run_local_timer(entry):
    await asyncio.sleep(max(0.0, entry["end"] - time.time()))
    text = timer_done_text(entry.get("label", ""))
    if entry.get("mode") == "bot" and await bot_notify(text):
        return await _drop_timer(entry)
    try:
        await client.send_message(entry["chat"], text, reply_to=entry.get("msg"))
    except Exception:
        try:
            await client.get_dialogs()
            await client.send_message(entry["chat"], text, reply_to=entry.get("msg"))
        except Exception:
            await client.send_message("me", text)
    await _drop_timer(entry)


async def _drop_timer(entry):
    if entry in config["timers"]:
        config["timers"].remove(entry)
        try:
            await save_config()
        except Exception:
            pass


async def restore_timers():
    """После перезапуска продолжаем короткие таймеры (длинные ведёт сам Telegram)."""
    before = len(config["timers"])
    prune_timers()
    for entry in config["timers"]:
        if entry.get("mode") in ("local", "bot"):
            asyncio.create_task(run_local_timer(entry))
    if before != len(config["timers"]):
        try:
            await save_config()
        except Exception:
            pass


@client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^(?:\.list\s+timers?|\.timers)$"))
async def list_timer_cmd(event):
    delete_later(event)
    before = len(config["timers"])
    prune_timers()
    if before != len(config["timers"]):
        try:
            await save_config()
        except Exception:
            pass
    timers = sorted(config["timers"], key=lambda t: t["end"])
    if not timers:
        return await event.edit("⏳ **Таймеры**\nСейчас нет активных.")
    now = time.time()
    tz = timezone(timedelta(hours=LOG_TZ_HOURS))
    lines = [f"⏳ **Таймеры: {len(timers)}**", ""]
    for n, t in enumerate(timers, 1):
        left = fmt(int(t["end"] - now))
        at = datetime.fromtimestamp(t["end"], tz).strftime("%H:%M")
        label = t.get("label") or "без названия"
        lines.append(f"**{n}.** {label} · осталось {left} · в {at}")
    lines += ["", f"Время по UTC{LOG_TZ_HOURS:+g}"]
    await event.edit("\n".join(lines))




NAME = "Таймер"
ORDER = 20
HELP = (
    "⏳ **Таймер**\n"
    "`.timer 10m чай` — таймер с подписью\n"
    "Время: 30s, 5m, 1h30m или просто секунды\n"
    "🔔 По окончании напишет бот-помощник (если задан HELPER_BOT_TOKEN и нажат Start), иначе «Избранное»\n"
    "`.list timer` — какие таймеры идут"
)


async def on_load():
    await restore_timers()


def status():
    prune_timers()
    return f"⏳ Таймеры: {len(config['timers'])}"
