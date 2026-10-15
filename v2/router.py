"""Команда /v2: Казик V2 включается отдельно в каждом чате и открывается кнопкой.

В группе кнопка ведёт в Mini App этого чата (подписанный токен в startapp),
в личке — web_app-кнопка для привязанной группы. Чужие чаты не затрагиваются.
"""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from config import CREATOR_IDS
from v2 import links, settings
from v2.security import parse_chat_token

router = Router(name="kazik_v2")
log = logging.getLogger(__name__)

INTRO = (
    "🍄 <b>Казик V2</b> — казино сыроежек прямо внутри Telegram\n\n"
    "🃏 Блэкджек, слоты, кости, напёрстки, «Тихая охота», баккара, видео-покер и КНБ против ИИ\n"
    "👥 Общие столы чата: Краш, Рулетка, Складчина и Дуэли — видно, кто играет прямо сейчас\n"
    "🏆 Лига недели с призовым фондом, задания дня, кешбэк, уровни и достижения\n"
    "🎁 Бонус, работа и «дело» — как в командах, только с анимациями\n\n"
    "Шансы честные: казино оставляет себе ~3%. Баланс общий с ботом этого чата."
)
HELP = ("<b>Казик V2</b>\n/v2 — открыть приложение\n/v2 on · /v2 off — включить или выключить в этом чате\n"
        "/v2 announce on|off — анонсы крупных выигрышей\n/v2 status — состояние и настройка")


def _is_creator(message: Message) -> bool:
    return bool(message.from_user) and message.from_user.id in CREATOR_IDS


async def _open_group(message: Message, prefix: str = ""):
    chat_id = message.chat.id
    markup = links.open_markup(chat_id)
    text = (prefix + "\n\n" if prefix else "") + INTRO
    if markup is None:
        text += "\n\n⚠️ Ссылка на приложение пока не настроена — создателю: /v2 status."
    elif not links.direct_link(chat_id):
        text += "\n\n<i>Кнопка откроет личку с ботом — там нажми «Открыть Казик».</i>"
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def _status(message: Message):
    chat_id = message.chat.id
    on = await settings.enabled(chat_id)
    announce = await settings.announce_enabled(chat_id)
    url = links.webapp_url() or "не задан (V2_WEBAPP_URL / SPACE_HOST)"
    if links.short_name():
        mode = f"Mini App «{html.escape(links.short_name())}» — открывается прямо в группе"
    elif links.state["main_app"]:
        mode = "Main Mini App — открывается прямо в группе"
    else:
        mode = "через личку с ботом (настрой Main Mini App в @BotFather, чтобы открывать прямо в группе)"
    await message.answer(
        f"🍄 <b>Казик V2 в этом чате:</b> {'включён ✅' if on else 'выключен ⛔️'}\n"
        f"📣 Анонсы выигрышей: {'вкл' if announce else 'выкл'}\n"
        f"🌐 Адрес приложения: <code>{html.escape(url)}</code>\n"
        f"🔗 Открытие: {mode}\n\nДругие чаты не затрагиваются: включение действует только здесь.",
        disable_web_page_preview=True)


@router.message(Command("v2", "kazik"))
async def cmd_v2(message: Message, command: CommandObject):
    if not message.from_user or message.from_user.is_bot:
        return
    if message.chat.type == "private":
        return await _private(message)
    args = (command.args or "").lower().split()
    chat_id = message.chat.id
    if args and args[0] in ("on", "off", "announce", "status", "help"):
        if args[0] == "help":
            return await message.answer(HELP)
        if not _is_creator(message):
            if args[0] == "status":
                return await message.answer(
                    f"Казик V2 в этом чате {'включён' if await settings.enabled(chat_id) else 'выключен'}.")
            return await message.answer("Переключать Казик V2 может только создатель бота.")
        if args[0] == "status":
            return await _status(message)
        if args[0] == "announce":
            value = len(args) > 1 and args[1] in ("on", "вкл", "1")
            await settings.set_announce(chat_id, value, message.from_user.id)
            return await message.answer("📣 Анонсы крупных выигрышей " + ("включены." if value else "выключены."))
        async with settings.switch_lock(chat_id):
            await settings.set_enabled(chat_id, args[0] == "on", message.from_user.id)
        if args[0] == "on":
            return await _open_group(message, "✅ <b>Казик V2 включён в этом чате.</b> В других чатах ничего не "
                                              "изменилось.")
        return await message.answer("⛔️ Казик V2 выключен в этом чате. Ставки на общих столах доиграются "
                                    "или вернутся автоматически. Старые команды работают как раньше.")
    if not await settings.enabled(chat_id):
        return await message.answer("Казик V2 в этом чате пока выключен.\nВключить может создатель бота: "
                                    "<code>/v2 on</code>")
    await _open_group(message)


async def _send_webapp(message: Message, chat_id: int, title: str = ""):
    if not await settings.enabled(chat_id):
        return await message.answer("В этом чате Казик V2 выключен. Включить: /v2 on (в группе).")
    markup = links.webapp_markup(chat_id)
    if markup is None:
        return await message.answer("Адрес приложения не настроен. Создателю: задай V2_WEBAPP_URL.")
    where = f" чата «{html.escape(title)}»" if title else ""
    await message.answer(f"🍄 Казик{where} готов. Жми кнопку — откроется приложение.", reply_markup=markup)


async def _chat_title(message: Message, chat_id: int) -> str:
    try:
        return (await message.bot.get_chat(chat_id)).title or ""
    except Exception:
        return ""


async def _private(message: Message):
    from user_manager import load_user_primary_chat
    chat_id = await load_user_primary_chat(message.from_user.id)
    if not chat_id or chat_id > 0:
        return await message.answer("Сначала напиши /v2 в своей группе — Казик привязан к чату.")
    await _send_webapp(message, chat_id, await _chat_title(message, chat_id))


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("v2_")), F.chat.type == "private")
async def start_v2(message: Message, command: CommandObject):
    chat_id = parse_chat_token(command.args or "")
    if chat_id is None or chat_id > 0:
        return await message.answer("Ссылка устарела. Напиши /v2 в группе ещё раз.")
    await _send_webapp(message, chat_id, await _chat_title(message, chat_id))
