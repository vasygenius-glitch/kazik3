import asyncio
import logging
import sys
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message="Detected filter.*positional arguments")


from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, FIREBASE_KEY_PATH
from db import init_db
from handlers_init import register_all_handlers
from whitelist_middleware import WhitelistMiddleware
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        from aiogram.fsm.storage.redis import RedisStorage
        storage = RedisStorage.from_url(redis_url)
        logger.info("✅ Подключен RedisStorage для FSM!")
    else:
        storage = MemoryStorage()
        logger.info("⚠️ REDIS_URL не найден, используется MemoryStorage.")

    dp = Dispatcher(storage=storage)

    try:
        init_db(FIREBASE_KEY_PATH)
    except Exception as e:
        logger.error(f"Ошибка БД: {e}", exc_info=True)

    # Hugging Face Spaces block Telegram API sporadically.
    # The most robust way to solve this is to use a clean connector without forcing families,
    # but strictly trusting environment proxies if Hugging Face injects them (`trust_env=True`),
    # and ensuring standard SSL verification is used so we don't trip security systems.
    import aiohttp

    session = AiohttpSession()

    # Enable `trust_env` so if Hugging Face provides HTTP_PROXY, it's automatically used.
    # We do NOT force IPv4 anymore as it was failing on IPv6-only nodes.
    original_create_session = session.create_session
    async def custom_create_session():
        if session._should_reset_connector:
            await session.close()
        if session._session is None or session._session.closed:
            session._session = aiohttp.ClientSession(
                trust_env=True,
                connector=aiohttp.TCPConnector()
            )
            session._should_reset_connector = False
        return session._session

    session.create_session = custom_create_session
    session.timeout = 60

    from aiogram.client.telegram import TelegramAPIServer

    # Используем приватный Cloudflare Worker для обхода жесткой блокировки api.telegram.org на Hugging Face Spaces.
    # Можно переопределить через переменную окружения TELEGRAM_API_URL (например, свой Worker с кастомным доменом).
    api_url = os.environ.get("TELEGRAM_API_URL", "https://super-cloud-9af3.ruzkovmisa.workers.dev/")
    custom_server = TelegramAPIServer.from_base(api_url)

    # Назначаем этот API-сервер внутрь сессии (так требует aiogram 3.x для корректной маршрутизации)
    session.api = custom_server

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    from cooldown_middleware import CooldownMiddleware
    from log_system import LoggingMiddleware
    dp.message.outer_middleware(WhitelistMiddleware())
    dp.message.outer_middleware(LoggingMiddleware())
    dp.callback_query.outer_middleware(WhitelistMiddleware())
    dp.callback_query.outer_middleware(LoggingMiddleware())
    dp.callback_query.middleware(CooldownMiddleware())
    register_all_handlers(dp)

    logger.info("Бот запускается на Hugging Face Spaces...")

    # We will try to resolve webhook conflict and verify token first
    while True:
        try:
            me = await bot.get_me()
            logger.info(f"✅ Соединение с Telegram API установлено! Бот: @{me.username}")
            
            # Удаляем вебхуки, чтобы поллинг не конфликтовал (если они случайно были)
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Вебхуки успешно удалены (если были).")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка при инициализации/проверке токена: {e}", exc_info=True)
            logger.info("Повторная попытка подключения через 10 секунд...")
            await asyncio.sleep(10)

    logger.info("✅ Начинаю слушать сообщения (polling)...")
    from log_system import flush_logs
    from chat_stats import weekly_reset_task, flush_stats_task
    from user_manager import flush_user_data_task
    from stocks import update_stocks_task
    from admin_logs import admin_alert_worker
    from backup_system import backup_database_task
    asyncio.create_task(flush_logs(bot))
    asyncio.create_task(weekly_reset_task(bot))
    asyncio.create_task(flush_stats_task())
    asyncio.create_task(flush_user_data_task())
    asyncio.create_task(update_stocks_task())
    asyncio.create_task(admin_alert_worker(bot))
    asyncio.create_task(backup_database_task())

    # Бесконечный цикл поллинга для защиты от падений сети на Hugging Face Spaces
    from aiogram.exceptions import TelegramConflictError
    try:
        while True:
            try:
                await dp.start_polling(bot, handle_signals=False)
                # If start_polling returns without exception (e.g. if stopped gracefully or webhook conflict again)
                logger.warning("⚠️ Метод start_polling завершился. Переподключение через 5с...")
                await asyncio.sleep(5)
            except TelegramConflictError as e:
                logger.error(f"⚠️ Обнаружен конфликт сессий (запущена другая копия бота): {e}")
                logger.error("Принудительно завершаю этот процесс для разрешения конфликта.")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка сети/поллинга (переподключение через 5с): {e}", exc_info=True)
                await asyncio.sleep(5)
    finally:
        logger.info("🔄 Завершение работы: принудительная синхронизация данных...")
        from user_manager import flush_user_data
        try:
            await asyncio.wait_for(flush_user_data(), timeout=10)
            logger.info("✅ Данные успешно синхронизированы.")
        except Exception as e:
            logger.error(f"⚠️ Ошибка при финальной синхронизации: {e}", exc_info=True)
        await bot.session.close()

if __name__ == "__main__":
    # Flask сервер для keep-alive на Hugging Face Spaces (порт 7860)
    import threading
    from flask import Flask

    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Бот работает круглосуточно на Hugging Face Spaces!"

    def run_flask():
        # Hugging Face Spaces требует чтобы приложение слушало 0.0.0.0:7860
        app.run(host="0.0.0.0", port=7860, debug=False, use_reloader=False)

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
