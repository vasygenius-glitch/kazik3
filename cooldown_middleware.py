from typing import Callable, Dict, Any, Awaitable
import time
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

class CooldownMiddleware(BaseMiddleware):
    def __init__(self):
        self.last_clicks = {}

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        # Only apply to shop and inventory
        cd_prefixes = ("shop_", "buy_", "sell_", "inv_")
        if not any(event.data.startswith(prefix) for prefix in cd_prefixes):
            return await handler(event, data)

        user_id = event.from_user.id
        current_time = time.time()
        
        last_click = self.last_clicks.get(user_id, 0)
        if current_time - last_click < 0.8: # 800ms cooldown
            await event.answer("⏳ Обработка...", show_alert=False)
            return

        self.last_clicks[user_id] = current_time
        return await handler(event, data)
