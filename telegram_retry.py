"""Bounded Telegram retries; ambiguous writes are never retried automatically."""
import asyncio
import logging
import random

from aiohttp import ClientError
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter

logger = logging.getLogger(__name__)

# A timeout does not mean Telegram failed to execute a request. Retrying a
# sendMessage/sendInvoice/etc. could duplicate it. Only retry known safe reads.
SAFE_NETWORK_RETRIES = frozenset({
    "getMe", "getUpdates", "getChat", "getChatMember", "getChatAdministrators",
    "getChatMemberCount", "getFile", "getUserProfilePhotos", "getWebhookInfo",
})


class RetryRequestMiddleware(BaseRequestMiddleware):
    def __init__(self, max_retries: int = 3, max_retry_after: float = 60.0):
        if max_retries < 1 or max_retry_after < 0:
            raise ValueError("Retry limits must be positive (retry_after may be zero)")
        self.max_retries = max_retries  # Total attempts, including the first.
        self.max_retry_after = max_retry_after

    async def __call__(self, make_request, bot, method):
        for attempt in range(self.max_retries):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                if attempt + 1 == self.max_retries or exc.retry_after > self.max_retry_after:
                    raise
                delay = max(0, exc.retry_after) + 0.1
            except (TelegramNetworkError, ClientError, asyncio.TimeoutError, OSError):
                if (attempt + 1 == self.max_retries
                        or getattr(method, "__api_method__", "") not in SAFE_NETWORK_RETRIES):
                    raise
                delay = min(8.0, 2.0 ** attempt) + random.uniform(0, 0.25)
            # Do not log request arguments, tokens, proxy credentials or exception URLs.
            logger.warning("Telegram retry %s/%s in %.2fs", attempt + 2, self.max_retries, delay)
            await asyncio.sleep(delay)
