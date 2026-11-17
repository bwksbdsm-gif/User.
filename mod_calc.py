from core import *
from utils import calc

NAME = "Калькулятор"
ORDER = 10
HELP = (
    "🧮 **Калькулятор**\n"
    "`.calc 2+2*3` — посчитать\n"
    "Есть: степень ^, скобки, sqrt, sin, cos, pi"
)


# ---------- Калькулятор ----------
@client.on(events.NewMessage(outgoing=True, pattern=r"(?is)^\.calc\s+(.+)$"))
async def calc_cmd(event):
    delete_later(event)
    expr = event.pattern_match.group(1).strip()
    try:
        result = calc(expr)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        await event.edit(f"🧮 {expr} = {result}")
    except ZeroDivisionError:
        await event.edit("⚠️ деление на ноль")
    except Exception as e:
        await event.edit(f"⚠️ ошибка: {e}")
