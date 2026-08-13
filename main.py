import asyncio
import logging
import os
import socket
import warnings
import aiohttp
from urllib.parse import urlparse
from aiohttp import web, ClientError
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.client.telegram import TelegramAPIServer, PRODUCTION
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, FIREBASE_KEY_PATH
from db import init_db
from handlers_init import register_all_handlers
from whitelist_middleware import WhitelistMiddleware

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="Detected filter.*positional arguments",
)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Порт для Hugging Face Space Health Check
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = 7860

class RetryRequestMiddleware(BaseRequestMiddleware):

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def __call__(self, make_request, bot, method):
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as e:
                logger.warning(
                    "⏳ Превышен лимит флуда Telegram (Flood Control). Ожидание %s сек. перед повторным запросом...",
                    e.retry_after
                )
                await asyncio.sleep(e.retry_after + 1)
                continue
            except (TelegramNetworkError, ClientError, asyncio.TimeoutError, OSError) as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = 1.0 * attempt
                    logger.warning(
                        "Сетевая ошибка воркера (%s: %s), попытка %s/%s...",
                        type(e).__name__, e, attempt, self.max_retries
                    )
                    await asyncio.sleep(delay)
        if last_exc:
            raise last_exc



class CustomAiohttpSession(AiohttpSession):

    async def create_session(self) -> aiohttp.ClientSession:
        if self._should_reset_connector:
            await self.close()

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=self._connector_type(**self._connector_init),
                trust_env=True,
            )
            self._should_reset_connector = False

        return self._session


def _build_bot(api_server: TelegramAPIServer) -> Bot:
    session = CustomAiohttpSession(api=api_server, timeout=30)
    session._connector_init["family"] = socket.AF_INET
    session.middleware(RetryRequestMiddleware())
    return Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

async def _create_bot() -> Bot:
    if not BOT_TOKEN:
        logger.error("❌ ОШИБКА: BOT_TOKEN не найден в переменных окружения!")
    else:
        masked = BOT_TOKEN[:6] + "..." + BOT_TOKEN[-4:] if len(BOT_TOKEN) > 10 else "***"
        logger.info("🔑 BOT_TOKEN обнаружен: %s (длина %s)", masked, len(BOT_TOKEN))

    custom_proxy = os.environ.get("TELEGRAM_API_URL", "").strip().rstrip("/")
    
    candidates = []
    if custom_proxy and custom_proxy != "https://123123-woad.vercel.app":
        candidates.append(("Кастомный ПРОКСИ (" + custom_proxy + ")", TelegramAPIServer.from_base(custom_proxy)))
    elif custom_proxy == "https://123123-woad.vercel.app":
        candidates.append(("Прокси Vercel", TelegramAPIServer.from_base("https://123123-woad.vercel.app")))
    
    candidates.append(("Стандартный сервер", PRODUCTION))

    last_error = None
    for name, server in candidates:
        for attempt in range(1, 3):
            bot = _build_bot(server)
            try:
                me = await asyncio.wait_for(bot.get_me(), timeout=12.0)
                logger.info("✅ Успешно подключено к Telegram API! Бот: @%s", me.username)
                return bot
            except Exception as e:
                last_error = e
                err_str = str(e) or repr(e)
                logger.warning("⚠️ [%s] Попытка %s/2 не удалась (%s: %s)", name, attempt, type(e).__name__, err_str)
                await bot.session.close()
                if attempt < 2:
                    await asyncio.sleep(1.5)

    raise RuntimeError(
        f"Не удалось запустить бота ни одним способом. Последняя ошибка: {last_error}.\n"
        f"Если api.telegram.org заблокирован на вашем хостинге, разверните прокси (папка tg_proxy_render) и укажите TELEGRAM_API_URL."
    )




background_tasks = []

async def on_startup(bot: Bot):
    logger.info("✅ Запуск фоновых задач бота...")
    
    from admin_logs import admin_alert_worker
    from backup_system import backup_database_task
    from chat_stats import flush_stats_task, weekly_reset_task
    from log_system import flush_logs
    from stocks import update_stocks_task
    from user_manager import flush_user_data_task
    
    background_tasks.extend([
        asyncio.create_task(flush_logs(bot)),
        asyncio.create_task(weekly_reset_task(bot)),
        asyncio.create_task(flush_stats_task()),
        asyncio.create_task(flush_user_data_task()),
        asyncio.create_task(update_stocks_task()),
        asyncio.create_task(admin_alert_worker(bot)),
        asyncio.create_task(backup_database_task()),
    ])
    logger.info("Все фоновые задачи успешно инициализированы.")

async def on_shutdown(bot: Bot, storage):
    logger.info("Бот завершает работу.")
    for task in background_tasks:
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
        
    try:
        from user_manager import flush_user_data
        await asyncio.wait_for(flush_user_data(), timeout=10)
    except Exception:
        pass
        
    await storage.close()
    await bot.session.close()

async def main():
    redis_url = os.environ.get("REDIS_URL")


    storage = None
    if redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import Redis
            redis_client = Redis.from_url(
                redis_url,
                socket_timeout=3.0,
                socket_connect_timeout=3.0,
                health_check_interval=30,
                retry_on_timeout=True
            )
            await asyncio.wait_for(redis_client.ping(), timeout=3.0)
            storage = RedisStorage(redis=redis_client)
            logger.info("✅ RedisStorage успешно подключен и проверен!")
        except Exception as e:
            logger.warning("⚠️ Ошибка подключения к Redis (%s). Переключение на MemoryStorage.", e)
            storage = MemoryStorage()
    else:
        storage = MemoryStorage()
        logger.warning("REDIS_URL не найден. Используется MemoryStorage.")

        
    dp = Dispatcher(storage=storage)
    
    try:
        init_db(FIREBASE_KEY_PATH)
        logger.info("База данных подключена.")
    except Exception:
        logger.exception("Не удалось подключить базу данных.")
        
    from cooldown_middleware import CooldownMiddleware
    from log_system import LoggingMiddleware
    
    dp.message.outer_middleware(WhitelistMiddleware())
    dp.message.outer_middleware(LoggingMiddleware())
    dp.callback_query.outer_middleware(WhitelistMiddleware())
    dp.callback_query.outer_middleware(LoggingMiddleware())
    dp.callback_query.middleware(CooldownMiddleware())
    
    register_all_handlers(dp)
    
    bot = await _create_bot()
    dp.startup.register(on_startup)
    
    # Создаем веб-сервер aiohttp только ради Health Check для Hugging Face
    app = web.Application()
    
    async def health(request):
        return web.Response(text="Bot is running")
        
    app.router.add_get("/", health)
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()
    logger.info("Веб-сервер для Health Check запущен на порту %s", WEB_SERVER_PORT)
    
    try:
        logger.info("Запуск бота в режиме Long Polling...")
        # Перед стартом принудительно удаляем старый вебхук, если он был установлен
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await on_shutdown(bot, storage)
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception:
        logger.exception("Бот остановлен из-за ошибки.")
        raise
