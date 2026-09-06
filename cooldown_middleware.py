"""Bounded per-user button throttling (not a financial transaction lock)."""
import time
from collections import OrderedDict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class CooldownMiddleware(BaseMiddleware):
    def __init__(self, cooldown: float = 0.8, max_entries: int = 10000):
        if cooldown <= 0 or max_entries < 1:
            raise ValueError("Cooldown and max_entries must be positive")
        self.cooldown = cooldown
        self.max_entries = max_entries
        self.last_clicks = OrderedDict()
        # Do not throttle time-sensitive cashout/game actions.
        self.prefixes = ("shop_", "buy_", "sell_", "inv_", "hub:")

    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery) or not (event.data or "").startswith(self.prefixes):
            return await handler(event, data)

        now = time.monotonic()
        while self.last_clicks:
            key, timestamp = next(iter(self.last_clicks.items()))
            if now - timestamp < self.cooldown:
                break
            self.last_clicks.pop(key)

        chat = getattr(event.message, "chat", None)
        key = (getattr(chat, "id", None), event.from_user.id)
        if key in self.last_clicks:
            await event.answer("⏳ Подождите немного перед следующим нажатием.", show_alert=False)
            return None

        self.last_clicks[key] = now
        if len(self.last_clicks) > self.max_entries:
            self.last_clicks.popitem(last=False)
        return await handler(event, data)
