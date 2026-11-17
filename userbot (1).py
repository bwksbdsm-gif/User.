import core
from core import *
import config as config_mod
from config import load_config, save_config
import loader  # noqa: F401  (регистрирует .mods, .help, .loadmod ...)


async def main():
    await client.start()  # при первом запуске спросит телефон и код
    me = await client.get_me()
    core.ME_ID = me.id
    await load_config()
    if config_mod._legacy_format:
        try:
            await save_config()  # переписать настройки в читаемом виде
        except Exception as e:
            print("Не удалось обновить вид настроек:", e, flush=True)
    await loader.load_all()
    print(f"Юзербот запущен как {me.first_name} (id {me.id}), модулей: {len(loader.MODULES)}")
    await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
