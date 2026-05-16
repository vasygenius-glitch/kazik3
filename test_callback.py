import asyncio
from aiogram import Bot, Dispatcher, Router, types
from aiogram.types import CallbackQuery
from unittest.mock import AsyncMock

async def test():
    cb = CallbackQuery(id="123", from_user=AsyncMock(), chat_instance="123", data="test")
    cb.answer = AsyncMock()
    await cb.answer()
    await cb.answer()
    print("No exception raised!")

asyncio.run(test())
