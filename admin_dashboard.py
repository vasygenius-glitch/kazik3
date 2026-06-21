# ==============================================================================
#  admin_dashboard.py — Единая Панель Создателя
# ==============================================================================
#  Полностью переработанная версия:
#   • централизованное логирование
#   • декоратор контроля доступа @creator_only
#   • безопасные обёртки над Telegram API (safe_edit / safe_delete / safe_answer)
#   • устойчивый парсинг callback-данных
#   • строгая типизация, docstrings, константы вместо «магии»
#   • сохранён ВЕСЬ исходный функционал
# ==============================================================================

from __future__ import annotations

import os
import time
import random
import asyncio
import hashlib
import logging
import functools
import traceback
from typing import Optional, Any, Callable, Awaitable, Union, Iterable

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import CREATOR_ID, CREATOR_USERNAME, CREATOR_IDS
from escape import escape_html
from db import get_db
from user_manager import (
    get_user_data,
    update_user_balance,
    update_user_field,
    invalidate_user_cache,
    get_user_by_username_or_id,
    get_user_ref,
    safe_get_snapshot,
    _user_cache,
    flush_user_cache_immediately,
)
from whitelist import get_whitelist, add_to_whitelist, remove_from_whitelist
from chances import get_game_chance, set_game_chance
from economy_utils import get_global_tax, set_global_tax
from spy import toggle_spy, get_spy_chats
from lock_system import toggle_lock, get_locked_chats
from admin_logs import log_transaction, check_balance_alert

from profile_bank import (
    get_bank_info,
    create_or_update_bank,
    invalidate_bank_cache,
    DEFAULT_DEPOSIT_RATE,
    MIN_DEPOSIT_RATE,
    MAX_DEPOSIT_RATE,
)

# ==============================================================================
#  ЛОГИРОВАНИЕ
# ==============================================================================
logger = logging.getLogger("admin_dashboard")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | admin_dashboard | %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

router = Router()


# ==============================================================================
#  КОНСТАНТЫ И НАСТРОЙКИ ПАНЕЛИ
# ==============================================================================
class Cfg:
    """Числовые лимиты и настройки панели в одном месте."""
    MIN_TAX: int = 0
    MAX_TAX: int = 100

    MIN_CHANCE: int = -1            # -1 = честный рандом
    MAX_CHANCE: int = 100

    MIN_INV_QTY: int = 0
    MAX_INV_QTY: int = 1000

    MAX_SKILL_LEVEL: int = 5
    MAX_WARNS: int = 3

    WIPE_BATCH_SIZE: int = 500
    WIPE_RESET_BALANCE: int = 500

    BROADCAST_DELAY: float = 0.15
    AUTODELETE_OK: float = 2.0
    AUTODELETE_ERR: float = 5.0
    DELETE_AFTER_ACTION: float = 2.0
    WIPE_RESULT_HOLD: float = 3.0

    BANK_NAME_MAXLEN: int = 60
    DISEASE_INFECT_SECONDS: int = 3600
    PET_STARVE_HOURS: int = 48

    EXECUTION_IMAGE_PATH: str = "assets/execution.png"
    EXECUTION_FALLBACK_URL: str = "https://i.imgur.com/8Qp4S3q.png"


# Доступные игры для настройки шансов: (id, отображаемое имя)
GAMES_CHANCE_LIST: list[tuple[str, str]] = [
    ("slots", "🎰 Slots (Слоты)"),
    ("cups", "🥤 Cups (Стаканчики)"),
    ("roulette", "🎡 Roulette (Рулетка)"),
    ("blackjack", "🃏 Blackjack (Блэкджек)"),
    ("baccarat", "🃏 Baccarat (Баккара)"),
    ("craps", "🎲 Craps (Кости)"),
    ("poker", "🃏 Poker (Видеопокер)"),
    ("crash", "🚀 Crash (Авиатор)"),
]


# ==============================================================================
#  СОСТОЯНИЯ FSM
# ==============================================================================
class AdminPanelState(StatesGroup):
    waiting_for_player_search = State()
    waiting_for_player_money_add = State()
    waiting_for_player_money_set = State()
    waiting_for_say_text = State()
    waiting_for_global_tax = State()
    waiting_for_chance_val = State()
    waiting_for_whitelist_id = State()
    waiting_for_whitelist_title = State()

    # Банковские состояния
    waiting_for_bank_capital = State()
    waiting_for_bank_rate = State()
    waiting_for_bank_new_owner = State()
    waiting_for_bank_create_user = State()
    waiting_for_bank_create_name = State()

    # Кланы
    waiting_for_clan_treasury = State()
    waiting_for_clan_leader = State()

    # Промокоды
    waiting_for_promo_code = State()
    waiting_for_promo_reward = State()
    waiting_for_promo_max_uses = State()

    # Рассылка
    waiting_for_global_broadcast = State()

    # Дополнительно для игрока
    waiting_for_player_reputation = State()
    waiting_for_debt_creditor = State()
    waiting_for_debt_amount = State()
    waiting_for_player_inv_qty = State()
    waiting_for_player_escort = State()
    waiting_for_player_role = State()

    # Крипта
    waiting_for_coin_ticker = State()
    waiting_for_coin_name = State()
    waiting_for_coin_price = State()
    waiting_for_coin_crash = State()

    # Доп. команды
    waiting_for_eval_code = State()
    waiting_for_lock_chat_id = State()


# ==============================================================================
#  УНИВЕРСАЛЬНЫЕ БЕЗОПАСНЫЕ ОБЁРТКИ
# ==============================================================================
async def safe_edit(
    message: types.Message,
    text: str,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> bool:
    """Безопасно редактирует сообщение. Возвращает True при успехе."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("safe_edit failed: %s", exc)
        return False


async def safe_delete(message: Optional[types.Message]) -> bool:
    """Безопасно удаляет сообщение."""
    if message is None:
        return False
    try:
        await message.delete()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("safe_delete failed: %s", exc)
        return False


async def safe_answer(callback: types.CallbackQuery, text: Optional[str] = None,
                      show_alert: bool = False) -> None:
    """Безопасно отвечает на callback (не падает, если истёк)."""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as exc:  # noqa: BLE001
        logger.debug("safe_answer failed: %s", exc)


async def notify_and_autodelete(message: types.Message, text: str,
                                delay: float = Cfg.AUTODELETE_OK) -> None:
    """Отправляет временное уведомление и удаляет его через delay секунд."""
    try:
        sent = await message.answer(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify_and_autodelete send failed: %s", exc)
        return

    async def _cleanup() -> None:
        await asyncio.sleep(delay)
        await safe_delete(sent)

    asyncio.create_task(_cleanup())


def parse_int(raw: str, *, allow_negative: bool = True,
              minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    """
    Аккуратно парсит целое из пользовательского ввода.
    Поддерживает пробелы и запятые. Возвращает None при ошибке/выходе за границы.
    """
    if raw is None:
        return None
    cleaned = raw.replace(" ", "").replace(",", "").replace("\u00a0", "")
    try:
        value = int(cleaned)
    except (ValueError, TypeError):
        return None
    if not allow_negative and value < 0:
        return None
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def parse_float(raw: str, *, minimum: Optional[float] = None,
                maximum: Optional[float] = None) -> Optional[float]:
    """Парсит дробное число (запятая = точка)."""
    if raw is None:
        return None
    cleaned = raw.replace(",", ".").replace(" ", "").strip()
    try:
        value = float(cleaned)
    except (ValueError, TypeError):
        return None
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def fmt_money(amount: Union[int, float]) -> str:
    """Форматирует сумму с разделителями тысяч."""
    try:
        return f"{int(amount):,}"
    except (ValueError, TypeError):
        return str(amount)


def fmt_chance(chance: int) -> str:
    """Человекочитаемый шанс."""
    return f"{chance}%" if chance != -1 else "Честный рандом"


def extract_bot(obj: Any) -> Optional[Bot]:
    """Достаёт объект Bot из message/callback/mock."""
    if hasattr(obj, "bot") and obj.bot is not None:
        return obj.bot
    if hasattr(obj, "message") and getattr(obj.message, "bot", None) is not None:
        return obj.message.bot
    return None


# ==============================================================================
#  MOCK-CALLBACK (для имитации callback из текстовых хендлеров)
# ==============================================================================
class MockCallback:
    """
    Имитация types.CallbackQuery для случаев, когда нужно из текстового
    обработчика вызвать callback-хендлер (повторно отрисовать меню).
    """

    def __init__(self, message: types.Message, menu_message_id: Optional[int],
                 callback_data: str):
        outer_message = message
        outer_menu_id = menu_message_id

        class MockMessage:
            def __init__(self) -> None:
                self.chat = outer_message.chat
                self.from_user = outer_message.from_user
                self.message_id = outer_menu_id
                self.bot = outer_message.bot

            async def edit_text(self, text: str, reply_markup=None, parse_mode: str = "HTML"):
                try:
                    await outer_message.bot.edit_message_text(
                        chat_id=outer_message.chat.id,
                        message_id=outer_menu_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("MockMessage.edit_text fallback: %s", exc)
                    await outer_message.answer(text, reply_markup=reply_markup,
                                               parse_mode=parse_mode)

            async def answer(self, text: str, reply_markup=None, parse_mode: str = "HTML"):
                return await outer_message.answer(text, reply_markup=reply_markup,
                                                  parse_mode=parse_mode)

            async def delete(self):
                try:
                    await outer_message.bot.delete_message(
                        chat_id=outer_message.chat.id, message_id=outer_menu_id
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("MockMessage.delete failed: %s", exc)

        self.message = MockMessage()
        self.bot = message.bot
        self.from_user = message.from_user
        self.data = callback_data

    async def answer(self, text: Optional[str] = None, show_alert: bool = False) -> None:
        if text:
            try:
                await self.bot.send_message(chat_id=self.message.chat.id, text=text)
            except Exception as exc:  # noqa: BLE001
                logger.debug("MockCallback.answer failed: %s", exc)


# ==============================================================================
#  КОНТРОЛЬ ДОСТУПА
# ==============================================================================
def is_creator(event: Union[types.Message, types.CallbackQuery, MockCallback]) -> bool:
    """Проверяет, является ли пользователь Создателем бота."""
    try:
        user = event.from_user
        return int(user.id) in CREATOR_IDS
    except Exception as exc:  # noqa: BLE001
        logger.warning("is_creator check failed: %s", exc)
        return False


def creator_only(handler: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """
    Декоратор: пускает только Создателя.
    Работает и для message-хендлеров, и для callback-хендлеров.
    """

    @functools.wraps(handler)
    async def wrapper(event, *args, **kwargs):
        if not is_creator(event):
            if isinstance(event, types.CallbackQuery):
                await safe_answer(event, "❌ У вас нет доступа.", show_alert=True)
            return None
        try:
            return await handler(event, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.error("Handler %s crashed: %s\n%s",
                         handler.__name__, exc, traceback.format_exc())
            if isinstance(event, types.CallbackQuery):
                await safe_answer(event, f"⚠️ Внутренняя ошибка: {exc}", show_alert=True)
            elif isinstance(event, types.Message):
                await safe_delete(None)
                try:
                    await event.answer(f"⚠️ Произошла ошибка: <code>{escape_html(str(exc))}</code>")
                except Exception:
                    pass
            return None

    return wrapper


# ==============================================================================
#  ХЕЛПЕРЫ ДЛЯ FIRESTORE
# ==============================================================================
async def _collect_docs(docs: Any) -> list:
    """Собирает документы из (async)-итератора в список."""
    result: list = []
    if docs is None:
        return result
    if hasattr(docs, "__aiter__"):
        async for d in docs:
            result.append(d)
    else:
        for d in docs:
            result.append(d)
    return result


def chat_doc(chat_id: int):
    """Ссылка на документ чата."""
    return get_db().collection("chats").document(str(chat_id))


def users_collection(chat_id: int):
    return chat_doc(chat_id).collection("users")


def banks_collection(chat_id: int):
    return chat_doc(chat_id).collection("banks")


def clans_collection(chat_id: int):
    return chat_doc(chat_id).collection("clans")


def split_cb(data: str) -> list[str]:
    """Разбивает callback_data по '_'."""
    return data.split("_")


def cb_int(parts: list[str], index: int, default: Optional[int] = None) -> Optional[int]:
    """Безопасно достаёт int из части callback-данных."""
    try:
        return int(parts[index])
    except (IndexError, ValueError, TypeError):
        return default


# ==============================================================================
#  ГЛОБАЛЬНЫЙ ОТМЕНЩИК FSM
# ==============================================================================
@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Прерывает текущий ввод FSM и возвращает меню (если возможно)."""
    current_state = await state.get_state()
    if current_state is None:
        return

    state_data = await state.get_data()
    msg_id = state_data.get("menu_message_id")
    await state.clear()

    if msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text="❌ Действие отменено Создателем.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("cancel edit failed: %s", exc)

    try:
        await message.answer("❌ Ввод отменён.", reply_markup=types.ReplyKeyboardRemove())
    except Exception:
        pass
    await safe_delete(message)


# ==============================================================================
#  КОМАНДА /admin
# ==============================================================================
@router.message(Command("admin", "admin_panel", "банкиры"))
@router.message(F.text == "!!!admin")
@router.message(F.text == "!!!панель")
@creator_only
async def cmd_admin_main(message: types.Message, state: FSMContext):
    """Точка входа в панель Создателя."""
    await state.clear()
    if message.chat.type == "private":
        await show_chat_select_screen(message, state)
    else:
        await show_group_main_screen(message, state, message.chat.id)


# ==============================================================================
#  ЭКРАНЫ ИНТЕРФЕЙСА
# ==============================================================================
async def show_chat_select_screen(message_or_callback, state: FSMContext) -> None:
    """Экран выбора чата (только в ЛС)."""
    whitelist = await get_whitelist()
    text = "🛠 <b>Панель Создателя: Выберите чат для управления</b>"

    builder = InlineKeyboardBuilder()
    for cid, title in whitelist.items():
        builder.button(text=f"🏢 {title}", callback_data=f"db_m_{cid}")
    builder.button(text="🌍 Глобальные настройки бота", callback_data="db_glob_0")
    builder.button(text="❌ Закрыть", callback_data="db_close")
    builder.adjust(1)

    if isinstance(message_or_callback, types.CallbackQuery):
        await safe_edit(message_or_callback.message, text, builder.as_markup())
    else:
        msg = await message_or_callback.answer(text, reply_markup=builder.as_markup())
        await state.update_data(menu_message_id=msg.message_id)


async def show_group_main_screen(message_or_callback, state: FSMContext,
                                 chat_id: int, edit: bool = False) -> None:
    """Главный экран управления конкретным чатом."""
    await state.clear()
    await state.update_data(chat_id=chat_id)

    chat_title = "Группа"
    bot = extract_bot(message_or_callback)
    if bot:
        try:
            chat_obj = await bot.get_chat(chat_id)
            chat_title = chat_obj.title or chat_title
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_chat failed for %s: %s", chat_id, exc)

    text = (
        f"🛠 <b>Панель Создателя</b>\n"
        f"🏢 Чат: <b>{escape_html(chat_title)}</b> (<code>{chat_id}</code>)\n\n"
        f"Выберите категорию настроек:"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🏦 Управление банками", callback_data=f"db_b_{chat_id}")
    builder.button(text="👤 Управление игроками", callback_data=f"db_p_{chat_id}")
    builder.button(text="🛡 Управление кланами", callback_data=f"db_clans_list_{chat_id}")
    builder.button(text="⚙️ Настройки группы", callback_data=f"db_g_{chat_id}")
    builder.button(text="🌍 Глобальные настройки", callback_data=f"db_glob_{chat_id}")

    if isinstance(message_or_callback, types.CallbackQuery):
        is_pm = message_or_callback.message.chat.type == "private"
    else:
        is_pm = message_or_callback.chat.type == "private"

    if is_pm:
        builder.button(text="⬅️ Сменить чат", callback_data="db_sc_0")
    builder.button(text="❌ Закрыть", callback_data="db_close")
    builder.adjust(1)
    markup = builder.as_markup()

    if edit and isinstance(message_or_callback, types.CallbackQuery):
        await safe_edit(message_or_callback.message, text, markup)
    elif isinstance(message_or_callback, types.CallbackQuery):
        msg = await message_or_callback.message.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)
        await safe_delete(message_or_callback.message)
    else:
        msg = await message_or_callback.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)


