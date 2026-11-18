"""
Юзербот для Telegram (Telethon).
Команды (пишешь сам в любом чате, в том числе в «Избранном»):

  .timer 10m текст     — таймер (форматы: 30s, 5m, 1h, 1h30m, 90)
  .calc 2+2*(3**2)     — калькулятор
  .click 5 1           — жать кнопку №1 каждые 5 сек (ответом на сообщение с кнопками)
  .list click          — показать запущенные автонажатия
  .list timer          — показать идущие таймеры
  .grant @юзер аид мозг — выдать человеку доступ к триггеру (all — ко всем)
  .revoke @юзер        — забрать доступ,  .access — кто что может
  .log here            — писать логи использования триггеров в этот чат/канал
  .click 2 1 босс      — то же, но с названием
  .stop босс           — остановить автонажатие по названию
  .stop                — остановить все автонажатия
  .ping                — пинг и состояние бота
  .lot Грааль          — написать @Lot1fybot, ответ формой с кнопками (то же: .лф)
  (все ответы, кроме .timer и .click, сами удаляются через минуту, настройка AUTO_DELETE_SEC)
  .help                — список команд

Доступ только у владельца: бот работает от твоего аккаунта и реагирует
исключительно на ТВОИ исходящие сообщения (outgoing=True).
"""
import ast
import asyncio
import html as html_lib
import json
import math
import operator
import os
import platform
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import telethon
from telethon import Button, TelegramClient, events, functions, types, utils
from telethon.extensions import html as tg_html
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

# Все секреты берутся из переменных окружения (на Railway: вкладка Variables)
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = "".join(os.environ["SESSION_STRING"].split()).strip("'\"")
print("Длина SESSION_STRING:", len(SESSION_STRING), flush=True)

# Боты, на которых разрешён .click (юзернеймы через запятую).
# Можно переопределить переменной ALLOWED_CLICK_BOTS в Railway.
_allowed_raw = [
    u.strip().lstrip("@")
    for u in os.environ.get("ALLOWED_CLICK_BOTS", "Lot1fybot").split(",")
    if u.strip()
]
ALLOWED_CLICK_BOTS = {u.lower() for u in _allowed_raw}
ALLOWED_DISPLAY = ", ".join("@" + u for u in _allowed_raw)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

START_TIME = time.time()  # для .ping (сколько бот работает)


# ---------- Автоудаление сообщений ----------
AUTO_DELETE_SEC = int(os.environ.get("AUTO_DELETE_SEC", "60"))  # через сколько удалять .help и .calc


def delete_later(event, seconds=None):
    """Через время удалить сообщение с командой (у всех, не только у тебя)."""
    async def _run():
        await asyncio.sleep(AUTO_DELETE_SEC if seconds is None else seconds)
        try:
            await event.delete()
        except Exception:
            pass
    asyncio.create_task(_run())



ME_ID = None  # id владельца, ставится в main()
LOG_TZ_HOURS = float(os.environ.get("LOG_TZ_HOURS", "3"))  # часовой пояс в логах (UTC+3)
