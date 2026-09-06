import asyncio
import logging
import os
import warnings
from functools import partial

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer, PRODUCTION
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    BOT_TOKEN,
    FIREBASE_KEY_PATH,
    API_TIMEOUT_SECONDS,
    API_CONNECT_TIMEOUT_SECONDS,
    API_RETRY_DELAY_SECONDS,
)
from db import init_db
from handlers_init import register_all_handlers
from runtime import RuntimeStatus, TaskSupervisor, create_health_app
from telegram_retry import RetryRequestMiddleware
from whitelist_middleware import WhitelistMiddleware

warnings.filterwarnings("ignore", category=UserWarning, message="Detected filter.*positional arguments")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CustomAiohttpSession(AiohttpSession):
    async def create_session(self) -> aiohttp.ClientSession:
        if getattr(self, "_should_reset_connector", False):
            await self.close()
        if self._session is None or self._session.closed:
            connector_type = getattr(self, "_connector_type", aiohttp.TCPConnector)
            connector_init = getattr(self, "_connector_init", {})
            self._session = aiohttp.ClientSession(
                connector=connector_type(**connector_init), trust_env=True,
            )
            self._should_reset_connector = False
        return self._session


def _build_bot(api_server: TelegramAPIServer) -> Bot:
    session = CustomAiohttpSession(api=api_server, timeout=API_TIMEOUT_SECONDS)
    session.middleware(RetryRequestMiddleware())
    return Bot(token=BOT_TOKEN, session=session,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def _create_bot() -> Bot:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Настройте окружение перед запуском.")
    custom_proxy = os.environ.get("TELEGRAM_API_URL", "").strip().rstrip("/")
    candidates = []
    if custom_proxy:
        candidates.append(("custom", TelegramAPIServer.from_base(custom_proxy)))
    candidates.append(("telegram", PRODUCTION))
    for name, server in candidates:
        for attempt in range(1, 3):
            bot = _build_bot(server)
            connected = False
            try:
                me = await asyncio.wait_for(bot.get_me(), timeout=API_CONNECT_TIMEOUT_SECONDS)
                connected = True
                logger.info("Подключено к Telegram: @%s", me.username)
                return bot
            except Exception as exc:
                # Network exceptions may contain the entire token-bearing URL.
                logger.warning("Telegram connection %s attempt %s/2 failed (%s)",
                               name, attempt, type(exc).__name__)
            finally:
                if not connected:
                    await bot.session.close()
            if attempt < 2:
                await asyncio.sleep(API_RETRY_DELAY_SECONDS)
    raise RuntimeError("Нет подключения к Telegram. Проверьте токен, сеть и TELEGRAM_API_URL.")


async def create_storage():
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        client = None
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import Redis
            client = Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3,
                                    health_check_interval=30)
            await asyncio.wait_for(client.ping(), timeout=3)
            logger.info("RedisStorage подключен.")
            return RedisStorage(redis=client)
        except BaseException as exc:
            if client is not None:
                await client.aclose()
            if not isinstance(exc, Exception):
                raise
            logger.warning("Redis недоступен (%s); используется MemoryStorage.", type(exc).__name__)
    else:
        logger.warning("REDIS_URL не задан; FSM-состояния не сохраняются при перезапуске.")
    return MemoryStorage()


async def on_startup(bot: Bot, supervisor: TaskSupervisor, status: RuntimeStatus):
    from admin_logs import admin_alert_worker
    from backup_system import backup_database_task
    from chat_stats import flush_stats_task, weekly_reset_task
    from log_system import flush_logs
    from stocks import update_stocks_task
    from user_manager import flush_user_data_task
    from seasons import season_rotator_task

    workers = {
        "logs": partial(flush_logs, bot),
        "weekly_stats": partial(weekly_reset_task, bot),
        "chat_stats": flush_stats_task,
        "user_data": flush_user_data_task,
        "stocks": update_stocks_task,
        "admin_alerts": partial(admin_alert_worker, bot),
        "backups": backup_database_task,
        "seasons": partial(season_rotator_task, bot),
    }
    for name, factory in workers.items():
        supervisor.start(name, factory)
    status.ready = True
    logger.info("Запущено фоновых задач: %s", len(workers))


async def on_shutdown(bot, storage, supervisor, status):
    status.ready = False
    await supervisor.stop()
    from utils import drain_background_tasks
    from user_manager import flush_user_data
    await drain_background_tasks(timeout=5)
    try:
        quota_hit = await asyncio.wait_for(flush_user_data(), timeout=15)
        from user_manager import _dirty_cache
        if quota_hit or _dirty_cache:
            logger.error("Завершение с несохранёнными профилями: %s", len(_dirty_cache))
    except Exception:
        logger.exception("Не удалось выполнить финальное сохранение профилей")
    try:
        await storage.close()
    finally:
        if bot is not None:
            await bot.session.close()


async def main():
    # Never continue serving economy operations after a failed DB initialization.
    init_db(FIREBASE_KEY_PATH)
    storage = await create_storage()
    supervisor = TaskSupervisor()
    status = RuntimeStatus(supervisor)
    bot = None
    runner = None
    try:
        dp = Dispatcher(storage=storage)
        from cooldown_middleware import CooldownMiddleware
        from log_system import LoggingMiddleware

        # Cheap button throttling runs before database-heavy middleware.
        dp.callback_query.outer_middleware(CooldownMiddleware())
        for observer in (dp.message, dp.callback_query):
            observer.outer_middleware(WhitelistMiddleware())
            observer.outer_middleware(LoggingMiddleware())
        register_all_handlers(dp)
        bot = await _create_bot()
        dp.startup.register(partial(on_startup, supervisor=supervisor, status=status))

        runner = web.AppRunner(create_health_app(status))
        await runner.setup()
        port = int(os.environ.get("PORT", "7860"))
        host = os.environ.get("WEB_SERVER_HOST", "0.0.0.0")
        await web.TCPSite(runner, host, port).start()
        logger.info("Health server listening on port %s", port)

        # Preserve queued updates by default. Dropping them must be deliberate.
        drop_pending = os.environ.get("DROP_PENDING_UPDATES", "false").lower() == "true"
        await bot.delete_webhook(drop_pending_updates=drop_pending)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(),
                               close_bot_session=False)
    finally:
        try:
            await on_shutdown(bot, storage, supervisor, status)
        finally:
            if runner is not None:
                await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception:
        logger.exception("Бот остановлен из-за ошибки.")
        raise