# ==============================================================================
#  БАЗОВЫЕ CALLBACK-ОБРАБОТЧИКИ
# ==============================================================================
@router.callback_query(F.data == "db_close")
@creator_only
async def cb_close_dashboard(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_delete(callback.message)
    await safe_answer(callback)


@router.callback_query(F.data == "db_sc_0")
@creator_only
async def cb_select_chat_route(callback: types.CallbackQuery, state: FSMContext):
    await show_chat_select_screen(callback, state)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_m_"))
@creator_only
async def cb_group_main_route(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    if chat_id is None:
        return await safe_answer(callback, "❌ Ошибка данных.", show_alert=True)
    await show_group_main_screen(callback, state, chat_id, edit=True)
    await safe_answer(callback)


# ==============================================================================
#  РАЗДЕЛ: БАНКИ
# ==============================================================================
@router.callback_query(F.data.startswith("db_b_"))
@creator_only
async def cb_banks_list(callback: types.CallbackQuery, state: FSMContext):
    """Список банков чата."""
    chat_id = cb_int(split_cb(callback.data), 2)
    if chat_id is None:
        return await safe_answer(callback, "❌ Ошибка данных.", show_alert=True)
    await state.update_data(chat_id=chat_id)

    docs = await _collect_docs(await banks_collection(chat_id).get())

    text = "🏦 <b>Управление банками чата</b>\n\nСписок зарегистрированных банков:"
    builder = InlineKeyboardBuilder()

    if not docs:
        text += "\n<i>Банки отсутствуют. Назначьте банкира через кнопку ниже.</i>"
    else:
        for doc in docs:
            b_data = doc.to_dict() or {}
            cap = b_data.get("capital", 0)
            name = b_data.get("name", "Банк")
            builder.button(
                text=f"🏛 {escape_html(name)} ({fmt_money(cap)} сыр.)",
                callback_data=f"db_bv_{chat_id}_{doc.id}",
            )

    builder.button(text="➕ Создать банк игроку", callback_data=f"db_bcr_{chat_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_m_{chat_id}")
    builder.adjust(1)

    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


async def show_bank_detail_screen(callback_or_message, state: FSMContext,
                                  chat_id: int, banker_id: int, edit: bool = False) -> None:
    """Детальный экран конкретного банка."""
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        if isinstance(callback_or_message, types.CallbackQuery):
            return await cb_banks_list(callback_or_message, state)
        return

    user_data = await get_user_data(chat_id, banker_id)
    banker_status_text = "🔴 ЗАБАНЕН В БОТЕ" if user_data.get("is_banned") else "🟢 Активен"

    dep_docs = await _collect_docs(
        await users_collection(chat_id).where("bank_name", "==", banker_id).get()
    )
    total_deposits = sum((d.to_dict() or {}).get("bank_deposit", 0) for d in dep_docs)
    total_depositors = len(dep_docs)

    text = (
        f"🏛 <b>Банк: \"{escape_html(bank_data.get('name', 'Без названия'))}\"</b>\n\n"
        f"👤 Владелец: <b>{escape_html(bank_data.get('banker_name', 'Игрок'))}</b> "
        f"(ID: <code>{banker_id}</code>)\n"
        f"🚨 Статус владельца: <b>{banker_status_text}</b>\n\n"
        f"💰 Капитал: <b>{fmt_money(bank_data.get('capital', 0))}</b> сыр.\n"
        f"📈 Процент по вкладам: <b>{bank_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)}%</b> в день\n"
        f"👥 Вкладчиков: <b>{total_depositors}</b> "
        f"(Всего вкладов: <b>{fmt_money(total_deposits)}</b> сыр.)\n\n"
        f"⚙️ Уровни улучшений:\n"
        f"  🛡 Броневики: {bank_data.get('upgrade_armor', 0)}/5\n"
        f"  💼 Вместимость: {bank_data.get('upgrade_earnings', 0)}/5\n"
        f"  👔 Доля банкира: {bank_data.get('upgrade_banker', 0)}/5\n"
        f"  📈 Маркетинг: {bank_data.get('upgrade_marketing', 0)}/5\n"
        f"  🔐 Охрана: {bank_data.get('upgrade_security', 0)}/5"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Сменить владельца", callback_data=f"db_bo_{chat_id}_{banker_id}")
    builder.button(text="💰 Капитал", callback_data=f"db_bc_{chat_id}_{banker_id}")
    builder.button(text="📈 Ставка %", callback_data=f"db_br_{chat_id}_{banker_id}")
    builder.button(text="🗑 Удалить банк", callback_data=f"db_bd_{chat_id}_{banker_id}")
    builder.button(text="⬅️ К списку банков", callback_data=f"db_b_{chat_id}")
    builder.adjust(2, 2, 1)
    markup = builder.as_markup()

    if edit and isinstance(callback_or_message, types.CallbackQuery):
        await safe_edit(callback_or_message.message, text, markup)
        return

    bot = extract_bot(callback_or_message)
    if isinstance(callback_or_message, types.CallbackQuery):
        msg = await callback_or_message.message.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)
        await safe_delete(callback_or_message.message)
    else:
        state_data = await state.get_data()
        msg_id = state_data.get("menu_message_id")
        if msg_id and bot:
            try:
                await bot.edit_message_text(
                    chat_id=callback_or_message.chat.id, message_id=msg_id,
                    text=text, reply_markup=markup, parse_mode="HTML",
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("bank detail edit failed: %s", exc)
        msg = await callback_or_message.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)


@router.callback_query(F.data.startswith("db_bv_"))
@creator_only
async def cb_bank_details(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, banker_id = cb_int(parts, 2), cb_int(parts, 3)
    if chat_id is None or banker_id is None:
        return await safe_answer(callback, "❌ Ошибка данных.", show_alert=True)
    await show_bank_detail_screen(callback, state, chat_id, banker_id, edit=True)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_bc_"))
@creator_only
async def cb_bank_capital_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, banker_id = cb_int(parts, 2), cb_int(parts, 3)
    await state.set_state(AdminPanelState.waiting_for_bank_capital)
    await state.update_data(chat_id=chat_id, banker_id=banker_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    await safe_edit(
        callback.message,
        "💰 <b>Изменение капитала банка</b>\n\n"
        "Введите новую сумму ликвидности (целое число сыроежек) в ответ на это сообщение:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_bank_capital)
@creator_only
async def process_bank_capital_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, banker_id = data["chat_id"], data["banker_id"]

    val = parse_int(message.text, allow_negative=False, minimum=0)
    if val is None:
        await message.answer("❌ Введите положительное целое число. Попробуйте снова или напишите 'отмена'.")
        return

    await create_or_update_bank(chat_id, banker_id, {"capital": val})
    invalidate_bank_cache(chat_id, banker_id)
    logger.info("Capital of bank %s in chat %s set to %s", banker_id, chat_id, val)

    await show_bank_detail_screen(message, state, chat_id, banker_id)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_br_"))
@creator_only
async def cb_bank_rate_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, banker_id = cb_int(parts, 2), cb_int(parts, 3)
    await state.set_state(AdminPanelState.waiting_for_bank_rate)
    await state.update_data(chat_id=chat_id, banker_id=banker_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    await safe_edit(
        callback.message,
        f"📈 <b>Изменение процентной ставки вклада</b>\n\n"
        f"Введите процент в день (от {MIN_DEPOSIT_RATE}% до {MAX_DEPOSIT_RATE}%, можно дробью, например 4.5):",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_bank_rate)
@creator_only
async def process_bank_rate_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, banker_id = data["chat_id"], data["banker_id"]

    rate = parse_float(message.text, minimum=MIN_DEPOSIT_RATE, maximum=MAX_DEPOSIT_RATE)
    if rate is None:
        await message.answer(
            f"❌ Введите число от {MIN_DEPOSIT_RATE} до {MAX_DEPOSIT_RATE}. Попробуйте ещё раз:"
        )
        return

    await create_or_update_bank(chat_id, banker_id, {"deposit_rate": rate})
    invalidate_bank_cache(chat_id, banker_id)
    await show_bank_detail_screen(message, state, chat_id, banker_id)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_bo_"))
@creator_only
async def cb_bank_owner_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, banker_id = cb_int(parts, 2), cb_int(parts, 3)
    await state.set_state(AdminPanelState.waiting_for_bank_new_owner)
    await state.update_data(chat_id=chat_id, banker_id=banker_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    await safe_edit(
        callback.message,
        "👤 <b>Смена владельца банка</b>\n\n"
        "Отправьте @username (с символом @) или числовой Telegram ID нового владельца.\n\n"
        "<i>(Новый владелец станет Банкиром, а все вклады будут перенесены под его контроль)</i>",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_bank_new_owner)
@creator_only
async def process_bank_owner_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, old_banker_id = data["chat_id"], data["banker_id"]

    target_id, target_data = await get_user_by_username_or_id(chat_id, message.text.strip())
    if not target_id:
        await message.answer("❌ Пользователь не найден в базе. Введите другой ID или @username:")
        return
    if int(target_id) == int(old_banker_id):
        await message.answer("❌ Этот пользователь уже владелец банка. Укажите другого:")
        return

    existing_bank = await get_bank_info(chat_id, target_id)
    if existing_bank:
        await message.answer(
            f"❌ У пользователя уже есть банк: <b>{escape_html(existing_bank.get('name'))}</b>. "
            f"Нельзя владеть двумя банками!"
        )
        return

    try:
        old_ref = banks_collection(chat_id).document(str(old_banker_id))
        new_ref = banks_collection(chat_id).document(str(target_id))

        bank_doc = await old_ref.get()
        if not bank_doc.exists:
            await message.answer("❌ Банк не найден.")
            return

        bank_data = bank_doc.to_dict()
        bank_data["banker_name"] = target_data.get("full_name", "Игрок")

        await new_ref.set(bank_data)
        await old_ref.delete()

        await update_user_field(chat_id, target_id, "is_banker", True)
        await update_user_field(chat_id, old_banker_id, "is_banker", False)

        dep_docs = await _collect_docs(
            await users_collection(chat_id).where("bank_name", "==", old_banker_id).get()
        )
        updated = 0
        for doc in dep_docs:
            uid = int(doc.id) if str(doc.id).isdigit() else doc.id
            await update_user_field(chat_id, uid, "bank_name", target_id)
            await flush_user_cache_immediately(chat_id, uid)
            updated += 1

        await flush_user_cache_immediately(chat_id, old_banker_id)
        await flush_user_cache_immediately(chat_id, target_id)
        invalidate_bank_cache(chat_id, old_banker_id, bank_data.get("name"))
        invalidate_bank_cache(chat_id, target_id, bank_data.get("name"))

        logger.info("Bank owner changed: %s -> %s (chat %s)", old_banker_id, target_id, chat_id)
        await message.answer(
            f"✅ <b>Владелец банка изменён!</b>\n\n"
            f"🏛 Банк: \"{escape_html(bank_data.get('name'))}\"\n"
            f"👤 Прежний: <code>{old_banker_id}</code>\n"
            f"👤 Новый: <b>{escape_html(target_data.get('full_name'))}</b> (<code>{target_id}</code>)\n"
            f"👥 Перенаправлено вкладчиков: {updated}"
        )
        await show_bank_detail_screen(message, state, chat_id, target_id)
        await safe_delete(message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Bank owner transfer failed: %s", exc)
        await message.answer(f"❌ Ошибка переноса:\n<code>{escape_html(str(exc))}</code>")


@router.callback_query(F.data.startswith("db_bd_"))
@creator_only
async def cb_bank_delete_confirm_screen(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, banker_id = cb_int(parts, 2), cb_int(parts, 3)
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await safe_answer(callback, "Банк не найден.")

    text = (
        f"⚠️ <b>Удаление банка \"{escape_html(bank_data.get('name'))}\"</b>\n\n"
        f"Выберите тип удаления:\n\n"
        f"1. <b>С возвратом средств (Рекомендуется)</b> — вклады вернутся игрокам наличными.\n"
        f"2. <b>Без возврата</b> — банк стирается, вклады игроков сгорают."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить и вернуть средства", callback_data=f"db_bdc_{chat_id}_{banker_id}_refund")
    builder.button(text="🔥 Списать без возврата (Вайп)", callback_data=f"db_bdc_{chat_id}_{banker_id}_norefund")
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_bdc_"))
@creator_only
async def cb_perform_bank_delete(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, banker_id = cb_int(parts, 2), cb_int(parts, 3)
    mode = parts[4] if len(parts) > 4 else "norefund"

    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await safe_answer(callback, "Банк не найден.", show_alert=True)

    dep_docs = await _collect_docs(
        await users_collection(chat_id).where("bank_name", "==", banker_id).get()
    )
    total_refunded, depositors = 0, 0

    for doc in dep_docs:
        u_data = doc.to_dict() or {}
        uid = int(doc.id) if str(doc.id).isdigit() else doc.id
        dep_amt = u_data.get("bank_deposit", 0)
        if mode == "refund" and dep_amt > 0:
            await update_user_balance(chat_id, uid, dep_amt, action="Bank Delete Refund")
            total_refunded += dep_amt
        await update_user_field(chat_id, uid, "bank_deposit", 0)
        await update_user_field(chat_id, uid, "bank_name", None)
        await update_user_field(chat_id, uid, "deposit_start_time", 0)
        await flush_user_cache_immediately(chat_id, uid)
        depositors += 1

    await update_user_field(chat_id, banker_id, "is_banker", False)
    await flush_user_cache_immediately(chat_id, banker_id)
    await banks_collection(chat_id).document(str(banker_id)).delete()
    invalidate_bank_cache(chat_id, banker_id, bank_data.get("name"))

    if mode == "refund":
        result = (f"✅ Банк <b>\"{escape_html(bank_data.get('name'))}\"</b> удалён.\n"
                  f"👥 Возвращены вклады: {depositors} игрокам на {fmt_money(total_refunded)} сыр.")
    else:
        result = (f"🔥 Банк <b>\"{escape_html(bank_data.get('name'))}\"</b> стёрт из базы.\n"
                  f"👥 Аннулированы вклады: {depositors} игроков. Деньги сгорели.")

    logger.info("Bank %s deleted (mode=%s) in chat %s", banker_id, mode, chat_id)
    await safe_edit(callback.message, result, None)
    await safe_answer(callback, "Банк успешно удалён!", show_alert=True)
    await asyncio.sleep(Cfg.DELETE_AFTER_ACTION)
    await cb_banks_list(callback, state)


@router.callback_query(F.data.startswith("db_bcr_"))
@creator_only
async def cb_bank_create_user_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    await state.set_state(AdminPanelState.waiting_for_bank_create_user)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_b_{chat_id}")
    await safe_edit(
        callback.message,
        "➕ <b>Назначение банкира и создание банка</b>\n\n"
        "Шаг 1: Введите @username или Telegram ID будущего банкира:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_bank_create_user)
@creator_only
async def process_bank_create_user_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]

    target_id, target_data = await get_user_by_username_or_id(chat_id, message.text.strip())
    if not target_id:
        await message.answer("❌ Игрок не найден в базе чата. Попробуйте ещё раз:")
        return

    existing = await get_bank_info(chat_id, target_id)
    if existing:
        await message.answer(
            f"❌ У пользователя уже есть банк: <b>{escape_html(existing.get('name'))}</b>. "
            f"Сначала удалите его или выберите другого банкира."
        )
        return

    await state.set_state(AdminPanelState.waiting_for_bank_create_name)
    await state.update_data(target_user_id=target_id,
                            target_name=target_data.get("full_name", "Банкир"))
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_b_{chat_id}")
    await message.answer(
        f"➕ <b>Назначение банкира: {escape_html(target_data.get('full_name'))}</b>\n\n"
        f"Шаг 2: Введите НАЗВАНИЕ для нового банка:",
        reply_markup=builder.as_markup(),
    )
    await safe_delete(message)


@router.message(AdminPanelState.waiting_for_bank_create_name)
@creator_only
async def process_bank_create_name_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    target_id = data["target_user_id"]
    target_name = data["target_name"]
    bank_name = message.text.strip()[: Cfg.BANK_NAME_MAXLEN]

    await update_user_field(chat_id, target_id, "is_banker", True)
    await flush_user_cache_immediately(chat_id, target_id)
    await create_or_update_bank(chat_id, target_id, {
        "name": bank_name,
        "capital": 0,
        "banker_name": target_name,
        "deposit_rate": DEFAULT_DEPOSIT_RATE,
    })
    invalidate_bank_cache(chat_id, target_id, bank_name)
    logger.info("Bank '%s' created for %s in chat %s", bank_name, target_id, chat_id)

    await message.answer(f"🏛 Банк <b>\"{escape_html(bank_name)}\"</b> создан, банкир назначен!")
    await show_bank_detail_screen(message, state, chat_id, target_id)
    await safe_delete(message)


# ==============================================================================
#  РАЗДЕЛ: ИГРОКИ
# ==============================================================================
@router.callback_query(F.data.startswith("db_p_"))
@creator_only
async def cb_player_search_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    await state.set_state(AdminPanelState.waiting_for_player_search)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_m_{chat_id}")
    await safe_edit(
        callback.message,
        "🔍 <b>Управление игроками</b>\n\n"
        "Отправьте @username или числовой Telegram ID игрока:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_search)
@creator_only
async def process_player_search_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    target_id, _ = await get_user_by_username_or_id(chat_id, message.text.strip())
    if not target_id:
        await message.answer("❌ Игрок не найден в базе чата. Попробуйте ещё раз:")
        return
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


async def show_player_details_screen(callback_or_message, state: FSMContext,
                                     chat_id: int, target_id: int, edit: bool = False) -> None:
    """Детальный экран профиля игрока."""
    data = await get_user_data(chat_id, target_id)

    vip_status = "👑 Да" if data.get("is_vip") else "❌ Нет"
    banker_status = "💼 Да" if data.get("is_banker") else "❌ Нет"
    ban_status = "🚫 Забанен" if data.get("is_banned") else "🟢 Активен"
    hidden_status = "👁 Скрыт" if data.get("hide_in_top") else "🟢 Виден"
    warns_count = len(data.get("warns", []) or [])
    balance = data.get("balance", 0)
    full_name = escape_html(data.get("full_name", "Игрок"))
    username = data.get("username", "нет")
    reputation = data.get("reputation", 0)
    escort_count = data.get("escort_count", 0)
    custom_role = data.get("custom_role", "Нет")

    # Питомец
    pet = data.get("pet")
    pet_text = "Нет"
    if isinstance(pet, dict):
        try:
            from pets import PETS_SHOP
            p_id = pet.get("id")
            p_name = PETS_SHOP.get(p_id, {}).get("name", p_id)
            fed_hours_ago = (time.time() - pet.get("last_fed", 0)) / 3600
            if fed_hours_ago > Cfg.PET_STARVE_HOURS:
                pet_text = f"{p_name} (Сбежал/Голодает)"
            else:
                pet_text = f"{p_name} (Сыт, кормили {int(fed_hours_ago)}ч назад)"
        except Exception as exc:  # noqa: BLE001
            logger.debug("pet render failed: %s", exc)

    # Навыки
    sk_text = "Нет"
    try:
        from skills import SKILLS
        skills = data.get("skills", {}) or {}
        sk_list = [f"{cfg.get('name', sid)}: {skills.get(sid, 0)}/5" for sid, cfg in SKILLS.items()]
        sk_text = " | ".join(sk_list) if sk_list else "Нет"
    except Exception as exc:  # noqa: BLE001
        logger.debug("skills render failed: %s", exc)

    # Долги
    debts = data.get("debts", {})
    total_debt = sum(debts.values()) if isinstance(debts, dict) else 0
    debt_text = f"<b>{fmt_money(total_debt)}</b> сыр." if total_debt > 0 else "Нет"

    # Болезни
    dis_text = "Здоров(а)"
    try:
        from diseases import get_active_diseases, DISEASES
        active_dis = await get_active_diseases(chat_id, target_id, u_data=data)
        dis_list = [DISEASES[d]["name"] for d in active_dis if d in DISEASES]
        dis_text = ", ".join(dis_list) if dis_list else "Здоров(а)"
    except Exception as exc:  # noqa: BLE001
        logger.debug("diseases render failed: %s", exc)

    # Инвентарь
    inv_text = "Пусто"
    try:
        from shop import ITEMS
        inventory = data.get("inventory", {}) or {}
        inv_list = [f"{ITEMS.get(k, {}).get('name', k)} (x{v})" for k, v in inventory.items()]
        inv_text = ", ".join(inv_list) if inv_list else "Пусто"
    except Exception as exc:  # noqa: BLE001
        logger.debug("inventory render failed: %s", exc)

    text = (
        f"👤 <b>Управление игроком: {full_name}</b>\n"
        f"📱 ID: <code>{target_id}</code> | 🏷 @{username}\n\n"
        f"💰 Баланс: <b>{fmt_money(balance)}</b> сыр.\n"
        f"📈 Репутация: <b>{reputation}</b>\n"
        f"🎭 Роль: <b>{custom_role}</b>\n"
        f"🔞 Выебан(а): <b>{escort_count}</b> раз\n"
        f"💸 Долги: {debt_text}\n"
        f"👑 VIP: <b>{vip_status}</b>\n"
        f"💼 Банкир: <b>{banker_status}</b>\n"
        f"🚫 Статус: <b>{ban_status}</b>\n"
        f"👁 В топе: <b>{hidden_status}</b>\n"
        f"⚠️ Варны: <b>{warns_count}/{Cfg.MAX_WARNS}</b>\n"
        f"🩺 Болезни: <i>{dis_text}</i>\n"
        f"🐾 Питомец: <i>{pet_text}</i>\n"
        f"🎯 Навыки: <i>{sk_text}</i>\n"
        f"📦 Инвентарь: <i>{inv_text}</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Выдать сыр", callback_data=f"db_pma_{chat_id}_{target_id}")
    builder.button(text="💰 Уст. баланс", callback_data=f"db_pms_{chat_id}_{target_id}")
    builder.button(text="👑 VIP +/-", callback_data=f"db_ptv_{chat_id}_{target_id}")
    builder.button(text="💼 Банкир +/-", callback_data=f"db_ptb_{chat_id}_{target_id}")
    builder.button(text="🚫 Бан +/-", callback_data=f"db_ptban_{chat_id}_{target_id}")
    builder.button(text="👁 Топ +/-", callback_data=f"db_pth_{chat_id}_{target_id}")
    builder.button(text="⚠️ Варн +", callback_data=f"db_pwa_{chat_id}_{target_id}")
    builder.button(text="🧼 Варн -", callback_data=f"db_pwr_{chat_id}_{target_id}")
    builder.button(text="🩺 ЗППП", callback_data=f"db_pdiseases_menu_{chat_id}_{target_id}")
    builder.button(text="🎒 Вещи", callback_data=f"db_pim_{chat_id}_{target_id}")
    builder.button(text="🔇 Мут", callback_data=f"db_pmute_menu_{chat_id}_{target_id}")
    builder.button(text="🐾 Питомцы", callback_data=f"db_ppet_menu_{chat_id}_{target_id}")
    builder.button(text="🎯 Навыки", callback_data=f"db_pskills_menu_{chat_id}_{target_id}")
    builder.button(text="💸 Долги", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
    builder.button(text="📈 Репутация", callback_data=f"db_prep_prompt_{chat_id}_{target_id}")
    builder.button(text="🔞 Выебан(а)", callback_data=f"db_pesc_prompt_{chat_id}_{target_id}")
    builder.button(text="🎭 Роль", callback_data=f"db_prole_prompt_{chat_id}_{target_id}")
    builder.button(text="🔄 Сбросить FSM", callback_data=f"db_pfsm_reset_{chat_id}_{target_id}")
    builder.button(text="⚡️ Казнить!", callback_data=f"db_pexecute_ask_{chat_id}_{target_id}")
    builder.button(text="🧹 Полный сброс", callback_data=f"db_pwi_{chat_id}_{target_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_m_{chat_id}")
    builder.adjust(2, 2, 2, 2, 3, 3, 3, 2, 2)
    markup = builder.as_markup()

    bot = extract_bot(callback_or_message)

    if edit and isinstance(callback_or_message, types.CallbackQuery):
        await safe_edit(callback_or_message.message, text, markup)
        return

    if isinstance(callback_or_message, types.CallbackQuery):
        msg = await callback_or_message.message.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)
        await safe_delete(callback_or_message.message)
    else:
        state_data = await state.get_data()
        msg_id = state_data.get("menu_message_id")
        if msg_id and bot:
            try:
                await bot.edit_message_text(
                    chat_id=callback_or_message.chat.id, message_id=msg_id,
                    text=text, reply_markup=markup, parse_mode="HTML",
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("player detail edit failed: %s", exc)
        msg = await callback_or_message.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)


@router.callback_query(F.data.startswith("db_pv_"))
@creator_only
async def cb_player_details_view(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)
    await safe_answer(callback)


async def _toggle_player_flag(callback: types.CallbackQuery, state: FSMContext,
                              field: str, label: str) -> tuple[int, int, bool]:
    """Универсальное переключение булевого поля игрока."""
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    data = await get_user_data(chat_id, target_id)
    new_val = not data.get(field, False)
    await update_user_field(chat_id, target_id, field, new_val)
    await flush_user_cache_immediately(chat_id, target_id)
    await safe_answer(callback, f"{label}: {new_val}")
    logger.info("Player %s field '%s' -> %s (chat %s)", target_id, field, new_val, chat_id)
    return chat_id, target_id, new_val


@router.callback_query(F.data.startswith("db_ptv_"))
@creator_only
async def cb_toggle_vip(callback: types.CallbackQuery, state: FSMContext):
    chat_id, target_id, _ = await _toggle_player_flag(callback, state, "is_vip", "VIP-статус установлен")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_ptb_"))
@creator_only
async def cb_toggle_banker_role(callback: types.CallbackQuery, state: FSMContext):
    chat_id, target_id, _ = await _toggle_player_flag(callback, state, "is_banker", "Статус банкира установлен")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_ptban_"))
@creator_only
async def cb_toggle_user_ban(callback: types.CallbackQuery, state: FSMContext):
    chat_id, target_id, _ = await _toggle_player_flag(callback, state, "is_banned", "Бан-статус в боте установлен")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_pth_"))
@creator_only
async def cb_toggle_user_top_hide(callback: types.CallbackQuery, state: FSMContext):
    chat_id, target_id, _ = await _toggle_player_flag(callback, state, "hide_in_top", "Скрытность в топе установлена")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_pwa_"))
@creator_only
async def cb_add_user_warn(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    data = await get_user_data(chat_id, target_id)
    warns = list(data.get("warns", []) or [])
    warns.append({
        "reason": "Выдано через Единую Панель Создателя",
        "time": int(time.time()),
        "by": callback.from_user.id,
    })
    await update_user_field(chat_id, target_id, "warns", warns)
    await flush_user_cache_immediately(chat_id, target_id)

    if len(warns) >= Cfg.MAX_WARNS:
        await update_user_field(chat_id, target_id, "is_banned", True)
        await flush_user_cache_immediately(chat_id, target_id)
        try:
            await callback.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ban_chat_member failed: %s", exc)
        await safe_answer(callback, f"Варн выдан! Бан за {Cfg.MAX_WARNS}/{Cfg.MAX_WARNS} варнов.", show_alert=True)
    else:
        await safe_answer(callback, f"Предупреждение выдано. Всего: {len(warns)}/{Cfg.MAX_WARNS}")

    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_pwr_"))
@creator_only
async def cb_remove_user_warn(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    data = await get_user_data(chat_id, target_id)
    warns = list(data.get("warns", []) or [])
    if warns:
        warns.pop()
        await update_user_field(chat_id, target_id, "warns", warns)
        await flush_user_cache_immediately(chat_id, target_id)
        await safe_answer(callback, f"Варн снят. Осталось: {len(warns)}/{Cfg.MAX_WARNS}")
    else:
        await safe_answer(callback, "У этого игрока нет предупреждений.", show_alert=True)
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_pwi_"))
@creator_only
async def cb_confirm_player_wipe_screen(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    text = (
        f"⚠️ <b>ВНИМАНИЕ: Вайп игрока</b>\n\n"
        f"Полностью обнулить профиль игрока ID <code>{target_id}</code>?\n"
        f"Будут сброшены деньги, инвентарь, бизнесы, крипта, питомцы и скиллы. Необратимо!"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🧹 Подтвердить полный сброс", callback_data=f"db_pwic_{chat_id}_{target_id}")
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pwic_"))
@creator_only
async def cb_perform_player_wipe(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    from user_manager import wipe_user_data
    success = await wipe_user_data(chat_id, target_id)
    if success:
        logger.info("Player %s wiped (chat %s)", target_id, chat_id)
        await safe_answer(callback, "Данные игрока полностью обнулены!", show_alert=True)
    else:
        await safe_answer(callback, "Не удалось сбросить данные.", show_alert=True)
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_pma_"))
@creator_only
async def cb_player_money_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    await state.set_state(AdminPanelState.waiting_for_player_money_add)
    await state.update_data(chat_id=chat_id, target_user_id=target_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    await safe_edit(
        callback.message,
        "💵 <b>Выдача сыроежек игроку</b>\n\n"
        "Введите сумму (для списания со знаком минус, например -500000):",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_money_add)
@creator_only
async def process_player_money_add(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    val = parse_int(message.text)
    if val is None:
        await message.answer("❌ Сумма должна быть целым числом. Попробуйте ещё раз:")
        return
    await update_user_balance(chat_id, target_id, val, action="Creator Panel Give")
    await flush_user_cache_immediately(chat_id, target_id)
    await message.answer(f"✅ Баланс изменён на {val:+,} сыроежек.")
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_pms_"))
@creator_only
async def cb_player_money_set_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    await state.set_state(AdminPanelState.waiting_for_player_money_set)
    await state.update_data(chat_id=chat_id, target_user_id=target_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    await safe_edit(
        callback.message,
        "💰 <b>Установка точного баланса</b>\n\nВведите новую сумму наличного баланса:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_money_set)
@creator_only
async def process_player_money_set(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    val = parse_int(message.text, allow_negative=False, minimum=0)
    if val is None:
        await message.answer("❌ Введите корректное положительное число:")
        return
    await update_user_field(chat_id, target_id, "balance", val)
    await flush_user_cache_immediately(chat_id, target_id)
    await message.answer(f"✅ Установлен баланс: {fmt_money(val)} сыроежек.")
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


# ==============================================================================
#  РАЗДЕЛ: НАСТРОЙКИ ГРУППЫ
# ==============================================================================
@router.callback_query(F.data.startswith("db_g_"))
@creator_only
async def cb_group_settings_view(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    spy_chats = await get_spy_chats()
    locked_chats = await get_locked_chats()

    spy_status = "👁 ВКЛЮЧЕН" if chat_id in spy_chats else "🙈 Выключен"
    lock_status = "🔒 Заблокирована" if chat_id in locked_chats else "🔓 Штатный режим"

    admin_status = "Неизвестно"
    try:
        bot_member = await callback.bot.get_chat_member(chat_id, callback.bot.id)
        admin_status = ("✅ Да (Админ)" if bot_member.status in ("administrator", "creator")
                        else f"❌ Нет ({bot_member.status})")
    except Exception as exc:  # noqa: BLE001
        admin_status = f"❌ Ошибка проверки ({exc})"

    text = (
        f"⚙️ <b>Панель управления чатом</b>\n\n"
        f"ID Группы: <code>{chat_id}</code>\n"
        f"👁 Шпионаж сообщений: <b>{spy_status}</b>\n"
        f"🔒 Ограничение работы (/lockbot): <b>{lock_status}</b>\n"
        f"🤖 Права бота в группе: <b>{admin_status}</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Экспортировать инвайт-ссылку", callback_data=f"db_gl_{chat_id}")
    builder.button(text="👁 Режим Шпиона +/-", callback_data=f"db_gs_{chat_id}")
    builder.button(text="🔒 Лок бота +/-", callback_data=f"db_glk_{chat_id}")
    builder.button(text="📣 Написать сообщение (say)", callback_data=f"db_gsy_{chat_id}")
    builder.button(text="⬅️ Назад к меню", callback_data=f"db_m_{chat_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_gs_"))
@creator_only
async def cb_toggle_group_spy(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    is_enabled = await toggle_spy(chat_id)
    await safe_answer(callback, f"Режим шпионажа {'включён' if is_enabled else 'выключен'}.", show_alert=True)
    await cb_group_settings_view(callback, state)


@router.callback_query(F.data.startswith("db_glk_"))
@creator_only
async def cb_toggle_group_lock(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    is_enabled = await toggle_lock(chat_id)
    status = "заблокирован (нужны права админа)" if is_enabled else "разблокирован"
    await safe_answer(callback, f"Доступ бота {status}.", show_alert=True)
    await cb_group_settings_view(callback, state)


@router.callback_query(F.data.startswith("db_gl_"))
@creator_only
async def cb_export_invite_link(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    try:
        link = await callback.bot.export_chat_invite_link(chat_id=chat_id)
        await callback.message.answer(f"🔗 Ссылка на группу <code>{chat_id}</code>:\n{link}")
        await safe_answer(callback, "Ссылка экспортирована!")
    except Exception as exc:  # noqa: BLE001
        await safe_answer(callback, f"❌ Ошибка экспорта: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("db_gsy_"))
@creator_only
async def cb_group_say_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    await state.set_state(AdminPanelState.waiting_for_say_text)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="🛑 Остановить трансляцию", callback_data=f"db_stop_say_{chat_id}")
    await safe_edit(
        callback.message,
        "📣 <b>Трансляция сообщений в группу</b>\n\n"
        "Все ваши сообщения (текст, фото, стикеры, GIF) будут пересылаться в группу.\n\n"
        "Для завершения нажмите кнопку ниже:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_stop_say_"))
@creator_only
async def cb_stop_group_say(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3)
    await state.clear()
    await safe_answer(callback, "Трансляция остановлена")
    await cb_group_settings_view(MockCallback(callback.message, callback.message.message_id, f"db_g_{chat_id}"), state)


@router.message(AdminPanelState.waiting_for_say_text)
@creator_only
async def process_group_say_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not chat_id:
        return
    try:
        await message.send_copy(chat_id=chat_id)
        await notify_and_autodelete(message, "✅ Отправлено", Cfg.AUTODELETE_OK)
    except Exception as exc:  # noqa: BLE001
        await notify_and_autodelete(message, f"❌ Ошибка отправки: {exc}", Cfg.AUTODELETE_ERR)
    await safe_delete(message)


# ==============================================================================
#  РАЗДЕЛ: ГЛОБАЛЬНЫЕ НАСТРОЙКИ
# ==============================================================================
@router.callback_query(F.data.startswith("db_glob_"))
@creator_only
async def cb_global_settings_view(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2, default=0)
    tax = await get_global_tax()

    chances_text = ""
    for game_id, game_title in GAMES_CHANCE_LIST:
        ch = await get_game_chance(game_id)
        if game_id == "crash":
            crash_hint = f"{100 - ch}%" if ch != -1 else "10%"
            chances_text += f"  • {game_title}: <b>{fmt_chance(ch)}</b> (Ист. краш: {crash_hint})\n"
        else:
            chances_text += f"  • {game_title}: <b>{fmt_chance(ch)}</b>\n"

    from utils import check_maintenance
    maint_mode = await check_maintenance()
    maint_status = "🔴 ВКЛЮЧЕН (Тех. работы)" if maint_mode else "🟢 ВЫКЛЮЧЕН (Штатная работа)"

    text = (
        f"🌍 <b>Глобальные настройки бота</b>\n\n"
        f"🛠 Режим тех. работ: <b>{maint_status}</b>\n"
        f"💸 Базовый налог на переводы: <b>{tax}%</b>\n\n"
        f"🎰 Установленные шансы побед:\n{chances_text}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🛠 Тех. работы +/-", callback_data=f"db_gtm_{chat_id}")
    builder.button(text="📡 Рассылка (Broadcast)", callback_data=f"db_gbroadcast_prompt_{chat_id}")
    builder.button(text="💸 Изменить налог", callback_data=f"db_gt_{chat_id}")
    builder.button(text="🎰 Настройка шансов победы", callback_data=f"db_gch_{chat_id}")
    builder.button(text="📝 Белый список групп", callback_data=f"db_gwl_{chat_id}")
    builder.button(text="🏷 Управление промокодами", callback_data=f"db_promos_list_{chat_id}")
    builder.button(text="🧹 Глобальный вайп экономики", callback_data=f"db_gwipes_{chat_id}")
    
    # Новые разделы управления
    builder.button(text="📦 Резервные копии (Бэкапы)", callback_data=f"db_backups_menu_{chat_id}")
    builder.button(text="🪙 Управление криптой", callback_data=f"db_crypto_menu_{chat_id}")
    builder.button(text="🤖 Дополнительные команды", callback_data=f"db_extra_cmds_{chat_id}")

    if chat_id != 0:
        builder.button(text="⬅️ Назад к меню группы", callback_data=f"db_m_{chat_id}")
    else:
        builder.button(text="⬅️ К выбору чатов", callback_data="db_sc_0")
    builder.adjust(2, 2, 2, 1, 1, 1, 1, 1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_gt_"))
@creator_only
async def cb_global_tax_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    await state.set_state(AdminPanelState.waiting_for_global_tax)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_glob_{chat_id}")
    await safe_edit(
        callback.message,
        "💸 <b>Изменение базовой ставки налога</b>\n\n"
        f"Введите новый процент налога (целое число от {Cfg.MIN_TAX} до {Cfg.MAX_TAX}).\n"
        "<i>(Все группы будут оповещены)</i>",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_global_tax)
@creator_only
async def process_global_tax_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    tax = parse_int(message.text, allow_negative=False, minimum=Cfg.MIN_TAX, maximum=Cfg.MAX_TAX)
    if tax is None:
        await message.answer(f"❌ Налог должен быть целым от {Cfg.MIN_TAX} до {Cfg.MAX_TAX}:")
        return

    await set_global_tax(tax)
    whitelist = await get_whitelist()
    announcement = (
        f"🏛 <b>Указ Казначейства:</b> Налоговая ставка изменена. Теперь налог составляет <b>{tax}%</b>."
        if tax >= 15 else
        f"📢 <b>Экономические реформы:</b> Базовый налог на переводы установлен на уровне <b>{tax}%</b>."
    )

    notified = 0
    for cid in whitelist.keys():
        try:
            await message.bot.send_message(chat_id=cid, text=announcement)
            notified += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("tax announce failed for %s: %s", cid, exc)

    await message.answer(f"✅ Базовый налог установлен на {tax}%. Уведомлено {notified} чатов.")
    await state.clear()
    if chat_id != 0:
        await show_group_main_screen(message, state, chat_id)
    else:
        await show_chat_select_screen(message, state)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_gch_"))
@creator_only
async def cb_game_chances_menu(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    chances_text = ""
    builder = InlineKeyboardBuilder()
    for game_id, game_title in GAMES_CHANCE_LIST:
        ch = await get_game_chance(game_id)
        if game_id == "crash":
            ch_str = f"{ch}% (Ист. краш: {100 - ch}%)" if ch != -1 else "Честный рандом"
        else:
            ch_str = fmt_chance(ch)
        chances_text += f"  • {game_title}: <b>{ch_str}</b>\n"
        btn_label = game_title.split("(")[0].strip()
        btn_label = "".join(c for c in btn_label if ord(c) < 127 or ord(c) > 255).strip()
        if not btn_label:
            btn_label = game_id.upper()
        builder.button(text=btn_label, callback_data=f"db_gsc_{chat_id}_{game_id}")

    text = (
        f"🎰 <b>Настройка принудительных шансов победы</b>\n\n"
        f"Укажите игру для изменения шанса:\n\n{chances_text}"
    )
    builder.button(text="⬅️ Назад к настройкам", callback_data=f"db_glob_{chat_id}")
    builder.adjust(2, 2, 2, 2, 1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_gsc_"))
@creator_only
async def cb_game_chance_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 2)
    game_name = parts[3] if len(parts) > 3 else ""
    await state.set_state(AdminPanelState.waiting_for_chance_val)
    await state.update_data(chat_id=chat_id, game_name=game_name,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_gch_{chat_id}")
    await safe_edit(
        callback.message,
        f"🎰 <b>Настройка шанса для игры: {game_name.upper()}</b>\n\n"
        f"Введите процент ({Cfg.MIN_CHANCE}-{Cfg.MAX_CHANCE}) принудительной победы.\n"
        f"<i>(Введите -1 для честного рандома)</i>:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_chance_val)
@creator_only
async def process_game_chance_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, game_name = data["chat_id"], data["game_name"]
    val = parse_int(message.text, minimum=Cfg.MIN_CHANCE, maximum=Cfg.MAX_CHANCE)
    if val is None:
        await message.answer(f"❌ Процент должен быть числом от {Cfg.MIN_CHANCE} до {Cfg.MAX_CHANCE}:")
        return

    await set_game_chance(game_name, val)
    msg = (f"✅ Для игры <b>{game_name}</b> установлен шанс победы: {val}%"
           if val != -1 else f"✅ В игре <b>{game_name}</b> включён честный рандом.")
    await message.answer(msg)
    await state.clear()
    await cb_game_chances_menu(
        MockCallback(message, data.get("menu_message_id"), f"db_gch_{chat_id}"), state
    )
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_gwl_"))
@creator_only
async def cb_whitelist_view(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    whitelist = await get_whitelist()
    text = "📝 <b>Управление Белым Списком групп</b>\n\nСписок разрешённых чатов:"
    builder = InlineKeyboardBuilder()
    if not whitelist:
        text += "\n<i>Список пуст.</i>"
    else:
        for cid, title in whitelist.items():
            builder.button(text=f"❌ {escape_html(title)} ({cid})",
                           callback_data=f"db_gwlr_{chat_id}_{cid}")
    builder.button(text="➕ Разрешить чат (Добавить ID)", callback_data=f"db_gwla_{chat_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_gwlr_"))
@creator_only
async def cb_whitelist_remove_perform(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, remove_id = cb_int(parts, 2), cb_int(parts, 3)
    success = await remove_from_whitelist(remove_id)
    await safe_answer(callback,
                      f"Группа {remove_id} удалена." if success else "Ошибка удаления.")
    await cb_whitelist_view(callback, state)


@router.callback_query(F.data.startswith("db_gwla_"))
@creator_only
async def cb_whitelist_add_id_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    await state.set_state(AdminPanelState.waiting_for_whitelist_id)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_gwl_{chat_id}")
    await safe_edit(
        callback.message,
        "📝 <b>Добавление группы в белый список</b>\n\n"
        "Шаг 1: Введите числовой ID группы (обычно начинается с -100):",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_whitelist_id)
@creator_only
async def process_whitelist_id_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    cid = parse_int(message.text)
    if cid is None:
        await message.answer("❌ ID чата должен быть целым числом. Попробуйте ещё раз:")
        return
    await state.set_state(AdminPanelState.waiting_for_whitelist_title)
    await state.update_data(target_chat_id=cid)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_gwl_{chat_id}")
    await message.answer(
        f"📝 <b>Добавление группы {cid}</b>\n\nШаг 2: Введите название для этой группы:",
        reply_markup=builder.as_markup(),
    )
    await safe_delete(message)


@router.message(AdminPanelState.waiting_for_whitelist_title)
@creator_only
async def process_whitelist_title_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, cid = data["chat_id"], data["target_chat_id"]
    title = message.text.strip()
    await add_to_whitelist(cid, title)
    logger.info("Whitelist: added %s ('%s')", cid, title)
    await message.answer(f"✅ Группа <b>{escape_html(title)}</b> ({cid}) добавлена в белый список.")
    await state.clear()
    await cb_whitelist_view(
        MockCallback(message, data.get("menu_message_id"), f"db_gwl_{chat_id}"), state
    )
    await safe_delete(message)


# ==============================================================================
#  ГЛОБАЛЬНЫЕ ВАЙПЫ ЭКОНОМИКИ
# ==============================================================================
@router.callback_query(F.data.startswith("db_gwipes_"))
@creator_only
async def cb_global_wipes_menu(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    text = (
        f"🧹 <b>Глобальные вайпы экономики бота</b>\n\n"
        f"⚠️ <b>ВНИМАНИЕ:</b> Действия затрагивают ВСЕХ игроков во ВСЕХ чатах!\n\n"
        f"• <b>Сброс балансов</b>: наличные и вклады до {Cfg.WIPE_RESET_BALANCE} сыр.\n"
        f"• <b>Средний вайп</b>: деньги, инвентари, VIP, перезапуск биржи.\n"
        f"• <b>Полный вайп</b>: деньги, инвентари, долги, питомцы, скиллы, кланы, крипта."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Сбросить балансы (Только деньги)", callback_data=f"db_gwc_{chat_id}_balances")
    builder.button(text="📦 Средний вайп экономики", callback_data=f"db_gwc_{chat_id}_mid")
    builder.button(text="🔥 Полный вайп экономики (Глобально)", callback_data=f"db_gwc_{chat_id}_economy")
    builder.button(text="⬅️ Назад", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


def _default_crypto_coins() -> dict:
    """Дефолтный набор криптовалют при перезапуске биржи."""
    return {
        "chsyr": {"name": "Китайская Сыроежка", "ticker": "CH_SYR",
                  "prices": [random.randint(100, 500)], "creator": 0},
        "espsyr": {"name": "Испанская Сыроежка", "ticker": "ESP_SYR",
                   "prices": [random.randint(100, 500)], "creator": 0},
    }


async def _wipe_chats(whitelist: dict, fields: dict,
                      wipe_clans: bool = False) -> tuple[int, int]:
    """
    Батч-обновление пользователей (и опционально кланов) во всех чатах.
    Возвращает (users_wiped, clans_wiped).
    """
    db = get_db()
    users_wiped, clans_wiped = 0, 0

    for cid in whitelist.keys():
        users_ref = db.collection("chats").document(str(cid)).collection("users")
        user_docs = await users_ref.get()

        batch = db.batch()
        count = 0
        for doc in user_docs:
            if not doc.id:
                continue
            batch.set(users_ref.document(doc.id), fields, merge=True)
            users_wiped += 1
            count += 1
            if count >= Cfg.WIPE_BATCH_SIZE:
                await batch.commit()
                batch = db.batch()
                count = 0

        if wipe_clans:
            clans_ref = db.collection("chats").document(str(cid)).collection("clans")
            for cdoc in await clans_ref.get():
                if not cdoc.id:
                    continue
                batch.set(clans_ref.document(cdoc.id), {"treasury": 0}, merge=True)
                clans_wiped += 1
                count += 1
                if count >= Cfg.WIPE_BATCH_SIZE:
                    await batch.commit()
                    batch = db.batch()
                    count = 0

        if count > 0:
            await batch.commit()

    return users_wiped, clans_wiped


@router.callback_query(F.data.startswith("db_gwc_"))
@creator_only
async def cb_global_wipe_action(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 2)
    wipe_type = parts[3] if len(parts) > 3 else ""

    # Двойное подтверждение
    if len(parts) < 5 or parts[4] != "confirmed":
        type_names = {
            "balances": "Сброс балансов (Soft-Wipe)",
            "mid": "Средний вайп экономики",
            "economy": "ГЛОБАЛЬНЫЙ ВАЙП ЭКОНОМИКИ",
        }
        text = (
            f"🚨 <b>ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ!</b> 🚨\n\n"
            f"Действие: <b>{type_names.get(wipe_type, wipe_type)}</b>\n"
            f"Затронет всех игроков бота. Вы абсолютно уверены?"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="💥 ПОДТВЕРДИТЬ СБРОС", callback_data=f"db_gwc_{chat_id}_{wipe_type}_confirmed")
        builder.button(text="❌ Отмена", callback_data=f"db_gwipes_{chat_id}")
        builder.adjust(1)
        await safe_edit(callback.message, text, builder.as_markup())
        return await safe_answer(callback)

    status_msg = await callback.message.answer("🔄 <i>Начинаю сброс экономики. Подождите...</i>")
    _user_cache.clear()
    whitelist = await get_whitelist()
    db = get_db()

    try:
        if wipe_type == "balances":
            users_wiped, _ = await _wipe_chats(whitelist, {"balance": Cfg.WIPE_RESET_BALANCE, "bank_deposit": 0})
            await safe_edit(status_msg, f"✅ <b>Вайп балансов завершён!</b>\n👤 Обнулено игроков: <b>{users_wiped}</b>.")

        elif wipe_type == "mid":
            await db.collection("bot_settings").document("crypto_coins").set(
                {"coins": _default_crypto_coins(), "last_update": int(time.time())}
            )
            users_wiped, _ = await _wipe_chats(
                whitelist, {"balance": Cfg.WIPE_RESET_BALANCE, "inventory": {}, "is_vip": False}
            )
            await safe_edit(status_msg,
                            f"✅ <b>Средний вайп завершён!</b>\n👤 Обнулено игроков: <b>{users_wiped}</b>\n📈 Биржа перезапущена.")

        elif wipe_type == "economy":
            await db.collection("bot_settings").document("crypto_coins").set(
                {"coins": _default_crypto_coins(), "last_update": int(time.time())}
            )
            users_wiped, clans_wiped = await _wipe_chats(
                whitelist,
                {"balance": Cfg.WIPE_RESET_BALANCE, "bank_deposit": 0, "inventory": {},
                 "debts": {}, "skills": {}, "pet": None},
                wipe_clans=True,
            )
            await safe_edit(status_msg,
                            f"✅ <b>Глобальный сброс экономики завершён!</b>\n"
                            f"👤 Игроков: <b>{users_wiped}</b>\n🛡 Кланов: <b>{clans_wiped}</b>\n📈 Биржа сброшена.")

        logger.warning("Global wipe '%s' executed by %s", wipe_type, callback.from_user.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Global wipe failed: %s", exc)
        await safe_edit(status_msg, f"❌ Ошибка вайпа: {exc}")

    await safe_answer(callback, "Экономика сброшена!", show_alert=True)
    await asyncio.sleep(Cfg.WIPE_RESULT_HOLD)
    await cb_global_wipes_menu(callback, state)


# ==============================================================================
#  УПРАВЛЕНИЕ ЗППП ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_pdiseases_menu_"))
@creator_only
async def cb_pdiseases_menu(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    from diseases import get_active_diseases, DISEASES
    active = await get_active_diseases(chat_id, target_id)
    active_names = [DISEASES[d]["name"] for d in active if d in DISEASES]
    status_text = ", ".join(active_names) if active_names else "Здоров(а)"

    text = (
        f"🩺 <b>Управление заболеваниями (ЗППП)</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n"
        f"🦠 Активные болезни: <b>{status_text}</b>\n\nВыберите действие:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🧼 Вылечить всё", callback_data=f"db_pdis_cure_{chat_id}_{target_id}")
    builder.button(text="🤮 Полный букет ЗППП", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_fullhouse")
    for d_id, d_info in DISEASES.items():
        prefix = "🟢" if d_id in active else "🦠"
        builder.button(text=f"{prefix} {d_info['name']}",
                       callback_data=f"db_pdis_inf_{chat_id}_{target_id}_{d_id}")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(*([2] + [2] * ((len(DISEASES) + 1) // 2) + [1]))
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pdis_cure_"))
@creator_only
async def cb_pdis_cure(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    await update_user_field(chat_id, target_id, "diseases", {})
    await flush_user_cache_immediately(chat_id, target_id)
    await safe_answer(callback, "✅ Все болезни вылечены!", show_alert=True)
    await cb_pdiseases_menu(callback, state)


@router.callback_query(F.data.startswith("db_pdis_inf_"))
@creator_only
async def cb_pdis_inf(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    disease_id = parts[5] if len(parts) > 5 else ""
    from diseases import infect_full_house, DISEASES

    if disease_id == "fullhouse":
        await infect_full_house(chat_id, target_id)
        await safe_answer(callback, "✅ Игрок заражён всеми болезнями!", show_alert=True)
    else:
        data = await get_user_data(chat_id, target_id)
        current = data.get("diseases")
        if not isinstance(current, dict):
            current = {}
        current[disease_id] = time.time() + Cfg.DISEASE_INFECT_SECONDS
        await update_user_field(chat_id, target_id, "diseases", current)
        d_name = DISEASES.get(disease_id, {}).get("name", disease_id)
        await safe_answer(callback, f"✅ Игрок заражён: {d_name}!", show_alert=True)

    await flush_user_cache_immediately(chat_id, target_id)
    await cb_pdiseases_menu(callback, state)


# ==============================================================================
#  УПРАВЛЕНИЕ ИНВЕНТАРЁМ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_pim_"))
@creator_only
async def cb_pinv_menu(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    data = await get_user_data(chat_id, target_id)
    inventory = data.get("inventory", {}) or {}
    from shop import ITEMS
    inv_lines = [f"• {ITEMS.get(k, {}).get('name', k)}: <b>{v} шт.</b>" for k, v in inventory.items()]
    inv_text = "\n".join(inv_lines) if inv_lines else "<i>Инвентарь пуст.</i>"

    text = (
        f"🎒 <b>Управление инвентарём</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n\n"
        f"<b>Текущие вещи:</b>\n{inv_text}\n\nВыберите категорию:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🏢 Бизнесы", callback_data=f"db_pic_{chat_id}_{target_id}_biz")
    builder.button(text="🚗 Машины", callback_data=f"db_pic_{chat_id}_{target_id}_cars")
    builder.button(text="🎒 Прочее", callback_data=f"db_pic_{chat_id}_{target_id}_other")
    builder.button(text="🧹 Очистить инвентарь", callback_data=f"db_pia_{chat_id}_{target_id}_clear")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(3, 1, 1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pic_"))
@creator_only
async def cb_pinv_cat(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    cat = parts[4] if len(parts) > 4 else "other"
    data = await get_user_data(chat_id, target_id)
    inventory = data.get("inventory", {}) or {}
    from shop import ITEMS
    cat_names = {"biz": "🏢 Бизнесы", "cars": "🚗 Машины", "other": "🎒 Разное"}

    text = (
        f"🎒 <b>Категория: {cat_names.get(cat, cat)}</b>\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n\n"
        f"Нажимайте ➖ или ➕ для изменения количества:"
    )
    builder = InlineKeyboardBuilder()
    rows = 0
    for item_id, item_cfg in ITEMS.items():
        if item_cfg.get("cat") != cat:
            continue
        qty = inventory.get(item_id, 0)
        item_name = item_cfg.get("name", item_id)
        builder.button(text="➖", callback_data=f"db_pich_{chat_id}_{target_id}_{item_id}_m_{cat}")
        builder.button(text=f"{item_name} ({qty})", callback_data=f"db_piq_{chat_id}_{target_id}_{item_id}_{cat}")
        builder.button(text="➕", callback_data=f"db_pich_{chat_id}_{target_id}_{item_id}_p_{cat}")
        rows += 1
    builder.button(text="⬅️ Назад к категориям", callback_data=f"db_pim_{chat_id}_{target_id}")
    builder.adjust(*([3] * rows + [1]))
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pich_"))
@creator_only
async def cb_pinv_change(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    item_id = parts[4]
    action = parts[5]
    cat = parts[6]

    data = await get_user_data(chat_id, target_id)
    inventory = dict(data.get("inventory", {}) or {})
    current_qty = inventory.get(item_id, 0)

    if action == "p":
        inventory[item_id] = current_qty + 1
        await safe_answer(callback, "➕ Количество увеличено!")
    elif action == "m":
        if current_qty <= 0:
            return await safe_answer(callback, "❌ Предмета уже 0 в инвентаре!", show_alert=True)
        if current_qty == 1:
            del inventory[item_id]
        else:
            inventory[item_id] = current_qty - 1
        await safe_answer(callback, "➖ Количество уменьшено!")

    await update_user_field(chat_id, target_id, "inventory", inventory)
    asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))

    # Перерисовка категории без вложенного класса (исправлен баг)
    callback.data = f"db_pic_{chat_id}_{target_id}_{cat}"
    await cb_pinv_cat(callback, state)


@router.callback_query(F.data == "db_noop")
async def cb_noop(callback: types.CallbackQuery):
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pia_"))
@creator_only
async def cb_pinv_act(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    action = parts[4] if len(parts) > 4 else ""
    if action == "clear":
        await update_user_field(chat_id, target_id, "inventory", {})
        asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))
        await safe_answer(callback, "✅ Инвентарь очищен!", show_alert=True)
        await cb_pinv_menu(callback, state)


@router.callback_query(F.data.startswith("db_piq_"))
@creator_only
async def cb_player_inv_qty_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    item_id = parts[4]
    cat = parts[5]
    data = await get_user_data(chat_id, target_id)
    current_qty = (data.get("inventory", {}) or {}).get(item_id, 0)
    from shop import ITEMS
    item_name = ITEMS.get(item_id, {}).get("name", item_id)

    await state.set_state(AdminPanelState.waiting_for_player_inv_qty)
    await state.update_data(chat_id=chat_id, target_user_id=target_id, item_id=item_id,
                            cat=cat, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pic_{chat_id}_{target_id}_{cat}")
    await safe_edit(
        callback.message,
        f"🎒 <b>Изменение количества</b>\n\n"
        f"Предмет: <b>{item_name}</b>\nТекущее: <b>{current_qty} шт.</b>\n\n"
        f"Введите новое количество (от {Cfg.MIN_INV_QTY} до {Cfg.MAX_INV_QTY}):",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_inv_qty)
@creator_only
async def process_player_inv_qty_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    item_id, cat = data["item_id"], data["cat"]
    val = parse_int(message.text, allow_negative=False, minimum=Cfg.MIN_INV_QTY, maximum=Cfg.MAX_INV_QTY)
    if val is None:
        await message.answer(f"❌ Количество — целое от {Cfg.MIN_INV_QTY} до {Cfg.MAX_INV_QTY}:")
        return

    inv = dict((await get_user_data(chat_id, target_id)).get("inventory", {}) or {})
    if val == 0:
        inv.pop(item_id, None)
    else:
        inv[item_id] = val
    await update_user_field(chat_id, target_id, "inventory", inv)
    asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))

    await message.answer(f"✅ Количество установлено в {val}.")
    await state.clear()
    await cb_pinv_cat(
        MockCallback(message, data["menu_message_id"], f"db_pic_{chat_id}_{target_id}_{cat}"), state
    )
    await safe_delete(message)


# ==============================================================================
#  ДОПОЛНИТЕЛЬНЫЙ ФУНКЦИОНАЛ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_prep_prompt_"))
@creator_only
async def cb_player_reputation_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    await state.set_state(AdminPanelState.waiting_for_player_reputation)
    await state.update_data(chat_id=chat_id, target_user_id=target_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    await safe_edit(
        callback.message,
        "📈 <b>Изменение репутации</b>\n\nВведите целое число (может быть отрицательным):",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_reputation)
@creator_only
async def process_player_reputation_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    val = parse_int(message.text)
    if val is None:
        await message.answer("❌ Репутация — целое число. Попробуйте ещё раз:")
        return
    await update_user_field(chat_id, target_id, "reputation", val)
    await flush_user_cache_immediately(chat_id, target_id)
    await message.answer(f"✅ Репутация установлена в {val}.")
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_pesc_prompt_"))
@creator_only
async def cb_player_escort_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    await state.set_state(AdminPanelState.waiting_for_player_escort)
    await state.update_data(chat_id=chat_id, target_user_id=target_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    await safe_edit(
        callback.message,
        "🔞 <b>Изменение счётчика</b>\n\nВведите неотрицательное целое число:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_escort)
@creator_only
async def process_player_escort_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    val = parse_int(message.text, allow_negative=False, minimum=0)
    if val is None:
        await message.answer("❌ Введите неотрицательное целое число:")
        return
    await update_user_field(chat_id, target_id, "escort_count", val)
    await flush_user_cache_immediately(chat_id, target_id)
    await message.answer(f"✅ Счётчик установлен в {val}.")
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_prole_prompt_"))
@creator_only
async def cb_player_role_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    await state.set_state(AdminPanelState.waiting_for_player_role)
    await state.update_data(chat_id=chat_id, target_user_id=target_id,
                            menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    await safe_edit(
        callback.message,
        "🎭 <b>Изменение роли</b>\n\n"
        "Введите название особой роли (например, Король, Люцифер).\n"
        "Чтобы удалить роль, введите <code>none</code> или <code>отмена</code>:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_player_role)
@creator_only
async def process_player_role_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    text = message.text.strip()
    role_lower = text.lower()
    clear_words = {"none", "отмена", "clear", "сбросить", "удалить"}

    if role_lower not in clear_words and ("создатель" in role_lower or "creator" in role_lower):
        if target_id not in CREATOR_IDS:
            await message.answer("❌ Роль 'Создатель' доступна только разработчикам бота.")
            await show_player_details_screen(message, state, chat_id, target_id)
            await safe_delete(message)
            return

    if role_lower in clear_words:
        role_val = None
        success_text = "❌ Особая роль удалена."
    else:
        role_val = text
        success_text = f"✅ Роль установлена в: <b>{escape_html(role_val)}</b>."

    await update_user_field(chat_id, target_id, "custom_role", role_val)
    await flush_user_cache_immediately(chat_id, target_id)
    await message.answer(success_text)
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


# ==============================================================================
#  ПИТОМЦЫ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_ppet_menu_"))
@creator_only
async def cb_player_pet_menu(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    data = await get_user_data(chat_id, target_id)
    pet = data.get("pet")
    from pets import PETS_SHOP
    pet_text = "Нет питомца"
    if isinstance(pet, dict):
        p_name = PETS_SHOP.get(pet.get("id"), {}).get("name", pet.get("id"))
        fed_hours_ago = (time.time() - pet.get("last_fed", 0)) / 3600
        pet_text = (f"{p_name} (Сбежал/Голодает)" if fed_hours_ago > Cfg.PET_STARVE_HOURS
                    else f"{p_name} (Сыт, кормили {int(fed_hours_ago)}ч назад)")

    text = (
        f"🐾 <b>Управление питомцем</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n🐾 Питомец: <b>{pet_text}</b>\n\nВыберите действие:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🐱 Выдать Кота", callback_data=f"db_ppet_act_{chat_id}_{target_id}_set_cat")
    builder.button(text="🐶 Выдать Собаку", callback_data=f"db_ppet_act_{chat_id}_{target_id}_set_dog")
    builder.button(text="🐉 Выдать Дракона", callback_data=f"db_ppet_act_{chat_id}_{target_id}_set_dragon")
    builder.button(text="🍗 Покормить питомца", callback_data=f"db_ppet_act_{chat_id}_{target_id}_feed")
    builder.button(text="🗑 Убрать питомца", callback_data=f"db_ppet_act_{chat_id}_{target_id}_remove")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_ppet_act_"))
@creator_only
async def cb_player_pet_act(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    action = parts[5] if len(parts) > 5 else ""
    data = await get_user_data(chat_id, target_id)
    pet = data.get("pet")

    if action == "remove":
        await update_user_field(chat_id, target_id, "pet", None)
        await safe_answer(callback, "🐾 Питомец убран.", show_alert=True)
    elif action == "feed":
        if not isinstance(pet, dict):
            return await safe_answer(callback, "❌ У игрока нет питомца!", show_alert=True)
        pet["last_fed"] = int(time.time())
        await update_user_field(chat_id, target_id, "pet", pet)
        await safe_answer(callback, "🍗 Питомец сыт и доволен!", show_alert=True)
    elif action.startswith("set_"):
        pet_id = action.replace("set_", "")
        await update_user_field(chat_id, target_id, "pet", {"id": pet_id, "last_fed": int(time.time())})
        from pets import PETS_SHOP
        p_name = PETS_SHOP.get(pet_id, {}).get("name", pet_id)
        await safe_answer(callback, f"✅ Выдан питомец: {p_name}!", show_alert=True)

    await flush_user_cache_immediately(chat_id, target_id)
    await cb_player_pet_menu(callback, state)


# ==============================================================================
#  НАВЫКИ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_pskills_menu_"))
@creator_only
async def cb_player_skills_menu(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    data = await get_user_data(chat_id, target_id)
    skills = data.get("skills", {}) or {}
    from skills import SKILLS
    text = f"🎯 <b>Управление навыками</b>\n\n👤 Игрок ID: <code>{target_id}</code>\n\n"
    builder = InlineKeyboardBuilder()
    for sk_id, sk_cfg in SKILLS.items():
        lvl = skills.get(sk_id, 0)
        text += f"{sk_cfg['name']}: <b>{lvl}/{Cfg.MAX_SKILL_LEVEL}</b>\n<i>{sk_cfg['desc']}</i>\n\n"
        builder.button(text=f"➖ {sk_cfg['name']}", callback_data=f"db_psc_{chat_id}_{target_id}_{sk_id}_m")
        builder.button(text=f"➕ {sk_cfg['name']}", callback_data=f"db_psc_{chat_id}_{target_id}_{sk_id}_p")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(2, 2, 2, 1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_psc_"))
@creator_only
async def cb_player_skills_change(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 2), cb_int(parts, 3)
    sk_id = parts[4]
    action = parts[5]
    data = await get_user_data(chat_id, target_id)
    skills = dict(data.get("skills", {}) or {})
    current_lvl = skills.get(sk_id, 0)

    if action == "p":
        if current_lvl >= Cfg.MAX_SKILL_LEVEL:
            return await safe_answer(callback, f"❌ Навык уже на максимуме ({Cfg.MAX_SKILL_LEVEL})!", show_alert=True)
        skills[sk_id] = current_lvl + 1
        await safe_answer(callback, "✅ Уровень навыка повышен!", show_alert=True)
    elif action == "m":
        if current_lvl <= 0:
            return await safe_answer(callback, "❌ Уровень навыка уже 0!", show_alert=True)
        skills[sk_id] = current_lvl - 1
        await safe_answer(callback, "✅ Уровень навыка понижен!", show_alert=True)

    await update_user_field(chat_id, target_id, "skills", skills)
    asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))
    await cb_player_skills_menu(callback, state)


# ==============================================================================
#  ДОЛГИ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_pdebts_menu_"))
@creator_only
async def cb_player_debts_menu(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    data = await get_user_data(chat_id, target_id)
    debts = data.get("debts", {}) or {}

    text = f"💸 <b>Управление долгами</b>\n\n👤 Игрок ID: <code>{target_id}</code>\n\n"
    builder = InlineKeyboardBuilder()
    debt_keys: list = []

    if not debts:
        text += "<i>У игрока нет активных долгов.</i>"
    else:
        for index, (key, val) in enumerate(list(debts.items())):
            debt_keys.append(key)
            if str(key).startswith("bank_"):
                banker_id = str(key).split("_")[1]
                bank_info = await get_bank_info(chat_id, banker_id)
                bank_name = bank_info.get("name", f"Банк {banker_id}") if bank_info else f"Банк {banker_id}"
                line = f"🏦 {escape_html(bank_name)}: <b>{fmt_money(val)}</b> сыр."
            else:
                cred_data = await get_user_data(chat_id, key)
                cred_name = cred_data.get("full_name", f"Игрок {key}") if cred_data else f"Игрок {key}"
                line = f"👤 {escape_html(cred_name)}: <b>{fmt_money(val)}</b> сыр."
            text += f"{index + 1}. {line}\n"
            builder.button(text=f"🗑 Списать долг {index + 1}",
                           callback_data=f"db_pdebts_del_{chat_id}_{target_id}_{index}")

    await state.update_data(debt_keys=debt_keys)
    builder.button(text="➕ Выдать долг", callback_data=f"db_pdebts_add_{chat_id}_{target_id}")
    builder.button(text="🧹 Простить ВСЕ долги", callback_data=f"db_pdebts_clear_{chat_id}_{target_id}")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pdebts_del_"))
@creator_only
async def cb_player_debt_delete(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    index = cb_int(parts, 5)
    state_data = await state.get_data()
    debt_keys = state_data.get("debt_keys", [])

    if index is None or index >= len(debt_keys):
        return await safe_answer(callback, "❌ Ошибка: долг не найден.", show_alert=True)

    key_to_delete = debt_keys[index]
    debts = dict((await get_user_data(chat_id, target_id)).get("debts", {}) or {})
    if key_to_delete in debts:
        del debts[key_to_delete]
        await update_user_field(chat_id, target_id, "debts", debts)
        await flush_user_cache_immediately(chat_id, target_id)
        await safe_answer(callback, "✅ Долг списан!", show_alert=True)
    else:
        await safe_answer(callback, "❌ Долг уже погашен.", show_alert=True)
    await cb_player_debts_menu(callback, state)


@router.callback_query(F.data.startswith("db_pdebts_clear_"))
@creator_only
async def cb_player_debts_clear(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    await update_user_field(chat_id, target_id, "debts", {})
    await flush_user_cache_immediately(chat_id, target_id)
    await safe_answer(callback, "🧹 Все долги прощены!", show_alert=True)
    await cb_player_debts_menu(callback, state)


@router.callback_query(F.data.startswith("db_pdebts_add_"))
@creator_only
async def cb_player_debt_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    banks_docs = await _collect_docs(await banks_collection(chat_id).get())

    text = ("➕ <b>Добавление долга игроку</b>\n\n"
            "Выберите банк-кредитор или введите ID игрока-кредитора в ответ:")
    builder = InlineKeyboardBuilder()
    for doc in banks_docs:
        b_data = doc.to_dict() or {}
        builder.button(text=f"🏦 {b_data.get('name', 'Банк')}",
                       callback_data=f"db_pdebts_cbank_{chat_id}_{target_id}_{doc.id}")
    builder.button(text="❌ Отмена", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
    builder.adjust(1)

    await state.set_state(AdminPanelState.waiting_for_debt_creditor)
    await state.update_data(chat_id=chat_id, target_user_id=target_id,
                            menu_message_id=callback.message.message_id)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_debt_creditor)
@creator_only
async def process_debt_creditor_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    cred_id, cred_data = await get_user_by_username_or_id(chat_id, message.text.strip())
    if not cred_id:
        await message.answer("❌ Кредитор не найден в базе. Попробуйте ещё раз:")
        return

    await state.set_state(AdminPanelState.waiting_for_debt_amount)
    await state.update_data(creditor_key=str(cred_id), creditor_name=cred_data.get("full_name", "Игрок"))
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
    await message.answer(
        f"💰 <b>Выдача долга</b>\nКредитор: <b>{escape_html(cred_data.get('full_name'))}</b>\n\n"
        f"Введите сумму долга (сыроежек):",
        reply_markup=builder.as_markup(),
    )
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_pdebts_cbank_"))
@creator_only
async def cb_player_debt_select_bank(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    banker_id = parts[5]
    bank_info = await get_bank_info(chat_id, banker_id)
    if not bank_info:
        return await safe_answer(callback, "Банк не найден.", show_alert=True)

    debt_key = f"bank_{banker_id}_0_0_0"
    await state.set_state(AdminPanelState.waiting_for_debt_amount)
    await state.update_data(creditor_key=debt_key, creditor_name=bank_info.get("name", "Банк"))
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
    await safe_edit(
        callback.message,
        f"💰 <b>Выдача долга</b>\nКредитор (Банк): <b>{escape_html(bank_info.get('name'))}</b>\n\n"
        f"Введите сумму долга (сыроежек):",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_debt_amount)
@creator_only
async def process_debt_amount_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, target_id = data["chat_id"], data["target_user_id"]
    creditor_key, creditor_name = data["creditor_key"], data["creditor_name"]
    amount = parse_int(message.text, allow_negative=False, minimum=1)
    if amount is None:
        await message.answer("❌ Сумма — целое число больше нуля. Введите повторно:")
        return

    debts = dict((await get_user_data(chat_id, target_id)).get("debts", {}) or {})
    debts[creditor_key] = debts.get(creditor_key, 0) + amount
    await update_user_field(chat_id, target_id, "debts", debts)
    await flush_user_cache_immediately(chat_id, target_id)

    await message.answer(f"✅ Добавлен долг кредитору <b>{escape_html(creditor_name)}</b> на {fmt_money(amount)} сыр.")
    await state.clear()
    await show_player_details_screen(message, state, chat_id, target_id)
    await safe_delete(message)


# ==============================================================================
#  КАЗНЬ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_pexecute_ask_"))
@creator_only
async def cb_player_execute_ask(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    text = (
        f"⚔️ <b>ВЫСШАЯ МЕРА НАКАЗАНИЯ (Казнь)</b>\n\n"
        f"Вы собираетесь казнить игрока ID <code>{target_id}</code>.\n"
        f"Сообщение о казни будет отправлено в чат. Выберите тип приговора:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="💀 Только казнь (Визуальная)", callback_data=f"db_pexecute_do_{chat_id}_{target_id}_visual")
    builder.button(text="🔨 Казнить + Забанить в боте", callback_data=f"db_pexecute_do_{chat_id}_{target_id}_botban")
    builder.button(text="🚨 Казнить + Забанить везде", callback_data=f"db_pexecute_do_{chat_id}_{target_id}_fullban")
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pexecute_do_"))
@creator_only
async def cb_player_execute_do(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    mode = parts[5] if len(parts) > 5 else "visual"
    data = await get_user_data(chat_id, target_id)
    target_name = escape_html(data.get("full_name", "Грешник"))

    from aiogram.types import FSInputFile
    caption = (
        f"⚖️ <b>ВЫСШАЯ МЕРА НАКАЗАНИЯ!</b>\n\n"
        f"Пользователь <b>{target_name}</b> (<code>{target_id}</code>) признан виновным "
        f"в предательстве и приговорён к <b>казни</b>!\n\n"
        f"⚔️ <i>Приговор приведён в исполнение по воле Создателя.</i>\n"
        f"💀 Да смилуются боги над его душой!"
    )
    try:
        if os.path.exists(Cfg.EXECUTION_IMAGE_PATH):
            await callback.bot.send_photo(chat_id=chat_id, photo=FSInputFile(Cfg.EXECUTION_IMAGE_PATH), caption=caption)
        else:
            await callback.bot.send_photo(chat_id=chat_id, photo=Cfg.EXECUTION_FALLBACK_URL, caption=caption)
    except Exception as exc:  # noqa: BLE001
        logger.error("Execution photo failed: %s", exc)
        try:
            await callback.bot.send_message(chat_id=chat_id, text=caption)
        except Exception:
            pass

    if mode in ("botban", "fullban"):
        await update_user_field(chat_id, target_id, "is_banned", True)
        await flush_user_cache_immediately(chat_id, target_id)
    if mode == "fullban":
        try:
            await callback.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("execution ban failed: %s", exc)

    act_text = "Казнь приведена в исполнение!"
    if mode == "botban":
        act_text += " Пользователь забанен в боте."
    elif mode == "fullban":
        act_text += " Пользователь забанен в боте и в чате."
    await safe_answer(callback, act_text, show_alert=True)
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


@router.callback_query(F.data.startswith("db_pfsm_reset_"))
@creator_only
async def cb_player_fsm_reset(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    try:
        from aiogram.fsm.storage.base import StorageKey
        state_to_clear = FSMContext(
            storage=callback.bot.dispatcher.storage,
            key=StorageKey(bot_id=callback.bot.id, chat_id=chat_id, user_id=target_id),
        )
        await state_to_clear.clear()
        await safe_answer(callback, "🔄 Все FSM-состояния игрока сброшены!", show_alert=True)
    except Exception as exc:  # noqa: BLE001
        await safe_answer(callback, f"❌ Ошибка сброса: {exc}", show_alert=True)
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


# ==============================================================================
#  ГЛОБАЛЬНЫЕ ДЕЙСТВИЯ: ТЕХ.РАБОТЫ / РАССЫЛКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_gtm_"))
@creator_only
async def cb_toggle_maintenance(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 2)
    from utils import check_maintenance
    new_val = not await check_maintenance()
    await get_db().collection("bot_settings").document("maintenance").set({"active": new_val})
    try:
        from utils_pkg.cache_manager import global_cache
        global_cache.set("maintenance_mode", new_val, ttl=60)
    except Exception as exc:  # noqa: BLE001
        logger.debug("maintenance cache set failed: %s", exc)
    logger.warning("Maintenance mode -> %s by %s", new_val, callback.from_user.id)
    await safe_answer(callback, f"Режим тех. работ: {new_val}", show_alert=True)
    await cb_global_settings_view(callback, state)


@router.callback_query(F.data.startswith("db_gbroadcast_prompt_"))
@creator_only
async def cb_global_broadcast_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3)
    await state.set_state(AdminPanelState.waiting_for_global_broadcast)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_glob_{chat_id}")
    await safe_edit(
        callback.message,
        "📡 <b>Создание глобальной рассылки</b>\n\n"
        "Введите сообщение, которое будет разослано во все группы из белого списка:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_global_broadcast)
@creator_only
async def process_global_broadcast_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    whitelist = await get_whitelist()

    status_msg = await message.answer(
        f"📡 <b>Рассылка запущена!</b>\nЧатов: {len(whitelist)}\n\nБот оповестит о завершении."
    )
    creator_id = message.from_user.id
    bot = message.bot

    async def run_broadcast_task() -> None:
        success, fail = 0, 0
        for cid in whitelist.keys():
            try:
                await message.send_copy(chat_id=cid)
                success += 1
                await asyncio.sleep(Cfg.BROADCAST_DELAY)
            except Exception as exc:  # noqa: BLE001
                logger.debug("broadcast to %s failed: %s", cid, exc)
                fail += 1
        try:
            await bot.send_message(
                chat_id=creator_id,
                text=(f"✅ <b>Рассылка завершена!</b>\n\n"
                      f"Успешно: <b>{success}</b>\nНе удалось: <b>{fail}</b>"),
            )
        except Exception:
            pass

    try:
        from utils import fire_and_forget
        fire_and_forget(run_broadcast_task())
    except Exception:
        asyncio.create_task(run_broadcast_task())

    await state.clear()
    await cb_global_settings_view(
        MockCallback(message, data.get("menu_message_id"), f"db_glob_{chat_id}"), state
    )
    await safe_delete(message)
    await safe_delete(status_msg)


# ==============================================================================
#  МУТ / РАЗМУТ ИГРОКА
# ==============================================================================
@router.callback_query(F.data.startswith("db_pmute_menu_"))
@creator_only
async def cb_pmute_menu(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    text = (
        f"🔇 <b>Управление мутом</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n🏢 Чат: <code>{chat_id}</code>\n\n"
        f"Выберите длительность:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ 15 минут", callback_data=f"db_pmute_act_{chat_id}_{target_id}_15")
    builder.button(text="⏳ 1 час", callback_data=f"db_pmute_act_{chat_id}_{target_id}_60")
    builder.button(text="⏳ 1 день", callback_data=f"db_pmute_act_{chat_id}_{target_id}_1440")
    builder.button(text="⏳ 7 дней", callback_data=f"db_pmute_act_{chat_id}_{target_id}_10080")
    builder.button(text="🔊 Снять мут", callback_data=f"db_pmute_act_{chat_id}_{target_id}_unmute")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(2, 2, 1, 1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_pmute_act_"))
@creator_only
async def cb_pmute_act(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id, target_id = cb_int(parts, 3), cb_int(parts, 4)
    duration = parts[5] if len(parts) > 5 else "unmute"
    bot = callback.bot
    try:
        if duration == "unmute":
            await bot.restrict_chat_member(
                chat_id=chat_id, user_id=target_id,
                permissions=types.ChatPermissions(
                    can_send_messages=True, can_send_media_messages=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                ),
            )
            await safe_answer(callback, "🔊 Мут снят!", show_alert=True)
        else:
            minutes = int(duration)
            until_date = int(time.time()) + minutes * 60
            await bot.restrict_chat_member(
                chat_id=chat_id, user_id=target_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
            await safe_answer(callback, f"🔇 Игрок замучен на {minutes} мин!", show_alert=True)
            try:
                from log_system import log_action
                log_action(f"🔇 <b>Мут (Панель):</b> {callback.from_user.full_name} "
                           f"замутил {target_id} на {minutes} мин. в чате {chat_id}")
            except Exception as exc:  # noqa: BLE001
                logger.debug("mute log failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        await safe_answer(callback, f"❌ Ошибка: {exc}", show_alert=True)
    await cb_pmute_menu(callback, state)


# ==============================================================================
#  УПРАВЛЕНИЕ КЛАНАМИ — ВСПОМОГАТЕЛЬНОЕ
# ==============================================================================
def get_clan_hash(clan_name: str) -> str:
    """Короткий стабильный хэш имени клана (для callback_data)."""
    return hashlib.md5(clan_name.encode("utf-8")).hexdigest()[:16]


async def get_clan_name_by_hash(chat_id: int, clan_hash: str) -> Optional[str]:
    """Находит исходное имя клана по его хэшу."""
    for doc in await clans_collection(chat_id).get():
        if get_clan_hash(doc.id) == clan_hash:
            return doc.id
    return None


async def parse_clan_callback(callback_data: str) -> tuple[Optional[int], Optional[str], Optional[int]]:
    """
    Универсальный парсер callback'ов кланов (поддержка старого и нового формата).
    Возвращает (chat_id, clan_name, member_id_or_none).
    """
    parts = callback_data.split("_")
    if len(parts) < 4:
        return None, None, None

    # Карта: (короткий_префикс, есть_member, индекс_chat, индекс_hash/member)
    # Для читаемости разбираем явно по группам.
    try:
        # --- view / treasury / leader / dask / dconf / mlist (hash на позиции 4) ---
        short_no_member = {
            "db_clan_view_", "db_clan_treasury_", "db_clan_leader_",
            "db_clan_dask_", "db_clan_dconf_", "db_clan_mlist_",
        }
        for prefix in short_no_member:
            if callback_data.startswith(prefix):
                chat_id = int(parts[3])
                clan_hash = parts[4]
                clan_name = await get_clan_name_by_hash(chat_id, clan_hash) or "_".join(parts[4:])
                return chat_id, clan_name, None

        # --- длинные аналоги (raw name на позиции 4/5) ---
        long_no_member = {
            "db_clan_del_ask_": 4, "db_clan_del_confirm_": 4, "db_clan_members_list_": 4,
        }
        for prefix, chat_idx in long_no_member.items():
            if callback_data.startswith(prefix):
                chat_id = int(parts[chat_idx])
                clan_name = "_".join(parts[chat_idx + 1:])
                return chat_id, clan_name, None

        # --- короткие с member: mem / prom / dem / kck / ltr (member поз.4, hash поз.5) ---
        short_with_member = {
            "db_clan_mem_", "db_clan_prom_", "db_clan_dem_", "db_clan_kck_", "db_clan_ltr_",
        }
        for prefix in short_with_member:
            if callback_data.startswith(prefix):
                chat_id = int(parts[3])
                member_id = int(parts[4])
                clan_hash = parts[5]
                clan_name = await get_clan_name_by_hash(chat_id, clan_hash) or "_".join(parts[5:])
                return chat_id, clan_name, member_id

        # --- длинные с member: member / promote / demote / kick / leadtransfer ---
        long_with_member = {
            "db_clan_member_", "db_clan_promote_", "db_clan_demote_",
            "db_clan_kick_", "db_clan_leadtransfer_",
        }
        for prefix in long_with_member:
            if callback_data.startswith(prefix):
                chat_id = int(parts[3])
                member_id = int(parts[4])
                clan_name = "_".join(parts[5:])
                return chat_id, clan_name, member_id
    except (ValueError, IndexError) as exc:
        logger.debug("parse_clan_callback failed for '%s': %s", callback_data, exc)

    return None, None, None


@router.callback_query(F.data.startswith("db_clans_list_"))
@creator_only
async def cb_clans_list(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id = cb_int(split_cb(callback.data), 3)
    clans_docs = await clans_collection(chat_id).get()

    text = "🛡 <b>Управление кланами чата</b>\n\nВыберите клан:"
    builder = InlineKeyboardBuilder()
    has_clans = False
    for doc in clans_docs:
        c_data = doc.to_dict() or {}
        treasury = c_data.get("treasury", 0)
        builder.button(text=f"🛡 {doc.id} ({fmt_money(treasury)} сыр)",
                       callback_data=f"db_clan_view_{chat_id}_{get_clan_hash(doc.id)}")
        has_clans = True
    if not has_clans:
        text += "\n\n<i>В этой группе ещё не создано ни одного клана.</i>"
    builder.button(text="⬅️ Назад к меню", callback_data=f"db_m_{chat_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


async def show_clan_detail_screen(callback_or_message, state: FSMContext,
                                  chat_id: int, clan_name: str) -> None:
    """Детальный экран клана."""
    clan_ref = clans_collection(chat_id).document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        text = "❌ Клан не найден или был распущен."
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data=f"db_clans_list_{chat_id}")
        if hasattr(callback_or_message, "message"):
            await safe_edit(callback_or_message.message, text, builder.as_markup())
        else:
            await callback_or_message.answer(text, reply_markup=builder.as_markup())
        return

    c_data = doc.to_dict() or {}
    leader_id = c_data.get("leader_id")
    deputies = c_data.get("deputy_ids", [])
    members = c_data.get("members", [])
    treasury = c_data.get("treasury", 0)

    leader_name = "Неизвестный"
    try:
        leader_name = (await get_user_data(chat_id, leader_id)).get("full_name", f"ID: {leader_id}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("leader name fetch failed: %s", exc)

    member_names = []
    for m_id in members:
        try:
            m_name = (await get_user_data(chat_id, m_id)).get("full_name", f"ID: {m_id}")
        except Exception:
            m_name = f"ID: {m_id}"
        if m_id == leader_id:
            role = "👑 Лидер"
        elif m_id in deputies:
            role = "⭐ Зам"
        else:
            role = "👤 Участник"
        member_names.append(f"• <b>{escape_html(m_name)}</b> ({role})")
    members_str = "\n".join(member_names) if member_names else "<i>Нет участников</i>"

    text = (
        f"🛡 <b>Клан: {escape_html(clan_name)}</b>\n\n"
        f"👑 Лидер: <b>{escape_html(leader_name)}</b> (<code>{leader_id}</code>)\n"
        f"💰 Казна клана: <b>{fmt_money(treasury)}</b> сыр.\n\n"
        f"👥 <b>Состав клана ({len(members)}):</b>\n{members_str}"
    )
    builder = InlineKeyboardBuilder()
    c_hash = get_clan_hash(clan_name)
    builder.button(text="💰 Установить казну", callback_data=f"db_clan_treasury_{chat_id}_{c_hash}")
    builder.button(text="👑 Назначить Лидера", callback_data=f"db_clan_leader_{chat_id}_{c_hash}")
    builder.button(text="👥 Управление составом", callback_data=f"db_clan_mlist_{chat_id}_{c_hash}")
    builder.button(text="💥 Распустить клан", callback_data=f"db_clan_dask_{chat_id}_{c_hash}")
    builder.button(text="⬅️ К списку кланов", callback_data=f"db_clans_list_{chat_id}")
    builder.adjust(1)
    markup = builder.as_markup()

    if hasattr(callback_or_message, "message"):
        await safe_edit(callback_or_message.message, text, markup)
    else:
        bot = extract_bot(callback_or_message)
        state_data = await state.get_data()
        msg_id = state_data.get("menu_message_id")
        if msg_id and bot:
            try:
                await bot.edit_message_text(chat_id=callback_or_message.chat.id, message_id=msg_id,
                                            text=text, reply_markup=markup, parse_mode="HTML")
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("clan detail edit failed: %s", exc)
        msg = await callback_or_message.answer(text, reply_markup=markup)
        await state.update_data(menu_message_id=msg.message_id)


@router.callback_query(F.data.startswith("db_clan_view_"))
@creator_only
async def cb_clan_view(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    await show_clan_detail_screen(callback, state, chat_id, clan_name)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_clan_treasury_"))
@creator_only
async def cb_clan_treasury_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    await state.set_state(AdminPanelState.waiting_for_clan_treasury)
    await state.update_data(chat_id=chat_id, clan_name=clan_name, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_clan_view_{chat_id}_{get_clan_hash(clan_name)}")
    await safe_edit(
        callback.message,
        f"💰 <b>Изменение казны клана: {escape_html(clan_name)}</b>\n\nВведите новую сумму казны:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_clan_treasury)
@creator_only
async def process_clan_treasury_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, clan_name = data["chat_id"], data["clan_name"]
    menu_message_id = data.get("menu_message_id")
    val = parse_int(message.text, allow_negative=False, minimum=0)
    if val is None:
        await message.answer("❌ Сумма — положительное целое число. Введите корректно:")
        return

    await clans_collection(chat_id).document(clan_name).update({"treasury": val})
    await message.answer(f"✅ Казна клана <b>{escape_html(clan_name)}</b> изменена на {fmt_money(val)} сыроежек.")
    await state.clear()
    mock_cb = MockCallback(message, menu_message_id, f"db_clan_view_{chat_id}_{get_clan_hash(clan_name)}")
    await show_clan_detail_screen(mock_cb, state, chat_id, clan_name)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_clan_leader_"))
@creator_only
async def cb_clan_leader_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    await state.set_state(AdminPanelState.waiting_for_clan_leader)
    await state.update_data(chat_id=chat_id, clan_name=clan_name, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_clan_view_{chat_id}_{get_clan_hash(clan_name)}")
    await safe_edit(
        callback.message,
        f"👑 <b>Смена лидера клана: {escape_html(clan_name)}</b>\n\nВведите @username или ID нового Лидера:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_clan_leader)
@creator_only
async def process_clan_leader_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, clan_name = data["chat_id"], data["clan_name"]
    menu_message_id = data.get("menu_message_id")
    target_id, target_data = await get_user_by_username_or_id(chat_id, message.text.strip())
    if not target_id:
        await message.answer("❌ Пользователь не найден в базе чата. Попробуйте ещё раз:")
        return

    clan_ref = clans_collection(chat_id).document(clan_name)
    clan_data = (await clan_ref.get()).to_dict() or {}
    members = list(clan_data.get("members", []))
    if target_id not in members:
        members.append(target_id)
    deputy_ids = list(clan_data.get("deputy_ids", []))
    if target_id in deputy_ids:
        deputy_ids.remove(target_id)

    await clan_ref.update({"leader_id": target_id, "members": members, "deputy_ids": deputy_ids})
    await update_user_field(chat_id, target_id, "clan", clan_name)
    await flush_user_cache_immediately(chat_id, target_id)

    await message.answer(f"✅ Лидером клана <b>{escape_html(clan_name)}</b> назначен "
                         f"{target_data.get('full_name', 'Игрок')} ({target_id}).")
    await state.clear()
    mock_cb = MockCallback(message, menu_message_id, f"db_clan_view_{chat_id}_{get_clan_hash(clan_name)}")
    await show_clan_detail_screen(mock_cb, state, chat_id, clan_name)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_clan_dask_") | F.data.startswith("db_clan_del_ask_"))
@creator_only
async def cb_clan_del_ask_screen(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    text = (
        f"🚨 <b>ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ!</b> 🚨\n\n"
        f"Распустить клан <b>{escape_html(clan_name)}</b>?\n"
        f"Действие безвозвратно удалит клан и очистит принадлежность у всех участников.\n\nУверены?"
    )
    builder = InlineKeyboardBuilder()
    c_hash = get_clan_hash(clan_name)
    builder.button(text="💥 Да, распустить клан", callback_data=f"db_clan_dconf_{chat_id}_{c_hash}")
    builder.button(text="❌ Отмена", callback_data=f"db_clan_view_{chat_id}_{c_hash}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_clan_dconf_") | F.data.startswith("db_clan_del_confirm_"))
@creator_only
async def cb_perform_clan_delete(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    clan_ref = clans_collection(chat_id).document(clan_name)
    doc = await clan_ref.get()
    if doc.exists:
        for m_id in (doc.to_dict() or {}).get("members", []):
            await update_user_field(chat_id, m_id, "clan", None)
            await flush_user_cache_immediately(chat_id, m_id)
        await clan_ref.delete()
        logger.info("Clan '%s' disbanded in chat %s", clan_name, chat_id)
        await safe_answer(callback, f"Клан {clan_name} распущен!", show_alert=True)
    else:
        await safe_answer(callback, "Клан не найден.")
    await cb_clans_list(callback, state)


# ==============================================================================
#  УПРАВЛЕНИЕ СОСТАВОМ КЛАНА
# ==============================================================================
@router.callback_query(F.data.startswith("db_clan_mlist_") | F.data.startswith("db_clan_members_list_"))
@creator_only
async def cb_clan_members_list(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    doc = await clans_collection(chat_id).document(clan_name).get()
    if not doc.exists:
        return await safe_answer(callback, "Клан не найден.", show_alert=True)

    clan_data = doc.to_dict() or {}
    members = clan_data.get("members", [])
    leader_id = clan_data.get("leader_id")
    deputy_ids = clan_data.get("deputy_ids", [])

    text = f"👥 <b>Состав клана {escape_html(clan_name)}</b>\n\nВыберите участника:"
    builder = InlineKeyboardBuilder()
    c_hash = get_clan_hash(clan_name)
    for m_id in members:
        try:
            m_name = (await get_user_data(chat_id, m_id)).get("full_name", f"ID: {m_id}")
        except Exception:
            m_name = f"ID: {m_id}"
        role = "👑" if m_id == leader_id else ("⭐" if m_id in deputy_ids else "👤")
        builder.button(text=f"{role} {m_name}", callback_data=f"db_clan_mem_{chat_id}_{m_id}_{c_hash}")
    builder.button(text="⬅️ Назад к деталям клана", callback_data=f"db_clan_view_{chat_id}_{c_hash}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_clan_mem_") | F.data.startswith("db_clan_member_"))
@creator_only
async def cb_clan_member_view(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await safe_answer(callback, "❌ Клан не найден.", show_alert=True)
    doc = await clans_collection(chat_id).document(clan_name).get()
    if not doc.exists:
        return await safe_answer(callback, "Клан не найден.", show_alert=True)

    clan_data = doc.to_dict() or {}
    leader_id = clan_data.get("leader_id")
    deputies = clan_data.get("deputy_ids", [])
    try:
        m_name = (await get_user_data(chat_id, member_id)).get("full_name", f"ID: {member_id}")
    except Exception:
        m_name = f"ID: {member_id}"

    if member_id == leader_id:
        role_desc = "👑 Лидер (Нельзя исключить / сменить роль)"
    elif member_id in deputies:
        role_desc = "⭐ Заместитель"
    else:
        role_desc = "👤 Участник"

    text = (
        f"👤 <b>Управление участником</b>\n\n"
        f"Клан: <b>{escape_html(clan_name)}</b>\n"
        f"Игрок: <b>{escape_html(m_name)}</b> (ID: <code>{member_id}</code>)\n"
        f"Роль: <b>{role_desc}</b>"
    )
    builder = InlineKeyboardBuilder()
    c_hash = get_clan_hash(clan_name)
    if member_id != leader_id:
        if member_id in deputies:
            builder.button(text="👤 Сделать Участником", callback_data=f"db_clan_dem_{chat_id}_{member_id}_{c_hash}")
        else:
            builder.button(text="⭐ Сделать Заместителем", callback_data=f"db_clan_prom_{chat_id}_{member_id}_{c_hash}")
        builder.button(text="👑 Сделать Лидером", callback_data=f"db_clan_ltr_{chat_id}_{member_id}_{c_hash}")
        builder.button(text="👞 Исключить из клана", callback_data=f"db_clan_kck_{chat_id}_{member_id}_{c_hash}")
    builder.button(text="⬅️ К списку участников", callback_data=f"db_clan_mlist_{chat_id}_{c_hash}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_clan_prom_") | F.data.startswith("db_clan_promote_"))
@creator_only
async def cb_clan_promote(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await safe_answer(callback, "❌ Клан не найден.")
    clan_ref = clans_collection(chat_id).document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await safe_answer(callback, "Клан не найден.")
    deputies = list((doc.to_dict() or {}).get("deputy_ids", []))
    if member_id not in deputies:
        deputies.append(member_id)
        await clan_ref.update({"deputy_ids": deputies})
        await safe_answer(callback, "Участник назначен Заместителем!", show_alert=True)
    callback.data = f"db_clan_mem_{chat_id}_{member_id}_{get_clan_hash(clan_name)}"
    await cb_clan_member_view(callback, state)


@router.callback_query(F.data.startswith("db_clan_dem_") | F.data.startswith("db_clan_demote_"))
@creator_only
async def cb_clan_demote(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await safe_answer(callback, "❌ Клан не найден.")
    clan_ref = clans_collection(chat_id).document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await safe_answer(callback, "Клан не найден.")
    deputies = list((doc.to_dict() or {}).get("deputy_ids", []))
    if member_id in deputies:
        deputies.remove(member_id)
        await clan_ref.update({"deputy_ids": deputies})
        await safe_answer(callback, "Заместитель разжалован!", show_alert=True)
    callback.data = f"db_clan_mem_{chat_id}_{member_id}_{get_clan_hash(clan_name)}"
    await cb_clan_member_view(callback, state)


@router.callback_query(F.data.startswith("db_clan_kck_") | F.data.startswith("db_clan_kick_"))
@creator_only
async def cb_clan_kick(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await safe_answer(callback, "❌ Клан не найден.")
    clan_ref = clans_collection(chat_id).document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await safe_answer(callback, "Клан не найден.")
    clan_data = doc.to_dict() or {}
    members = list(clan_data.get("members", []))
    deputies = list(clan_data.get("deputy_ids", []))
    if member_id in members:
        members.remove(member_id)
    if member_id in deputies:
        deputies.remove(member_id)
    await clan_ref.update({"members": members, "deputy_ids": deputies})
    await update_user_field(chat_id, member_id, "clan", None)
    await flush_user_cache_immediately(chat_id, member_id)
    await safe_answer(callback, "Игрок исключён из клана!", show_alert=True)
    callback.data = f"db_clan_mlist_{chat_id}_{get_clan_hash(clan_name)}"
    await cb_clan_members_list(callback, state)


@router.callback_query(F.data.startswith("db_clan_ltr_") | F.data.startswith("db_clan_leadtransfer_"))
@creator_only
async def cb_clan_leadtransfer(callback: types.CallbackQuery, state: FSMContext):
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await safe_answer(callback, "❌ Клан не найден.")
    clan_ref = clans_collection(chat_id).document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await safe_answer(callback, "Клан не найден.")
    deputies = list((doc.to_dict() or {}).get("deputy_ids", []))
    if member_id in deputies:
        deputies.remove(member_id)
    await clan_ref.update({"leader_id": member_id, "deputy_ids": deputies})
    await update_user_field(chat_id, member_id, "clan", clan_name)
    await flush_user_cache_immediately(chat_id, member_id)
    await safe_answer(callback, "Лидерство передано!", show_alert=True)
    callback.data = f"db_clan_mem_{chat_id}_{member_id}_{get_clan_hash(clan_name)}"
    await cb_clan_member_view(callback, state)


# ==============================================================================
#  УПРАВЛЕНИЕ ПРОМОКОДАМИ
# ==============================================================================
def promocodes_collection():
    return get_db().collection("bot_settings").document("promocodes").collection("active")


@router.callback_query(F.data.startswith("db_promos_list_"))
@creator_only
async def cb_promos_list(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3)
    promos_docs = await promocodes_collection().get()

    text = "🏷 <b>Управление промокодами (Глобально)</b>\n\nАктивные промокоды:"
    builder = InlineKeyboardBuilder()
    has_promos = False
    for doc in promos_docs:
        p_data = doc.to_dict() or {}
        reward = p_data.get("reward", 0)
        used_by = p_data.get("used_by", [])
        max_act = p_data.get("max_activations", 0)
        builder.button(text=f"❌ {doc.id} ({reward} сыр, {len(used_by)}/{max_act} исп.)",
                       callback_data=f"db_promo_del_{chat_id}_{doc.id}")
        has_promos = True
    if not has_promos:
        text += "\n\n<i>Активных промокодов нет.</i>"
    builder.button(text="➕ Создать промокод", callback_data=f"db_promo_create_{chat_id}")
    builder.button(text="⬅️ Назад к глобальным", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_promo_del_"))
@creator_only
async def cb_promo_del(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3)
    code = "_".join(parts[4:])
    await promocodes_collection().document(code).delete()
    logger.info("Promo '%s' deleted", code)
    await safe_answer(callback, f"Промокод {code} удалён!", show_alert=True)
    await cb_promos_list(callback, state)


@router.callback_query(F.data.startswith("db_promo_create_"))
@creator_only
async def cb_promo_create_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3)
    await state.set_state(AdminPanelState.waiting_for_promo_code)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_promos_list_{chat_id}")
    await safe_edit(
        callback.message,
        "🏷 <b>Создание промокода</b>\n\nШаг 1: Введите текст (код) промокода:",
        builder.as_markup(),
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_promo_code)
@creator_only
async def process_promo_code_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    code = message.text.strip().upper()
    if (await promocodes_collection().document(code).get()).exists:
        await message.answer("❌ Такой промокод уже существует. Введите другое имя:")
        return
    await state.set_state(AdminPanelState.waiting_for_promo_reward)
    await state.update_data(promo_code=code)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_promos_list_{chat_id}")
    await message.answer(
        f"🏷 <b>Промокод {code}</b>\n\nШаг 2: Введите сумму награды в сыроежках:",
        reply_markup=builder.as_markup(),
    )
    await safe_delete(message)


@router.message(AdminPanelState.waiting_for_promo_reward)
@creator_only
async def process_promo_reward_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, code = data["chat_id"], data["promo_code"]
    reward = parse_int(message.text, allow_negative=False, minimum=1)
    if reward is None:
        await message.answer("❌ Награда — целое число больше нуля. Попробуйте ещё раз:")
        return
    await state.set_state(AdminPanelState.waiting_for_promo_max_uses)
    await state.update_data(promo_reward=reward)
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_promos_list_{chat_id}")
    await message.answer(
        f"🏷 <b>Промокод {code} (Награда: {reward} сыр)</b>\n\n"
        f"Шаг 3: Введите максимальное количество использований:",
        reply_markup=builder.as_markup(),
    )
    await safe_delete(message)


@router.message(AdminPanelState.waiting_for_promo_max_uses)
@creator_only
async def process_promo_max_uses_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, code, reward = data["chat_id"], data["promo_code"], data["promo_reward"]
    max_uses = parse_int(message.text, allow_negative=False, minimum=1)
    if max_uses is None:
        await message.answer("❌ Количество активаций — целое больше нуля. Попробуйте ещё раз:")
        return
    await promocodes_collection().document(code).set({
        "reward": reward, "max_activations": max_uses, "used_by": [],
    })
    logger.info("Promo '%s' created (reward=%s, max=%s)", code, reward, max_uses)
    await message.answer(
        f"✅ Промокод <b>{code}</b> создан!\nНаграда: {reward} сыроежек\nЛимит: {max_uses}"
    )
    await state.clear()
    await cb_promos_list(
        MockCallback(message, data.get("menu_message_id"), f"db_promos_list_{chat_id}"), state
    )
    await safe_delete(message)


# ==============================================================================
# РАЗДЕЛ: РЕЗЕРВНОЕ КОПИРОВАНИЕ (БЭКАПЫ) В МЕНЮ
# ==============================================================================

@router.callback_query(F.data.startswith("db_backups_menu_"))
@creator_only
async def cb_backups_menu(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    await state.clear()
    
    db = get_db()
    text = (
        "📦 <b>Управление резервными копиями базы данных</b>\n\n"
        "Здесь вы можете вручную создавать резервные копии (users, banks, clans) "
        "и просматривать список доступных точек восстановления.\n\n"
        "Выберите копию для просмотра деталей и отката:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать новый бэкап", callback_data=f"db_backup_create_{chat_id}")
    
    try:
        docs = await db.collection('backups').order_by('timestamp', direction='DESCENDING').limit(15).get()
        for doc in docs:
            d = doc.to_dict()
            dt_str = d.get('datetime', 'Unknown')
            builder.button(text=f"📅 {doc.id} ({dt_str})", callback_data=f"db_backup_view_{chat_id}_{doc.id}")
    except Exception as e:
        text += f"\n\n❌ <i>Ошибка загрузки бэкапов: {e}</i>"
        
    builder.button(text="⬅️ Назад в глобальные", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_backup_create_"))
@creator_only
async def cb_backup_create(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    await safe_answer(callback, "⏳ Создаю бэкап...")
    
    from backup_system import backup_database
    success, result = await backup_database()
    
    if success:
        await safe_answer(callback, "✅ Бэкап успешно создан!", show_alert=True)
    else:
        await safe_answer(callback, f"❌ Ошибка: {result}", show_alert=True)
        
    await cb_backups_menu(callback, state)


@router.callback_query(F.data.startswith("db_backup_view_"))
@creator_only
async def cb_backup_view(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    backup_id = "_".join(parts[4:])
    
    import gzip
    import json
    import base64
    
    db = get_db()
    doc = await db.collection('backups').document(backup_id).get()
    
    if not doc.exists:
        return await safe_answer(callback, "❌ Бэкап не найден.", show_alert=True)
        
    d = doc.to_dict()
    payload = d.get("payload", "")
    dt_str = d.get("datetime", "Unknown")
    ts = d.get("timestamp", 0)
    
    info_str = "❌ Нет данных"
    if payload:
        try:
            compressed_bytes = base64.b64decode(payload)
            json_bytes = gzip.decompress(compressed_bytes)
            backup_data = json.loads(json_bytes.decode('utf-8'))
            chats = backup_data.get("chats", {})
            num_chats = len(chats)
            num_users = sum(len(c.get("users", {})) for c in chats.values())
            num_banks = sum(len(c.get("banks", {})) for c in chats.values())
            num_clans = sum(len(c.get("clans", {})) for c in chats.values())
            info_str = (
                f"🏢 Чатов: {num_chats}\n"
                f"👤 Игроков: {num_users}\n"
                f"🏦 Банков: {num_banks}\n"
                f"🛡 Кланов: {num_clans}"
            )
        except Exception as e:
            info_str = f"⚠️ Ошибка разбора: {e}"
            
    text = (
        f"📄 <b>Информация о бэкапе:</b> <code>{backup_id}</code>\n\n"
        f"📅 Дата создания: <b>{dt_str} UTC</b>\n"
        f"🔑 Timestamp: <code>{ts}</code>\n\n"
        f"📊 <b>Содержимое бэкапа:</b>\n{info_str}\n\n"
        f"⚠️ Восстановление сотрет текущие данные в чатах!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Восстановить базу из бэкапа", callback_data=f"db_backup_rest_conf_{chat_id}_{backup_id}")
    builder.button(text="⬅️ К списку бэкапов", callback_data=f"db_backups_menu_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_backup_rest_conf_"))
@creator_only
async def cb_backup_restore_confirm(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 4, default=0)
    backup_id = "_".join(parts[5:])
    
    text = (
        f"⚠️⚠️⚠️ <b>ВНИМАНИЕ! ПОЛНЫЙ ОТКАТ БАЗЫ ДАННЫХ</b> ⚠️⚠️⚠️\n\n"
        f"Вы действительно хотите восстановить базу данных из копии <code>{backup_id}</code>?\n\n"
        f"<b>ЭТО ДЕЙСТВИЕ:</b>\n"
        f"1. Полностью сотрет всех игроков, банки и кланы в чатах.\n"
        f"2. Запишет данные из выбранного бэкапа.\n"
        f"3. Сбросит кэш.\n\n"
        f"Убедитесь, что бот остановлен на время восстановления во избежание сбоев кэша!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Да, начать восстановление", callback_data=f"db_backup_rest_exec_{chat_id}_{backup_id}")
    builder.button(text="❌ Отмена", callback_data=f"db_backup_view_{chat_id}_{backup_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_backup_rest_exec_"))
@creator_only
async def cb_backup_restore_execute(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 4, default=0)
    backup_id = "_".join(parts[5:])
    
    await safe_edit(callback.message, f"🔄 <i>Восстанавливаю базу данных из {backup_id}... Пожалуйста, подождите.</i>")
    await safe_answer(callback, "🔄 Запуск восстановления...")
    
    from backup_system import restore_database
    success, error = await restore_database(backup_id)
    
    if success:
        text = f"✅ База данных успешно восстановлена из резервной копии <code>{backup_id}</code>!"
        await safe_answer(callback, "✅ Успешно восстановлено!", show_alert=True)
    else:
        text = f"❌ Ошибка восстановления: <code>{error}</code>"
        await safe_answer(callback, f"❌ Ошибка: {error}", show_alert=True)
        
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data=f"db_backup_view_{chat_id}_{backup_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    
    try:
        from config import CREATOR_ID
        await callback.bot.send_message(chat_id=CREATOR_ID, text=text, parse_mode="HTML")
    except Exception:
        pass


# ==============================================================================
# РАЗДЕЛ: УПРАВЛЕНИЕ КРИПТОЙ В МЕНЮ
# ==============================================================================

@router.callback_query(F.data.startswith("db_crypto_menu_"))
@creator_only
async def cb_crypto_menu(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    await state.clear()
    
    from crypto import get_all_coins
    coins = await get_all_coins()
    
    text = (
        "🪙 <b>Управление криптовалютой на бирже</b>\n\n"
        "Здесь вы можете управлять листингом монет, изменять курс "
        "и делать искусственные пампы или дампы (краш).\n\n"
        "Выберите монету для настроек или создайте новую:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать новую монету (Листинг)", callback_data=f"db_crypto_add_{chat_id}")
    
    for cid, coin in coins.items():
        price = coin["prices"][-1] if coin.get("prices") else 0
        name = coin.get("name", "Unknown")
        builder.button(text=f"🪙 {coin['ticker']} ({name}) — {fmt_money(price)} сыр.", callback_data=f"db_crypto_cview_{chat_id}_{cid}")
        
    builder.button(text="⬅️ Назад в глобальные", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_crypto_add_"))
@creator_only
async def cb_crypto_add(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    await state.set_state(AdminPanelState.waiting_for_coin_ticker)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_crypto_menu_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(
        callback.message,
        "🪙 <b>Листинг новой монеты — Шаг 1</b>\n\nВведите краткий ТИКЕР монеты (например, SOL, максимум 8 букв):",
        builder.as_markup()
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_coin_ticker)
@creator_only
async def process_coin_ticker_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    ticker = message.text.strip().lower()[:8]
    
    if not ticker.isalnum():
        await message.answer("❌ Тикер должен содержать только буквы и цифры. Введите еще раз:")
        return
        
    from crypto import get_all_coins
    coins = await get_all_coins()
    if ticker in coins:
        await message.answer("❌ Такой тикер уже занят другой монетой. Введите другой:")
        return
        
    await state.set_state(AdminPanelState.waiting_for_coin_name)
    await state.update_data(coin_ticker=ticker)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_crypto_menu_{chat_id}")
    builder.adjust(1)
    
    await message.answer(
        f"🪙 <b>Монета {ticker.upper()}</b>\n\nШаг 2: Введите полное название монеты (например, Solana, максимум 32 символа):",
        reply_markup=builder.as_markup()
    )
    await safe_delete(message)


@router.message(AdminPanelState.waiting_for_coin_name)
@creator_only
async def process_coin_name_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    ticker = data["coin_ticker"]
    name = escape_html(message.text.strip()[:32])
    
    start_price = random.randint(100, 500)
    
    from crypto import get_all_coins, update_coins
    coins = await get_all_coins()
    
    coins[ticker] = {
        "name": name,
        "ticker": ticker.upper(),
        "prices": [start_price],
        "creator": message.from_user.id
    }
    await update_coins(coins)
    
    await message.answer(
        f"✅ Монета <b>{name}</b> ({ticker.upper()}) успешно добавлена на биржу!\n"
        f"💰 Начальный курс: {fmt_money(start_price)} сыр."
    )
    await state.clear()
    
    await cb_crypto_menu(MockCallback(message, data.get("menu_message_id"), f"db_crypto_menu_{chat_id}"), state)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_crypto_cview_"))
@creator_only
async def cb_crypto_coin_view(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    ticker = parts[4].lower()
    
    from crypto import get_all_coins
    coins = await get_all_coins()
    
    if ticker not in coins:
        return await safe_answer(callback, "❌ Монета не найдена.", show_alert=True)
        
    coin = coins[ticker]
    prices = coin.get("prices", [100])
    price = prices[-1]
    name = coin.get("name", "Unknown")
    creator_id = coin.get("creator", "Админ")
    
    text = (
        f"🪙 <b>Управление монетой {coin['ticker']} ({name})</b>\n\n"
        f"💰 Текущая цена: <b>{fmt_money(price)} сыр.</b>\n"
        f"👤 ID создателя: <code>{creator_id}</code>\n"
        f"📈 Длина истории цен: {len(prices)} тиков\n\n"
        f"Выберите действие для монеты:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Изменить курс (вручную)", callback_data=f"db_crypto_pr_{chat_id}_{ticker}")
    builder.button(text="📈 Памп / 📉 Дамп (Краш)", callback_data=f"db_crypto_cr_{chat_id}_{ticker}")
    builder.button(text="🗑 Делистинг (Удалить монету)", callback_data=f"db_crypto_del_{chat_id}_{ticker}")
    builder.button(text="⬅️ Назад к списку", callback_data=f"db_crypto_menu_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_crypto_pr_"))
@creator_only
async def cb_crypto_price_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    ticker = parts[4].lower()
    
    await state.set_state(AdminPanelState.waiting_for_coin_price)
    await state.update_data(chat_id=chat_id, coin_ticker=ticker, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_crypto_cview_{chat_id}_{ticker}")
    builder.adjust(1)
    
    await safe_edit(
        callback.message,
        f"💸 <b>Изменение курса {ticker.upper()}</b>\n\nВведите новое значение курса монеты (целое число больше нуля):",
        builder.as_markup()
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_coin_price)
@creator_only
async def process_coin_price_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, ticker = data["chat_id"], data["coin_ticker"]
    
    price = parse_int(message.text, allow_negative=False, minimum=1)
    if price is None:
        await message.answer("❌ Курс монеты должен быть целым числом больше нуля. Попробуйте еще раз:")
        return
        
    from crypto import get_all_coins, update_coins
    coins = await get_all_coins()
    if ticker in coins:
        coins[ticker].setdefault("prices", [100]).append(price)
        await update_coins(coins)
        await message.answer(f"✅ Курс монеты <b>{ticker.upper()}</b> изменен на <b>{fmt_money(price)} сыр.</b>")
        
    await state.clear()
    await cb_crypto_coin_view(MockCallback(message, data.get("menu_message_id"), f"db_crypto_cview_{chat_id}_{ticker}"), state)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_crypto_cr_"))
@creator_only
async def cb_crypto_crash_prompt(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    ticker = parts[4].lower()
    
    await state.set_state(AdminPanelState.waiting_for_coin_crash)
    await state.update_data(chat_id=chat_id, coin_ticker=ticker, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_crypto_cview_{chat_id}_{ticker}")
    builder.adjust(1)
    
    await safe_edit(
        callback.message,
        f"📈📉 <b>Памп / Дамп монеты {ticker.upper()}</b>\n\n"
        f"Введите процент изменения курса монеты (целое число от -99 до +1000).\n"
        f"Например: <code>+50</code> увеличит курс наполовину, а <code>-30</code> обвалит на 30%:",
        builder.as_markup()
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_coin_crash)
@creator_only
async def process_coin_crash_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id, ticker = data["chat_id"], data["coin_ticker"]
    
    percent = parse_int(message.text, allow_negative=True)
    if percent is None or percent < -99 or percent > 1000:
        await message.answer("❌ Процент изменения должен быть целым числом в диапазоне от -99 до +1000. Введите снова:")
        return
        
    from crypto import get_all_coins, update_coins
    coins = await get_all_coins()
    if ticker in coins:
        prices = coins[ticker].setdefault("prices", [100])
        last_price = prices[-1]
        
        multiplier = 1 + (percent / 100.0)
        new_price = max(1, int(last_price * multiplier))
        
        prices.append(new_price)
        await update_coins(coins)
        
        sign = "+" if percent >= 0 else ""
        await message.answer(f"📊 Курс монеты <b>{ticker.upper()}</b> изменен на <b>{sign}{percent}%</b>! Текущая цена: <b>{fmt_money(new_price)} сыр.</b>")
        
    await state.clear()
    await cb_crypto_coin_view(MockCallback(message, data.get("menu_message_id"), f"db_crypto_cview_{chat_id}_{ticker}"), state)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_crypto_del_"))
@creator_only
async def cb_crypto_del_confirm(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    ticker = parts[4].lower()
    
    from crypto import get_all_coins
    coins = await get_all_coins()
    if ticker not in coins:
        return await safe_answer(callback, "❌ Монета не найдена.", show_alert=True)
        
    price = coins[ticker]["prices"][-1]
    
    text = (
        f"⚠️⚠️⚠️ <b>ДЕЛИСТИНГ МОНЕТЫ {ticker.upper()}</b> ⚠️⚠️⚠️\n\n"
        f"Вы действительно хотите полностью удалить монету <b>{ticker.upper()}</b>?\n\n"
        f"<b>ЭТО ДЕЙСТВИЕ:</b>\n"
        f"1. Удалит монету с биржи безвозвратно.\n"
        f"2. Возвратит баланс в сыроежках ВСЕМ владельцам во всех чатах "
        f"по текущей цене <b>{fmt_money(price)} сыр.</b> за единицу.\n\n"
        f"Это тяжелая операция, которая сканирует всю БД!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Да, удалить и вернуть средства", callback_data=f"db_crypto_dexec_{chat_id}_{ticker}")
    builder.button(text="❌ Отмена", callback_data=f"db_crypto_cview_{chat_id}_{ticker}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_crypto_dexec_"))
@creator_only
async def cb_crypto_del_execute(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    ticker = parts[4].lower()
    
    await safe_edit(callback.message, f"🗑 <i>Провожу делистинг монеты {ticker.upper()}... Пожалуйста, подождите.</i>")
    await safe_answer(callback, "🔄 Запуск делистинга...")
    
    from crypto import get_all_coins
    coins = await get_all_coins()
    
    if ticker not in coins:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data=f"db_crypto_menu_{chat_id}")
        await safe_edit(callback.message, "❌ Ошибка: монета не найдена.", builder.as_markup())
        return
        
    last_price = coins[ticker]["prices"][-1]
    db = get_db()
    
    refunded_count = 0
    total_refund = 0
    
    try:
        from firebase_admin import firestore_async
        chats_ref = db.collection('chats')
        chats_docs = await chats_ref.get()
        
        for chat_doc in chats_docs:
            c_id = chat_doc.id
            users_ref = chats_ref.document(c_id).collection('users')
            users_docs = await users_ref.get()
            
            for user_doc in users_docs:
                u_data = user_doc.to_dict() or {}
                port = u_data.get('crypto_portfolio', {})
                
                if ticker in port:
                    qty = port[ticker]
                    if qty > 0:
                        refund_amount = qty * last_price
                        del port[ticker]
                        
                        await users_ref.document(user_doc.id).update({
                            'balance': firestore_async.Increment(refund_amount),
                            'crypto_portfolio': port
                        })
                        from user_manager import invalidate_user_cache
                        try:
                            invalidate_user_cache(int(c_id), int(user_doc.id))
                        except Exception:
                            pass
                            
                        refunded_count += 1
                        total_refund += refund_amount
                        
        await db.collection('bot_settings').document('crypto_coins').update({
            f"coins.{ticker}": firestore_async.DELETE_FIELD
        })
        
        text = (
            f"🗑 Монета <b>{ticker.upper()}</b> была успешно удалена с биржи (делистинг).\n\n"
            f"💰 Средства возвращены {refunded_count} игрокам во всех чатах.\n"
            f"💵 Всего выплачено: <b>{fmt_money(total_refund)} сыр.</b> (по цене {fmt_money(last_price)} сыр./ед.)."
        )
        await safe_answer(callback, "✅ Делистинг выполнен!", show_alert=True)
    except Exception as e:
        text = f"❌ Ошибка в процессе делистинга: <code>{e}</code>"
        await safe_answer(callback, f"❌ Ошибка: {e}", show_alert=True)
        
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В крипто-меню", callback_data=f"db_crypto_menu_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())


# ==============================================================================
# РАЗДЕЛ: ДОПОЛНИТЕЛЬНЫЕ АДМИН-КОМАНДЫ В МЕНЮ
# ==============================================================================

@router.callback_query(F.data.startswith("db_extra_cmds_"))
@creator_only
async def cb_extra_cmds_menu(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    await state.clear()
    
    text = (
        "🤖 <b>Панель дополнительных команд Создателя</b>\n\n"
        "Используйте эти кнопки как быстрые ярлыки вместо ручного ввода команд в чате.\n"
        "Здесь собрано полное управление состоянием бота:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🧹 Сбросить все кэши (Invalidate)", callback_data=f"db_ext_ccache_{chat_id}")
    builder.button(text="💼 Управление банкирами", callback_data=f"db_ext_bankers_{chat_id}")
    builder.button(text="🔒 Заблокировать/Разблокировать группу", callback_data=f"db_ext_lock_{chat_id}")
    builder.button(text="📟 Выполнить Python-код", callback_data=f"db_ext_eval_{chat_id}")
    builder.button(text="⬅️ Назад в глобальные", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_ext_ccache_"))
@creator_only
async def cb_extra_clear_cache(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    
    from user_manager import _user_cache, _username_to_id_cache
    from profile_bank import _bank_cache
    
    _user_cache.clear()
    _username_to_id_cache.clear()
    _bank_cache.clear()
    
    await safe_answer(callback, "✅ Все локальные кэши успешно сброшены!", show_alert=True)
    await cb_extra_cmds_menu(callback, state)


@router.callback_query(F.data.startswith("db_ext_bankers_"))
@creator_only
async def cb_extra_bankers(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    
    db = get_db()
    text = "💼 <b>Список официальных Банкиров во всех чатах:</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    
    try:
        chats_docs = await db.collection('chats').get()
        found_any = False
        for chat_doc in chats_docs:
            c_id = chat_doc.id
            whitelist = await get_whitelist()
            chat_title = whitelist.get(int(c_id), f"Чат {c_id}")
            
            users_docs = await db.collection('chats').document(c_id).collection('users').where('is_banker', '==', True).get()
            for u_doc in users_docs:
                u_data = u_doc.to_dict()
                username = u_data.get('username', 'NoUsername')
                balance = u_data.get('balance', 0)
                text += f"• 🏢 {chat_title}: @{username} (<code>{u_doc.id}</code>) — {fmt_money(balance)} сыр.\n"
                builder.button(
                    text=f"❌ Разжаловать @{username} ({chat_title})",
                    callback_data=f"db_ext_delbanker_{chat_id}_{c_id}_{u_doc.id}"
                )
                found_any = True
                
        if not found_any:
            text += "<i>Банкиры не найдены. Назначить банкира можно только в группе ответом на сообщение командой <code>/setbanker</code>.</i>"
    except Exception as e:
        text += f"❌ Ошибка получения банкиров: {e}"
        
    builder.button(text="⬅️ Назад", callback_data=f"db_extra_cmds_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.callback_query(F.data.startswith("db_ext_delbanker_"))
@creator_only
async def cb_extra_delbanker(callback: types.CallbackQuery, state: FSMContext):
    parts = split_cb(callback.data)
    chat_id = cb_int(parts, 3, default=0)
    target_chat_id = parts[4]
    target_user_id = parts[5]
    
    from user_manager import update_user_field, invalidate_user_cache
    await update_user_field(int(target_chat_id), int(target_user_id), 'is_banker', False)
    invalidate_user_cache(int(target_chat_id), int(target_user_id))
    
    await safe_answer(callback, "✅ Банкир успешно разжалован!", show_alert=True)
    await cb_extra_bankers(callback, state)


@router.callback_query(F.data.startswith("db_ext_lock_"))
@creator_only
async def cb_extra_lock_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    
    from lock_system import get_locked_chats
    locked = await get_locked_chats()
    
    text = "🔒 <b>Управление блокировками бота в группах</b>\n\n"
    if locked:
        text += "Список заблокированных ID групп:\n"
        for lid in locked:
            text += f"  • <code>{lid}</code>\n"
    else:
        text += "Заблокированных групп нет. Бот работает везде свободно.\n"
        
    text += "\nВведите ID группы (целое число со знаком минус, например -100...) для переключения блокировки:"
    
    await state.set_state(AdminPanelState.waiting_for_lock_chat_id)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_extra_cmds_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(callback.message, text, builder.as_markup())
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_lock_chat_id)
@creator_only
async def process_lock_chat_id_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    
    try:
        target_id = int(message.text.strip())
        from lock_system import toggle_lock
        is_enabled = await toggle_lock(target_id)
        
        status = "заблокирован" if is_enabled else "разблокирован"
        await message.answer(f"✅ Чат <code>{target_id}</code> успешно {status}!")
    except ValueError:
        await message.answer("❌ ID группы должен быть целым числом (обычно начинается с -100). Попробуйте еще раз:")
        return
        
    await state.clear()
    await cb_extra_cmds_menu(MockCallback(message, data.get("menu_message_id"), f"db_extra_cmds_{chat_id}"), state)
    await safe_delete(message)


@router.callback_query(F.data.startswith("db_ext_eval_"))
@creator_only
async def cb_extra_eval_prompt(callback: types.CallbackQuery, state: FSMContext):
    chat_id = cb_int(split_cb(callback.data), 3, default=0)
    
    await state.set_state(AdminPanelState.waiting_for_eval_code)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_extra_cmds_{chat_id}")
    builder.adjust(1)
    
    await safe_edit(
        callback.message,
        "📟 <b>Выполнение Python-кода (Async Eval/Exec)</b>\n\n"
        "Отправьте Python-код. Поддерживается `await`. "
        "В контексте доступны: `db`, `bot`, `callback`, `state`, `get_db()`. "
        "Для вывода используйте `print()` или верните выражение через `return`:",
        builder.as_markup()
    )
    await safe_answer(callback)


@router.message(AdminPanelState.waiting_for_eval_code)
@creator_only
async def process_eval_code_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    code = message.text.strip()
    
    await message.answer("⏳ Выполняю код...")
    
    import io
    import sys
    
    local_vars = {
        "db": get_db(),
        "get_db": get_db,
        "bot": message.bot,
        "message": message,
        "state": state,
        "asyncio": asyncio,
        "time": time,
        "os": os
    }
    
    stdout = io.StringIO()
    sys.stdout = stdout
    
    func_code = f"async def __temp_async_eval_func():\n"
    for line in code.split("\n"):
        func_code += f"    {line}\n"
        
    try:
        exec(func_code, globals(), local_vars)
        func = local_vars["__temp_async_eval_func"]
        result = await func()
        
        sys.stdout = sys.__stdout__
        output = stdout.getvalue()
        
        res_str = ""
        if output:
            res_str += f"<b>Вывод stdout:</b>\n<pre>{escape_html(output)}</pre>\n"
        if result is not None:
            res_str += f"<b>Результат:</b>\n<code>{escape_html(str(result))}</code>"
            
        if not res_str:
            res_str = "✅ Код успешно выполнен (без вывода)."
            
        await message.answer(res_str)
    except Exception as e:
        sys.stdout = sys.__stdout__
        error_trace = traceback.format_exc()
        await message.answer(f"❌ <b>Ошибка выполнения:</b>\n<pre>{escape_html(str(e))}</pre>\n<pre>{escape_html(error_trace[:800])}</pre>")
        
    await state.clear()
    await cb_extra_cmds_menu(MockCallback(message, data.get("menu_message_id"), f"db_extra_cmds_{chat_id}"), state)
    await safe_delete(message)