"""Ссылки на Mini App. В группах web_app-кнопки запрещены Telegram, поэтому
используется прямая ссылка t.me/<бот>?startapp=… (Main Mini App из BotFather)
или t.me/<бот>/<short_name>?startapp=…, а без настройки — переход в ЛС с ботом."""
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from v2.security import chat_token

state = {"username": "", "main_app": False}


def webapp_url() -> str:
    url = (os.getenv("V2_WEBAPP_URL") or os.getenv("PUBLIC_URL") or "").strip().rstrip("/")
    if not url and os.getenv("SPACE_HOST"):
        url = "https://" + os.getenv("SPACE_HOST").strip()
    if url and not url.endswith("/app"):
        url += "/app"
    return url + "/" if url else ""


def short_name() -> str:
    return (os.getenv("V2_APP_SHORT_NAME") or "").strip()


async def init(bot):
    try:
        me = await bot.get_me()
        state["username"] = me.username or ""
        state["main_app"] = bool(getattr(me, "has_main_web_app", False))
    except Exception:
        pass


def direct_link(chat_id: int) -> str | None:
    user = state["username"]
    if not user:
        return None
    token = chat_token(chat_id)
    if short_name():
        return f"https://t.me/{user}/{short_name()}?startapp={token}"
    if state["main_app"]:
        return f"https://t.me/{user}?startapp={token}&mode=fullscreen"
    return None


def dm_link(chat_id: int) -> str | None:
    user = state["username"]
    return f"https://t.me/{user}?start=v2_{chat_token(chat_id)}" if user else None


def open_markup(chat_id: int, text: str = "🍄 Открыть Казик") -> InlineKeyboardMarkup | None:
    link = direct_link(chat_id) or dm_link(chat_id)
    if not link:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=link)]])


def webapp_markup(chat_id: int, text: str = "🍄 Открыть Казик") -> InlineKeyboardMarkup | None:
    """Кнопка web_app — только для личных чатов (ограничение Telegram)."""
    url = webapp_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=text, web_app=WebAppInfo(url=f"{url}?c={chat_token(chat_id)}"))]])
