import time
import random
import traceback
import asyncio
from typing import Optional
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import CREATOR_ID, CREATOR_USERNAME
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
    flush_user_cache_immediately
)
from whitelist import get_whitelist, add_to_whitelist, remove_from_whitelist
from chances import get_game_chance, set_game_chance
from economy_utils import get_global_tax, set_global_tax
from spy import toggle_spy, get_spy_chats
from lock_system import toggle_lock, get_locked_chats
from admin_logs import log_transaction, check_balance_alert

# Импортируем хелперы для банков
from profile_bank import (
    get_bank_info,
    create_or_update_bank,
    invalidate_bank_cache,
    DEFAULT_DEPOSIT_RATE,
    MIN_DEPOSIT_RATE,
    MAX_DEPOSIT_RATE
)

router = Router()

# ===================== СОСТОЯНИЯ FSM =====================
class AdminPanelState(StatesGroup):
    waiting_for_player_search = State()
    waiting_for_player_money_add = State()
    waiting_for_player_money_set = State()
    waiting_for_say_text = State()
    waiting_for_global_tax = State()
    waiting_for_chance_val = State()  # Сохраняем имя игры в state data
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

# Helper to simulate callback from a text message handler
class MockCallback:
    def __init__(self, message: types.Message, menu_message_id: int, callback_data: str):
        class MockMessage:
            def __init__(self):
                self.chat = message.chat
                self.from_user = message.from_user
                self.message_id = menu_message_id
            async def edit_text(self, text, reply_markup=None):
                try:
                    await message.bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=menu_message_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
                except Exception:
                    await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            async def delete(self):
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=menu_message_id)
                except Exception:
                    pass
        self.message = MockMessage()
        self.bot = message.bot
        self.data = callback_data

    async def answer(self, text=None, show_alert=False):
        if text:
            try:
                await self.bot.send_message(chat_id=self.message.chat.id, text=text)
            except Exception:
                pass

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
def is_creator(message_or_callback) -> bool:
    user = message_or_callback.from_user
    user_id = user.id
    username = user.username
    if username == CREATOR_USERNAME:
        return True
    if CREATOR_ID and int(user_id) == int(CREATOR_ID):
        return True
    return False

async def _collect_docs(docs):
    result = []
    if hasattr(docs, '__aiter__'):
        async for d in docs:
            result.append(d)
    else:
        for d in docs:
            result.append(d)
    return result

# ===================== ГЛОБАЛЬНЫЙ ОТМЕНЩИК FSM =====================
@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    
    state_data = await state.get_data()
    msg_id = state_data.get("menu_message_id")
    chat_id = state_data.get("chat_id", message.chat.id)
    
    await state.clear()
    
    # Попробуем отредактировать меню обратно
    if msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text="❌ Действие отменено Создателем."
            )
        except Exception:
            pass
            
    await message.answer("❌ Ввод отменен.", reply_markup=types.ReplyKeyboardRemove())
    try:
        await message.delete()
    except Exception:
        pass

# ===================== КОМАНДА /admin =====================
@router.message(Command("admin", "admin_panel", "банкиры"))
@router.message(F.text == "!!!admin")
@router.message(F.text == "!!!панель")
async def cmd_admin_main(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    await state.clear()
    
    if message.chat.type == "private":
        # В ЛС показываем меню выбора чата
        await show_chat_select_screen(message, state)
    else:
        # В группе открываем сразу меню этой группы
        chat_id = message.chat.id
        await show_group_main_screen(message, state, chat_id)

# ===================== ЭКРАНЫ ИНТЕРФЕЙСА =====================

# 1. Экран выбора чата (в ЛС)
async def show_chat_select_screen(message_or_callback, state: FSMContext):
    whitelist = await get_whitelist()
    
    text = "🛠 <b>Панель Создателя: Выберите чат для управления</b>"
    builder = InlineKeyboardBuilder()
    
    for cid, title in whitelist.items():
        builder.button(text=f"🏢 {title}", callback_data=f"db_m_{cid}")
        
    builder.button(text="🌍 Глобальные настройки бота", callback_data="db_glob_0")
    builder.button(text="❌ Закрыть", callback_data="db_close")
    builder.adjust(1)
    
    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        msg = await message_or_callback.answer(text, reply_markup=builder.as_markup())
        await state.update_data(menu_message_id=msg.message_id)

# 2. Главный экран управления чатом
async def show_group_main_screen(message_or_callback, state: FSMContext, chat_id: int, edit=False):
    # Очищаем состояние ввода, но сохраняем ID чата
    await state.clear()
    await state.update_data(chat_id=chat_id)
    
    # Получаем информацию о группе
    chat_title = "Группа"
    try:
        bot = message_or_callback.bot if hasattr(message_or_callback, 'bot') else message_or_callback.message.bot
        chat_obj = await bot.get_chat(chat_id)
        chat_title = chat_obj.title or chat_title
    except Exception:
        pass
        
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
    
    # Если пришли из ЛС, добавляем кнопку возврата к выбору чата
    is_pm = False
    if isinstance(message_or_callback, types.CallbackQuery):
        is_pm = message_or_callback.message.chat.type == "private"
    else:
        is_pm = message_or_callback.chat.type == "private"
        
    if is_pm:
        builder.button(text="⬅️ Сменить чат", callback_data="db_sc_0")
        
    builder.button(text="❌ Закрыть", callback_data="db_close")
    builder.adjust(1)
    
    if edit and isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        if isinstance(message_or_callback, types.CallbackQuery):
            msg = await message_or_callback.message.answer(text, reply_markup=builder.as_markup())
            await state.update_data(menu_message_id=msg.message_id)
            await message_or_callback.message.delete()
        else:
            msg = await message_or_callback.answer(text, reply_markup=builder.as_markup())
            await state.update_data(menu_message_id=msg.message_id)

# ===================== ОБРАБОТЧИКИ CALLBACK CALLBACKS =====================

@router.callback_query(F.data == "db_close")
async def cb_close_dashboard(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "db_sc_0")
async def cb_select_chat_route(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    await show_chat_select_screen(callback, state)
    await callback.answer()

@router.callback_query(F.data.startswith("db_m_"))
async def cb_group_main_route(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    chat_id = int(callback.data.split("_")[2])
    await show_group_main_screen(callback, state, chat_id, edit=True)
    await callback.answer()

# ===================== РАЗДЕЛ: БАНКИ =====================

# Список банков в чате
@router.callback_query(F.data.startswith("db_b_"))
async def cb_banks_list(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
        
    chat_id = int(callback.data.split("_")[2])
    await state.update_data(chat_id=chat_id)
    
    db = get_db()
    banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
    docs_raw = await banks_ref.get()
    docs = await _collect_docs(docs_raw)
    
    text = "🏦 <b>Управление банками чата</b>\n\nСписок зарегистрированных банков:"
    builder = InlineKeyboardBuilder()
    
    if not docs:
        text += "\n<i>Банки отсутствуют. Назначьте банкира через кнопку ниже.</i>"
    else:
        for doc in docs:
            b_data = doc.to_dict() or {}
            rate = b_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)
            cap = b_data.get('capital', 0)
            name = b_data.get('name', 'Банк')
            builder.button(text=f"🏛 {escape_html(name)} ({cap:,} сыр.)", callback_data=f"db_bv_{chat_id}_{doc.id}")
            
    builder.button(text="➕ Создать банк игроку", callback_data=f"db_bcr_{chat_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_m_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Просмотр конкретного банка
async def show_bank_detail_screen(callback_or_message, state: FSMContext, chat_id: int, banker_id: int, edit=False):
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        # Если не найден, возвращаемся в список
        if isinstance(callback_or_message, types.CallbackQuery):
            return await cb_banks_list(callback_or_message, state)
        else:
            return
            
    # Проверка на бан владельца в боте
    user_data = await get_user_data(chat_id, banker_id)
    banker_status_text = "🔴 ЗАБАНЕН В БОТЕ" if user_data.get('is_banned') else "🟢 Активен"
    
    # Вкладчики
    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
    dep_docs_raw = await users_ref.where('bank_name', '==', banker_id).get()
    dep_docs = await _collect_docs(dep_docs_raw)
    total_deposits = sum(d.to_dict().get('bank_deposit', 0) for d in dep_docs)
    total_depositors = len(dep_docs)
    
    text = (
        f"🏛 <b>Банк: \"{escape_html(bank_data.get('name', 'Без названия'))}\"</b>\n\n"
        f"👤 Владелец: <b>{escape_html(bank_data.get('banker_name', 'Игрок'))}</b> (ID: <code>{banker_id}</code>)\n"
        f"🚨 Статус владельца: <b>{banker_status_text}</b>\n\n"
        f"💰 Капитал: <b>{bank_data.get('capital', 0):,}</b> сыр.\n"
        f"📈 Процент по вкладам: <b>{bank_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)}%</b> в день\n"
        f"👥 Вкладчиков: <b>{total_depositors}</b> (Всего вкладов: <b>{total_deposits:,}</b> сыр.)\n\n"
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
    
    if edit and isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        bot = callback_or_message.bot if hasattr(callback_or_message, 'bot') else callback_or_message.message.bot
        if isinstance(callback_or_message, types.CallbackQuery):
            msg = await callback_or_message.message.answer(text, reply_markup=builder.as_markup())
            await state.update_data(menu_message_id=msg.message_id)
            await callback_or_message.message.delete()
        else:
            state_data = await state.get_data()
            msg_id = state_data.get("menu_message_id")
            if msg_id:
                try:
                    await bot.edit_message_text(chat_id=callback_or_message.chat.id, message_id=msg_id, text=text, reply_markup=builder.as_markup())
                    return
                except Exception:
                    pass
            msg = await callback_or_message.answer(text, reply_markup=builder.as_markup())
            await state.update_data(menu_message_id=msg.message_id)

@router.callback_query(F.data.startswith("db_bv_"))
async def cb_bank_details(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    banker_id = int(parts[3])
    await show_bank_detail_screen(callback, state, chat_id, banker_id, edit=True)
    await callback.answer()

# Изменение капитала банка (Запрос)
@router.callback_query(F.data.startswith("db_bc_"))
async def cb_bank_capital_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    banker_id = int(parts[3])
    
    await state.set_state(AdminPanelState.waiting_for_bank_capital)
    await state.update_data(chat_id=chat_id, banker_id=banker_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    
    await callback.message.edit_text(
        "💰 <b>Изменение капитала банка</b>\n\n"
        "Введите новую сумму ликвидности (целое число сыроежек) в ответ на это сообщение:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода капитала
@router.message(AdminPanelState.waiting_for_bank_capital)
async def process_bank_capital_input(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    banker_id = state_data["banker_id"]
    
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
        if val < 0:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите положительное целое число. Попробуйте еще раз или напишите 'отмена'.")
        return
        
    # Обновляем капитал
    await create_or_update_bank(chat_id, banker_id, {'capital': val})
    invalidate_bank_cache(chat_id, banker_id)
    
    # Возвращаемся на экран банка
    await show_bank_detail_screen(message, state, chat_id, banker_id)
    try:
        await message.delete()
    except Exception:
        pass

# Изменение ставки процента (Запрос)
@router.callback_query(F.data.startswith("db_br_"))
async def cb_bank_rate_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    banker_id = int(parts[3])
    
    await state.set_state(AdminPanelState.waiting_for_bank_rate)
    await state.update_data(chat_id=chat_id, banker_id=banker_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    
    await callback.message.edit_text(
        f"📈 <b>Изменение процентной ставки вклада</b>\n\n"
        f"Введите процент в день (от {MIN_DEPOSIT_RATE}% до {MAX_DEPOSIT_RATE}%, можно дробью, например 4.5):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода ставки
@router.message(AdminPanelState.waiting_for_bank_rate)
async def process_bank_rate_input(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    banker_id = state_data["banker_id"]
    
    try:
        rate = float(message.text.replace(",", ".").strip())
        if rate < MIN_DEPOSIT_RATE or rate > MAX_DEPOSIT_RATE:
            raise ValueError()
    except ValueError:
        await message.answer(f"❌ Введите числовое значение от {MIN_DEPOSIT_RATE} до {MAX_DEPOSIT_RATE}. Попробуйте еще раз:")
        return
        
    await create_or_update_bank(chat_id, banker_id, {'deposit_rate': rate})
    invalidate_bank_cache(chat_id, banker_id)
    
    await show_bank_detail_screen(message, state, chat_id, banker_id)
    try:
        await message.delete()
    except Exception:
        pass

# Смена владельца банка (Запрос)
@router.callback_query(F.data.startswith("db_bo_"))
async def cb_bank_owner_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    banker_id = int(parts[3])
    
    await state.set_state(AdminPanelState.waiting_for_bank_new_owner)
    await state.update_data(chat_id=chat_id, banker_id=banker_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    
    await callback.message.edit_text(
        "👤 <b>Смена владельца банка</b>\n\n"
        "Отправьте @username (с символом @) или числовой Telegram ID нового владельца в ответ на это сообщение.\n\n"
        "<i>(Новый владелец получит статус Банкира, его балансы будут обновлены, а все вклады перенесены под его контроль)</i>",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода нового владельца
@router.message(AdminPanelState.waiting_for_bank_new_owner)
async def process_bank_owner_input(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    old_banker_id = state_data["banker_id"]
    
    identifier = message.text.strip()
    target_id, target_data = await get_user_by_username_or_id(chat_id, identifier)
    
    if not target_id:
        await message.answer("❌ Пользователь не найден в базе данных этого чата. Попробуйте ввести другой ID или @username:")
        return
        
    if int(target_id) == int(old_banker_id):
        await message.answer("❌ Этот пользователь уже является владельцем банка. Укажите другого человека:")
        return
        
    # Проверяем, нет ли уже банка у нового владельца
    existing_bank = await get_bank_info(chat_id, target_id)
    if existing_bank:
        await message.answer(f"❌ У пользователя уже есть банк: <b>{escape_html(existing_bank.get('name'))}</b>. Нельзя владеть двумя банками!")
        return
        
    try:
        # Процесс переноса владельца банка
        db = get_db()
        old_bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(old_banker_id))
        new_bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(target_id))
        
        # Получаем данные банка
        bank_doc = await old_bank_ref.get()
        if not bank_doc.exists:
            await message.answer("❌ Банк не найден.")
            return
            
        bank_data = bank_doc.to_dict()
        
        # Переносим владельца в документе банка
        bank_data['banker_name'] = target_data.get('full_name', 'Игрок')
        
        # Записываем новый док, удаляем старый
        await new_bank_ref.set(bank_data)
        await old_bank_ref.delete()
        
        # Меняем поле is_banker у пользователей
        await update_user_field(chat_id, target_id, 'is_banker', True)
        await update_user_field(chat_id, old_banker_id, 'is_banker', False)
        
        # Находим всех вкладчиков старого банка в группе и перенаправляем на новый
        users_ref = db.collection('chats').document(str(chat_id)).collection('users')
        dep_docs_raw = await users_ref.where('bank_name', '==', old_banker_id).get()
        dep_docs = await _collect_docs(dep_docs_raw)
        
        updated_depositors_count = 0
        for doc in dep_docs:
            uid = int(doc.id) if doc.id.isdigit() else doc.id
            await update_user_field(chat_id, uid, 'bank_name', target_id)
            await flush_user_cache_immediately(chat_id, uid)
            updated_depositors_count += 1
            
        # Записываем изменения банкиров в базу данных немедленно
        await flush_user_cache_immediately(chat_id, old_banker_id)
        await flush_user_cache_immediately(chat_id, target_id)
        invalidate_bank_cache(chat_id, old_banker_id, bank_data.get('name'))
        invalidate_bank_cache(chat_id, target_id, bank_data.get('name'))
        
        # Оповещаем админа
        await message.answer(
            f"✅ <b>Владелец банка успешно изменен!</b>\n\n"
            f"🏛 Банк: \"{escape_html(bank_data.get('name'))}\"\n"
            f"👤 Прежний владелец: <code>{old_banker_id}</code>\n"
            f"👤 Новый владелец: <b>{escape_html(target_data.get('full_name'))}</b> (<code>{target_id}</code>)\n"
            f"👥 Перенаправлено вкладчиков: {updated_depositors_count}"
        )
        
        await show_bank_detail_screen(message, state, chat_id, target_id)
        try:
            await message.delete()
        except Exception:
            pass
            
    except Exception as e:
        await message.answer(f"❌ Произошла техническая ошибка при переносе:\n<code>{escape_html(str(e))}</code>")

# Экран удаления банка (Подтверждение)
@router.callback_query(F.data.startswith("db_bd_"))
async def cb_bank_delete_confirm_screen(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    banker_id = int(parts[3])
    
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await callback.answer("Банк не найден.")
        
    text = (
        f"⚠️ <b>Внимание! Удаление банка \"{escape_html(bank_data.get('name'))}\"</b>\n\n"
        f"Вы хотите удалить банк. Выберите тип удаления:\n\n"
        f"1. <b>Удалить с возвратом средств вкладчиков (Рекомендуется)</b> — все вклады "
        f"будут возвращены на балансы игроков наличными.\n"
        f"2. <b>Списать без возврата</b> — банк будет стерт, все вклады игроков сгорят."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить и вернуть средства", callback_data=f"db_bdc_{chat_id}_{banker_id}_refund")
    builder.button(text="🔥 Списать без возврата (Вайп)", callback_data=f"db_bdc_{chat_id}_{banker_id}_norefund")
    builder.button(text="❌ Отмена", callback_data=f"db_bv_{chat_id}_{banker_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Действие: удаление банка
@router.callback_query(F.data.startswith("db_bdc_"))
async def cb_perform_bank_delete(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    banker_id = int(parts[3])
    mode = parts[4] # 'refund' или 'norefund'
    
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await callback.answer("Банк не найден.", show_alert=True)
        
    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
    dep_docs_raw = await users_ref.where('bank_name', '==', banker_id).get()
    dep_docs = await _collect_docs(dep_docs_raw)
    
    total_refunded = 0
    depositors_count = 0
    
    for doc in dep_docs:
        u_data = doc.to_dict() or {}
        uid = int(doc.id) if doc.id.isdigit() else doc.id
        dep_amt = u_data.get('bank_deposit', 0)
        
        if mode == 'refund' and dep_amt > 0:
            # Возвращаем на баланс
            await update_user_balance(chat_id, uid, dep_amt, action="Bank Delete Refund")
            total_refunded += dep_amt
            
        # Сбрасываем банковские поля
        await update_user_field(chat_id, uid, 'bank_deposit', 0)
        await update_user_field(chat_id, uid, 'bank_name', None)
        await update_user_field(chat_id, uid, 'deposit_start_time', 0)
        await flush_user_cache_immediately(chat_id, uid)
        depositors_count += 1
        
    # Снимаем статус банкира
    await update_user_field(chat_id, banker_id, 'is_banker', False)
    await flush_user_cache_immediately(chat_id, banker_id)
    
    # Удаляем документ банка
    bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(banker_id))
    await bank_ref.delete()
    invalidate_bank_cache(chat_id, banker_id, bank_data.get('name'))
    
    result_text = ""
    if mode == 'refund':
        result_text = f"✅ Банк <b>\"{escape_html(bank_data.get('name'))}\"</b> удален.\n👥 Возвращены вклады: {depositors_count} игрокам на сумму {total_refunded:,} сыр."
    else:
        result_text = f"🔥 Банк <b>\"{escape_html(bank_data.get('name'))}\"</b> стерт из базы.\n👥 Аннулированы вклады: {depositors_count} игроков. Деньги сгорели."
        
    await callback.message.edit_text(result_text)
    await callback.answer(show_alert=True, text="Банк успешно удален!")
    
    # Спустя секунду возвращаемся к списку банков
    await asyncio.sleep(2.0)
    await cb_banks_list(callback, state)

# Назначить банкира и создать банк (Ввод ID игрока)
@router.callback_query(F.data.startswith("db_bcr_"))
async def cb_bank_create_user_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    chat_id = int(callback.data.split("_")[2])
    
    await state.set_state(AdminPanelState.waiting_for_bank_create_user)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_b_{chat_id}")
    
    await callback.message.edit_text(
        "➕ <b>Назначение банкира и создание банка</b>\n\n"
        "Шаг 1: Введите @username или Telegram ID будущего банкира в ответ на это сообщение:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода ID банкира для создания банка
@router.message(AdminPanelState.waiting_for_bank_create_user)
async def process_bank_create_user_input(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    
    identifier = message.text.strip()
    target_id, target_data = await get_user_by_username_or_id(chat_id, identifier)
    
    if not target_id:
        await message.answer("❌ Игрок не найден в базе чата. Попробуйте еще раз:")
        return
        
    # Проверяем, нет ли уже банка
    existing = await get_bank_info(chat_id, target_id)
    if existing:
        await message.answer(f"❌ У пользователя уже есть банк: <b>{escape_html(existing.get('name'))}</b>. Сначала удалите его банк или выберите другого банкира.")
        return
        
    await state.set_state(AdminPanelState.waiting_for_bank_create_name)
    await state.update_data(target_user_id=target_id, target_name=target_data.get('full_name', 'Банкир'))
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_b_{chat_id}")
    
    await message.answer(
        f"➕ <b>Назначение банкира: {escape_html(target_data.get('full_name'))}</b>\n\n"
        f"Шаг 2: Введите НАЗВАНИЕ для нового банка:",
        reply_markup=builder.as_markup()
    )
    try:
        await message.delete()
    except Exception:
        pass

# Обработчик ввода названия банка для его создания
@router.message(AdminPanelState.waiting_for_bank_create_name)
async def process_bank_create_name_input(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    target_name = state_data["target_name"]
    bank_name = message.text.strip()[:60]
    
    # Делаем банкиром в профиле
    await update_user_field(chat_id, target_id, 'is_banker', True)
    await flush_user_cache_immediately(chat_id, target_id)
    
    # Создаем банк
    await create_or_update_bank(chat_id, target_id, {
        'name': bank_name,
        'capital': 0,
        'banker_name': target_name,
        'deposit_rate': DEFAULT_DEPOSIT_RATE,
    })
    invalidate_bank_cache(chat_id, target_id, bank_name)
    
    await message.answer(f"🏛 Банк <b>\"{escape_html(bank_name)}\"</b> успешно создан, банкир назначен!")
    await show_bank_detail_screen(message, state, chat_id, target_id)
    try:
        await message.delete()
    except Exception:
        pass

# ===================== РАЗДЕЛ: ИГРОКИ =====================

# Поиск игрока (Экран ввода)
@router.callback_query(F.data.startswith("db_p_"))
async def cb_player_search_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    chat_id = int(callback.data.split("_")[2])
    
    await state.set_state(AdminPanelState.waiting_for_player_search)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_m_{chat_id}")
    
    await callback.message.edit_text(
        "🔍 <b>Управление игроками</b>\n\n"
        "Отправьте @username или числовой Telegram ID игрока для настройки его параметров:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода поиска игрока
@router.message(AdminPanelState.waiting_for_player_search)
async def process_player_search_input(message: types.Message, state: FSMContext):
    if not is_creator(message):
        return
        
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    
    identifier = message.text.strip()
    target_id, target_data = await get_user_by_username_or_id(chat_id, identifier)
    
    if not target_id:
        await message.answer("❌ Игрок не найден в базе чата. Попробуйте еще раз:")
        return
        
    await show_player_details_screen(message, state, chat_id, target_id)
    try:
        await message.delete()
    except Exception:
        pass

# Отредактированный профиль игрока в меню
async def show_player_details_screen(callback_or_message, state: FSMContext, chat_id: int, target_id: int, edit=False):
    data = await get_user_data(chat_id, target_id)
    
    vip_status = "👑 Да" if data.get('is_vip') else "❌ Нет"
    banker_status = "💼 Да" if data.get('is_banker') else "❌ Нет"
    ban_status = "🚫 Забанен" if data.get('is_banned') else "🟢 Активен"
    hidden_status = "👁 Скрыт" if data.get('hide_in_top') else "🟢 Виден"
    warns_count = len(data.get('warns', []))
    balance = data.get('balance', 0)
    full_name = escape_html(data.get('full_name', 'Игрок'))
    username = data.get('username', 'нет')
    reputation = data.get('reputation', 0)
    
    # Питомец
    pet = data.get('pet')
    pet_text = "Нет"
    if isinstance(pet, dict):
        from pets import PETS_SHOP
        p_id = pet.get('id')
        p_name = PETS_SHOP.get(p_id, {}).get('name', p_id)
        last_fed = pet.get('last_fed', 0)
        fed_hours_ago = (time.time() - last_fed) / 3600
        if fed_hours_ago > 48:
            pet_text = f"{p_name} (Сбежал/Голодает)"
        else:
            pet_text = f"{p_name} (Сыт, кормили {int(fed_hours_ago)}ч назад)"
            
    # Навыки
    skills = data.get('skills', {})
    from skills import SKILLS
    sk_list = []
    for sk_id, sk_cfg in SKILLS.items():
        lvl = skills.get(sk_id, 0)
        sk_list.append(f"{sk_cfg.get('name', sk_id)}: {lvl}/5")
    sk_text = " | ".join(sk_list) if sk_list else "Нет"
    
    # Долги
    debts = data.get('debts', {})
    total_debt = 0
    if isinstance(debts, dict):
        total_debt = sum(debts.values())
    debt_text = f"<b>{total_debt:,}</b> сыр." if total_debt > 0 else "Нет"
    
    # Болезни
    from diseases import get_active_diseases, DISEASES
    active_dis = await get_active_diseases(chat_id, target_id, u_data=data)
    dis_list = [DISEASES[d]['name'] for d in active_dis if d in DISEASES]
    dis_text = ", ".join(dis_list) if dis_list else "Здоров(а)"
    
    inventory = data.get('inventory', {})
    inv_list = []
    from shop import ITEMS
    for k, v in inventory.items():
        item_cfg = ITEMS.get(k, {})
        item_name = item_cfg.get('name', k)
        inv_list.append(f"{item_name} (x{v})")
    inv_text = ", ".join(inv_list) if inv_list else "Пусто"
    
    text = (
        f"👤 <b>Управление игроком: {full_name}</b>\n"
        f"📱 ID: <code>{target_id}</code> | 🏷 @{username}\n\n"
        f"💰 Баланс: <b>{balance:,}</b> сыр.\n"
        f"📈 Репутация: <b>{reputation}</b>\n"
        f"💸 Долги: {debt_text}\n"
        f"👑 VIP: <b>{vip_status}</b>\n"
        f"💼 Банкир: <b>{banker_status}</b>\n"
        f"🚫 Статус: <b>{ban_status}</b>\n"
        f"👁 В топе: <b>{hidden_status}</b>\n"
        f"⚠️ Варны: <b>{warns_count}/3</b>\n"
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
    builder.button(text="🔄 Сбросить FSM", callback_data=f"db_pfsm_reset_{chat_id}_{target_id}")
    builder.button(text="⚡️ Казнить!", callback_data=f"db_pexecute_ask_{chat_id}_{target_id}")
    builder.button(text="🧹 Полный сброс", callback_data=f"db_pwi_{chat_id}_{target_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_m_{chat_id}")
    builder.adjust(2, 2, 2, 2, 3, 3, 2, 2, 1)
    
    markup = builder.as_markup()
    bot = callback_or_message.bot if hasattr(callback_or_message, 'bot') else callback_or_message.message.bot
    
    if edit and isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.message.edit_text(text, reply_markup=markup)
    else:
        if isinstance(callback_or_message, types.CallbackQuery):
            msg = await callback_or_message.message.answer(text, reply_markup=markup)
            await state.update_data(menu_message_id=msg.message_id)
            await callback_or_message.message.delete()
        else:
            state_data = await state.get_data()
            msg_id = state_data.get("menu_message_id")
            if msg_id:
                try:
                    await bot.edit_message_text(chat_id=callback_or_message.chat.id, message_id=msg_id, text=text, reply_markup=markup)
                    return
                except Exception:
                    pass
            msg = await callback_or_message.answer(text, reply_markup=markup)
            await state.update_data(menu_message_id=msg.message_id)

@router.callback_query(F.data.startswith("db_pv_"))
async def cb_player_details_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback):
        return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)
    await callback.answer()

# Кнопки быстрых действий игрока:
@router.callback_query(F.data.startswith("db_ptv_"))
async def cb_toggle_vip(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    new_val = not data.get('is_vip', False)
    await update_user_field(chat_id, target_id, 'is_vip', new_val)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await callback.answer(f"VIP-статус установлен: {new_val}")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

@router.callback_query(F.data.startswith("db_ptb_"))
async def cb_toggle_banker_role(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    new_val = not data.get('is_banker', False)
    await update_user_field(chat_id, target_id, 'is_banker', new_val)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await callback.answer(f"Статус банкира установлен: {new_val}")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

@router.callback_query(F.data.startswith("db_ptban_"))
async def cb_toggle_user_ban(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    new_val = not data.get('is_banned', False)
    await update_user_field(chat_id, target_id, 'is_banned', new_val)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await callback.answer(f"Бан-статус в боте установлен: {new_val}")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

@router.callback_query(F.data.startswith("db_pth_"))
async def cb_toggle_user_top_hide(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    new_val = not data.get('hide_in_top', False)
    await update_user_field(chat_id, target_id, 'hide_in_top', new_val)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await callback.answer(f"Скрытность в топе установлена: {new_val}")
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

@router.callback_query(F.data.startswith("db_pwa_"))
async def cb_add_user_warn(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    warns = list(data.get('warns', []) or [])
    warns.append({
        "reason": "Выдано через Единую Панель Создателя",
        "time": int(time.time()),
        "by": callback.from_user.id
    })
    
    await update_user_field(chat_id, target_id, 'warns', warns)
    await flush_user_cache_immediately(chat_id, target_id)
    
    if len(warns) >= 3:
        await update_user_field(chat_id, target_id, 'is_banned', True)
        await flush_user_cache_immediately(chat_id, target_id)
        try:
            await callback.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        except Exception:
            pass
        await callback.answer("Варн выдан! Пользователь забанен за 3/3 варнов.", show_alert=True)
    else:
        await callback.answer(f"Предупреждение выдано. Всего: {len(warns)}/3")
        
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

@router.callback_query(F.data.startswith("db_pwr_"))
async def cb_remove_user_warn(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    warns = list(data.get('warns', []) or [])
    if warns:
        warns.pop()
        await update_user_field(chat_id, target_id, 'warns', warns)
        await flush_user_cache_immediately(chat_id, target_id)
        await callback.answer(f"Один варн успешно снят. Осталось: {len(warns)}/3")
    else:
        await callback.answer("У этого игрока нет предупреждений.", show_alert=True)
        
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

@router.callback_query(F.data.startswith("db_pwi_"))
async def cb_confirm_player_wipe_screen(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    text = (
        f"⚠️ <b>ВНИМАНИЕ: Вайп игрока</b>\n\n"
        f"Вы действительно хотите полностью обнулить профиль игрока ID <code>{target_id}</code>?\n"
        f"Будут сброшены деньги, инвентарь, бизнесы, крипта, питомцы и скиллы. Это действие необратимо!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🧹 Подтвердить полный сброс", callback_data=f"db_pwic_{chat_id}_{target_id}")
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("db_pwic_"))
async def cb_perform_player_wipe(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    from user_manager import wipe_user_data
    success = await wipe_user_data(chat_id, target_id)
    
    if success:
        await callback.answer("Данные игрока полностью обнулены!", show_alert=True)
    else:
        await callback.answer("Не удалось сбросить данные.", show_alert=True)
        
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)

# Запросы ввода для изменения балансов игрока
@router.callback_query(F.data.startswith("db_pma_"))
async def cb_player_money_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    await state.set_state(AdminPanelState.waiting_for_player_money_add)
    await state.update_data(chat_id=chat_id, target_user_id=target_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    
    await callback.message.edit_text(
        "💵 <b>Выдача сыроежек игроку</b>\n\n"
        "Введите сумму сыроежек для зачисления (для списания введите со знаком минус, например -500000) в ответ на это сообщение:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminPanelState.waiting_for_player_money_add)
async def process_player_money_add(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("❌ Сумма должна быть целым числом. Попробуйте еще раз:")
        return
        
    await update_user_balance(chat_id, target_id, val, action="Creator Panel Give")
    await flush_user_cache_immediately(chat_id, target_id)
    
    await message.answer(f"✅ Баланс успешно изменен на {val:+,} сыроежек.")
    await show_player_details_screen(message, state, chat_id, target_id)
    try:
        await message.delete()
    except Exception:
        pass

@router.callback_query(F.data.startswith("db_pms_"))
async def cb_player_money_set_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    await state.set_state(AdminPanelState.waiting_for_player_money_set)
    await state.update_data(chat_id=chat_id, target_user_id=target_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    
    await callback.message.edit_text(
        "💰 <b>Установка точного баланса игроку</b>\n\n"
        "Введите новую точную сумму наличного баланса игрока:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminPanelState.waiting_for_player_money_set)
async def process_player_money_set(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
        if val < 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное положительное число:")
        return
        
    await update_user_field(chat_id, target_id, 'balance', val)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await message.answer(f"✅ Установлен точный баланс: {val:,} сыроежек.")
    await show_player_details_screen(message, state, chat_id, target_id)
    try:
        await message.delete()
    except Exception:
        pass

# ===================== РАЗДЕЛ: ГРУППА =====================

@router.callback_query(F.data.startswith("db_g_"))
async def cb_group_settings_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    # Читаем шпионов, заблокированных и админ права
    spy_chats = await get_spy_chats()
    locked_chats = await get_locked_chats()
    
    spy_status = "👁 ВКЛЮЧЕН" if chat_id in spy_chats else "🙈 Выключен"
    lock_status = "🔒 Заблокирована" if chat_id in locked_chats else "🔓 Штатный режим"
    
    bot_member = None
    admin_status = "Неизвестно"
    try:
        bot_member = await callback.bot.get_chat_member(chat_id, callback.bot.id)
        admin_status = "✅ Да (Админ)" if bot_member.status in ['administrator', 'creator'] else f"❌ Нет ({bot_member.status})"
    except Exception as e:
        admin_status = f"❌ Ошибка проверки ({e})"
        
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
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("db_gs_"))
async def cb_toggle_group_spy(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    is_enabled = await toggle_spy(chat_id)
    status_str = "включен" if is_enabled else "выключен"
    await callback.answer(f"Режим шпионажа {status_str} для чата.", show_alert=True)
    await cb_group_settings_view(callback, state)

@router.callback_query(F.data.startswith("db_glk_"))
async def cb_toggle_group_lock(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    is_enabled = await toggle_lock(chat_id)
    status_str = "заблокирован (требуются права админа)" if is_enabled else "разблокирован"
    await callback.answer(f"Доступ бота {status_str}.", show_alert=True)
    await cb_group_settings_view(callback, state)

@router.callback_query(F.data.startswith("db_gl_"))
async def cb_export_invite_link(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    try:
        link = await callback.bot.export_chat_invite_link(chat_id=chat_id)
        await callback.message.answer(f"🔗 Ссылка на группу <code>{chat_id}</code>:\n{link}")
        await callback.answer("Ссылка успешно экспортирована!")
    except Exception as e:
        await callback.answer(f"❌ Ошибка экспорта: {e}", show_alert=True)

# Отправка сообщений в группу (Запрос)
@router.callback_query(F.data.startswith("db_gsy_"))
async def cb_group_say_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    await state.set_state(AdminPanelState.waiting_for_say_text)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🛑 Остановить трансляцию", callback_data=f"db_stop_say_{chat_id}")
    
    await callback.message.edit_text(
        "📣 <b>Трансляция сообщений в группу от имени бота</b>\n\n"
        "Все отправленные вами сообщения (текст, фото, стикеры, GIF и т.д.) "
        "будут автоматически пересылаться в группу.\n\n"
        "Для завершения трансляции нажмите кнопку ниже:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("db_stop_say_"))
async def cb_stop_group_say(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[3])
    await state.clear()
    await callback.answer("Трансляция остановлена")
    callback.data = f"db_g_{chat_id}"
    await cb_group_settings_view(callback, state)

@router.message(AdminPanelState.waiting_for_say_text)
async def process_group_say_text(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data.get("chat_id")
    if not chat_id:
        return
    
    try:
        await message.send_copy(chat_id=chat_id)
        sent = await message.answer("✅ Отправлено")
        async def delete_later(msg, delay):
            await asyncio.sleep(delay)
            try:
                await msg.delete()
            except Exception:
                pass
        asyncio.create_task(delete_later(sent, 2))
    except Exception as e:
        sent_err = await message.answer(f"❌ Ошибка отправки: {e}")
        async def delete_later(msg, delay):
            await asyncio.sleep(delay)
            try:
                await msg.delete()
            except Exception:
                pass
        asyncio.create_task(delete_later(sent_err, 5))
        
    try:
        await message.delete()
    except Exception:
        pass

# ===================== РАЗДЕЛ: ГЛОБАЛЬНЫЕ НАСТРОЙКИ =====================

GAMES_CHANCE_LIST = [
    ('slots', '🎰 Slots (Слоты)'),
    ('cups', '🥤 Cups (Стаканчики)'),
    ('roulette', '🎡 Roulette (Рулетка)'),
    ('blackjack', '🃏 Blackjack (Блэкджек)'),
    ('baccarat', '🃏 Baccarat (Баккара)'),
    ('craps', '🎲 Craps (Кости)'),
    ('poker', '🃏 Poker (Видеопокер)'),
    ('crash', '🚀 Crash (Авиатор)'),
]

@router.callback_query(F.data.startswith("db_glob_"))
async def cb_global_settings_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2]) # Может быть 0, если из ЛС
    
    tax = await get_global_tax()
    
    def format_chance(ch):
        return f"{ch}%" if ch != -1 else "Честный рандом"

    chances_text = ""
    for game_id, game_title in GAMES_CHANCE_LIST:
        ch = await get_game_chance(game_id)
        if game_id == 'crash':
            chances_text += f"  • {game_title}: <b>{format_chance(ch)}</b> (Ист. краш: {f'{100 - ch}%' if ch != -1 else '10%'})\n"
        else:
            chances_text += f"  • {game_title}: <b>{format_chance(ch)}</b>\n"
            
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
    
    if chat_id != 0:
        builder.button(text="⬅️ Назад к меню группы", callback_data=f"db_m_{chat_id}")
    else:
        builder.button(text="⬅️ К выбору чатов", callback_data="db_sc_0")
        
    builder.adjust(2, 2, 2, 1, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Глобальный налог (Запрос)
@router.callback_query(F.data.startswith("db_gt_"))
async def cb_global_tax_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    await state.set_state(AdminPanelState.waiting_for_global_tax)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_glob_{chat_id}")
    
    await callback.message.edit_text(
        "💸 <b>Изменение базовой ставки налога</b>\n\n"
        "Введите новый процент налога (целое число от 0 до 100) в ответ на это сообщение.\n"
        "<i>(Все группы будут оповещены об изменении налога)</i>",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminPanelState.waiting_for_global_tax)
async def process_global_tax_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    
    try:
        tax = int(message.text.replace(" ", ""))
        if tax < 0 or tax > 100: raise ValueError()
    except ValueError:
        await message.answer("❌ Процент налога должен быть целым числом от 0 до 100. Введите корректное значение:")
        return
        
    await set_global_tax(tax)
    
    # Оповещаем все чаты из белого списка
    whitelist = await get_whitelist()
    phrases = [
        f"🏛 <b>Указ Казначейства:</b> Налоговая ставка изменена. Теперь налог составляет <b>{tax}%</b>.",
        f"📢 <b>Экономические реформы:</b> Базовый налог на переводы установлен на уровне <b>{tax}%</b>."
    ]
    announcement = phrases[0] if tax >= 15 else phrases[1]
    
    notified = 0
    for cid in whitelist.keys():
        try:
            await message.bot.send_message(chat_id=cid, text=announcement)
            notified += 1
        except Exception:
            pass
            
    await message.answer(f"✅ Базовый налог установлен на {tax}%. Уведомлено {notified} чатов.")
    await state.clear()
    await show_group_main_screen(message, state, chat_id) if chat_id != 0 else await show_chat_select_screen(message, state)
    try:
        await message.delete()
    except Exception:
        pass

# Настройка шансов победы (Меню выбора игры)
@router.callback_query(F.data.startswith("db_gch_"))
async def cb_game_chances_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    def fmt(ch):
        return f"{ch}%" if ch != -1 else "Честный рандом"
        
    chances_text = ""
    builder = InlineKeyboardBuilder()
    for game_id, game_title in GAMES_CHANCE_LIST:
        ch = await get_game_chance(game_id)
        if game_id == 'crash':
            ch_str = f"{ch}% (Ист. краш: {100 - ch}%)" if ch != -1 else "Честный рандом"
        else:
            ch_str = f"{ch}%" if ch != -1 else "Честный рандом"
        chances_text += f"  • {game_title}: <b>{ch_str}</b>\n"
        # Extract the pure title without emojis and parentheses for the button
        btn_label = game_title.split("(")[0].strip()
        # strip emojis
        btn_label = "".join([c for c in btn_label if ord(c) < 127 or ord(c) > 255]).strip()
        if not btn_label:
            # Fallback if stripping emojis leaves it empty
            btn_label = game_id.upper()
        builder.button(text=btn_label, callback_data=f"db_gsc_{chat_id}_{game_id}")
        
    text = (
        f"🎰 <b>Настройка принудительных шансов победы</b>\n\n"
        f"Укажите игру для изменения шанса:\n\n"
        f"{chances_text}"
    )
    
    builder.button(text="⬅️ Назад к настройкам", callback_data=f"db_glob_{chat_id}")
    builder.adjust(2, 2, 2, 2, 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Принудительный шанс для конкретной игры (Запрос)
@router.callback_query(F.data.startswith("db_gsc_"))
async def cb_game_chance_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    game_name = parts[3]
    
    await state.set_state(AdminPanelState.waiting_for_chance_val)
    await state.update_data(chat_id=chat_id, game_name=game_name, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_gch_{chat_id}")
    
    await callback.message.edit_text(
        f"🎰 <b>Настройка шанса для игры: {game_name.upper()}</b>\n\n"
        f"Введите целое число процентов (0-100) принудительной победы игрока.\n"
        f"<i>(Введите -1 для включения честного рандома)</i>:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminPanelState.waiting_for_chance_val)
async def process_game_chance_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    game_name = state_data["game_name"]
    
    try:
        val = int(message.text.replace(" ", ""))
        if val < -1 or val > 100: raise ValueError()
    except ValueError:
        await message.answer("❌ Процент должен быть числом от -1 до 100. Введите корректно:")
        return
        
    await set_game_chance(game_name, val)
    await message.answer(f"✅ Для игры <b>{game_name}</b> установлен шанс победы: {val}%" if val != -1 else f"✅ В игре <b>{game_name}</b> включен честный рандом.")
    
    await state.clear()
    # Возвращаемся в меню шансов
    bot = message.bot
    await cb_game_chances_menu(MockCallback(message, state_data.get("menu_message_id"), f"db_gch_{chat_id}"), state)
    try:
        await message.delete()
    except Exception:
        pass

# Белый список групп (Список с удалением)
@router.callback_query(F.data.startswith("db_gwl_"))
async def cb_whitelist_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    whitelist = await get_whitelist()
    text = "📝 <b>Управление Белым Списком групп</b>\n\nСписок разрешенных чатов:"
    builder = InlineKeyboardBuilder()
    
    if not whitelist:
        text += "\n<i>Список пуст.</i>"
    else:
        for cid, title in whitelist.items():
            builder.button(text=f"❌ {escape_html(title)} ({cid})", callback_data=f"db_gwlr_{chat_id}_{cid}")
            
    builder.button(text="➕ Разрешить чат (Добавить ID)", callback_data=f"db_gwla_{chat_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Удаление чата из белого списка
@router.callback_query(F.data.startswith("db_gwlr_"))
async def cb_whitelist_remove_perform(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    remove_id = int(parts[3])
    
    success = await remove_from_whitelist(remove_id)
    if success:
        await callback.answer(f"Группа {remove_id} удалена из белого списка.")
    else:
        await callback.answer("Ошибка удаления.")
        
    await cb_whitelist_view(callback, state)

# Добавление группы в белый список (Запрос ID)
@router.callback_query(F.data.startswith("db_gwla_"))
async def cb_whitelist_add_id_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    await state.set_state(AdminPanelState.waiting_for_whitelist_id)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_gwl_{chat_id}")
    
    await callback.message.edit_text(
        "📝 <b>Добавление группы в белый список</b>\n\n"
        "Шаг 1: Введите числовой ID группы (обычно начинается с -100):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminPanelState.waiting_for_whitelist_id)
async def process_whitelist_id_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    
    try:
        cid = int(message.text.replace(" ", ""))
    except ValueError:
        await message.answer("❌ ID чата должен быть целым числом. Попробуйте еще раз:")
        return
        
    await state.set_state(AdminPanelState.waiting_for_whitelist_title)
    await state.update_data(target_chat_id=cid)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_gwl_{chat_id}")
    
    await message.answer(
        f"📝 <b>Добавление группы {cid}</b>\n\n"
        f"Шаг 2: Введите название для этой группы в списке:",
        reply_markup=builder.as_markup()
    )
    try:
        await message.delete()
    except Exception:
        pass

@router.message(AdminPanelState.waiting_for_whitelist_title)
async def process_whitelist_title_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    cid = state_data["target_chat_id"]
    title = message.text.strip()
    
    await add_to_whitelist(cid, title)
    await message.answer(f"✅ Группа <b>{escape_html(title)}</b> ({cid}) успешно добавлена в белый список.")
    
    await state.clear()
    
    await cb_whitelist_view(MockCallback(message, state_data.get("menu_message_id"), f"db_gwl_{chat_id}"), state)
    try:
        await message.delete()
    except Exception:
        pass

# Раздел глобальных вайпов экономики
@router.callback_query(F.data.startswith("db_gwipes_"))
async def cb_global_wipes_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    
    text = (
        f"🧹 <b>Глобальные вайпы экономики бота</b>\n\n"
        f"⚠️ <b>ВНИМАНИЕ:</b> Эти действия сбросят экономику у ВСЕХ игроков во ВСЕХ чатах!\n\n"
        f"• <b>Сброс балансов (Soft-Wipe)</b>: Сбросит наличные и банковские депозиты до 500 сыр.\n"
        f"• <b>Средний вайп (Mid-Wipe)</b>: Сбросит деньги, удалит инвентари, машины, бизнесы, VIP-статусы и обнулит крипторынок.\n"
        f"• <b>Полный вайп (Full-Wipe)</b>: Полное удаление экономики. Сброс денег, инвентарей, долгов, питомцев, скиллов, кланов, крипты."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Сбросить балансы (Только деньги)", callback_data=f"db_gwc_{chat_id}_balances")
    builder.button(text="📦 Средний вайп экономики", callback_data=f"db_gwc_{chat_id}_mid")
    builder.button(text="🔥 Полный вайп экономики (Глобально)", callback_data=f"db_gwc_{chat_id}_economy")
    builder.button(text="⬅️ Назад", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Выполнение глобального вайпа (Подтверждение и процесс)
@router.callback_query(F.data.startswith("db_gwc_"))
async def cb_global_wipe_action(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer("❌ Нет доступа.", show_alert=True)
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    wipe_type = parts[3]
    
    # Чтобы избежать случайных нажатий, при первом клике на эту кнопку покажем подтверждение с текстом CONFIRM
    # Но мы можем сделать более удобное подтверждение прямо кнопками
    # Проверим, есть ли параметр confirm
    if len(parts) < 5 or parts[4] != "confirmed":
        # Экран двойного подтверждения
        type_names = {
            'balances': 'Сброс балансов (Soft-Wipe)',
            'mid': 'Средний вайп экономики',
            'economy': 'ГЛОБАЛЬНЫЙ ВАЙП ЭКОНОМИКИ'
        }
        text = (
            f"🚨 <b>ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ!</b> 🚨\n\n"
            f"Вы выбрали действие: <b>{type_names.get(wipe_type, wipe_type)}</b>\n"
            f"Это действие затронет всех игроков бота. Вы абсолютно уверены?"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="💥 ПОДТВЕРДИТЬ СБРОС", callback_data=f"db_gwc_{chat_id}_{wipe_type}_confirmed")
        builder.button(text="❌ Отмена", callback_data=f"db_gwipes_{chat_id}")
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        return await callback.answer()
        
    # Действие подтверждено, выполняем
    status_msg = await callback.message.answer("🔄 <i>Начинаю сброс экономики во всех чатах. Пожалуйста, подождите...</i>")
    
    db = get_db()
    _user_cache.clear() # Чистим локальный кэш юзеров
    
    whitelist = await get_whitelist()
    users_wiped = 0
    clans_wiped = 0
    
    try:
        # Балансы и вклады
        if wipe_type == 'balances':
            for cid in whitelist.keys():
                users_ref = db.collection('chats').document(str(cid)).collection('users')
                user_docs = await users_ref.get()
                
                batch = db.batch()
                count = 0
                for doc in user_docs:
                    if doc.id:
                        batch.set(users_ref.document(doc.id), {
                            'balance': 500,
                            'bank_deposit': 0
                        }, merge=True)
                        users_wiped += 1
                        count += 1
                        if count >= 500:
                            await batch.commit()
                            batch = db.batch()
                            count = 0
                if count > 0:
                    await batch.commit()
            
            await status_msg.edit_text(f"✅ <b>Вайп балансов завершен!</b>\n👤 Обнулено денег у игроков: <b>{users_wiped}</b>.")
            
        # Средний вайп
        elif wipe_type == 'mid':
            # Вайпаем крипту
            current_time = int(time.time())
            default_coins = {
                "chsyr": {"name": "Китайская Сыроежка", "ticker": "CH_SYR", "prices":[random.randint(100, 500)], "creator": 0},
                "espsyr": {"name": "Испанская Сыроежка", "ticker": "ESP_SYR", "prices":[random.randint(100, 500)], "creator": 0}
            }
            await db.collection('bot_settings').document('crypto_coins').set({
                'coins': default_coins,
                'last_update': current_time
            })
            
            for cid in whitelist.keys():
                users_ref = db.collection('chats').document(str(cid)).collection('users')
                user_docs = await users_ref.get()
                
                batch = db.batch()
                count = 0
                for doc in user_docs:
                    if doc.id:
                        batch.set(users_ref.document(doc.id), {
                            'balance': 500,
                            'inventory': {},
                            'is_vip': False
                        }, merge=True)
                        users_wiped += 1
                        count += 1
                        if count >= 500:
                            await batch.commit()
                            batch = db.batch()
                            count = 0
                if count > 0:
                    await batch.commit()
            
            await status_msg.edit_text(f"✅ <b>Средний вайп завершен!</b>\n👤 Обнулено игроков: <b>{users_wiped}</b>\n📈 Биржа перезапущена.")
            
        # Глобальный вайп экономики
        elif wipe_type == 'economy':
            # Вайпаем крипту
            current_time = int(time.time())
            default_coins = {
                "chsyr": {"name": "Китайская Сыроежка", "ticker": "CH_SYR", "prices":[random.randint(100, 500)], "creator": 0},
                "espsyr": {"name": "Испанская Сыроежка", "ticker": "ESP_SYR", "prices":[random.randint(100, 500)], "creator": 0}
            }
            await db.collection('bot_settings').document('crypto_coins').set({
                'coins': default_coins,
                'last_update': current_time
            })
            
            for cid in whitelist.keys():
                # Пользователи
                users_ref = db.collection('chats').document(str(cid)).collection('users')
                user_docs = await users_ref.get()
                
                batch = db.batch()
                count = 0
                for doc in user_docs:
                    if doc.id:
                        batch.set(users_ref.document(doc.id), {
                            'balance': 500,
                            'bank_deposit': 0,
                            'inventory': {},
                            'debts': {},
                            'skills': {},
                            'pet': None
                        }, merge=True)
                        users_wiped += 1
                        count += 1
                        if count >= 500:
                            await batch.commit()
                            batch = db.batch()
                            count = 0
                
                # Кланы
                clans_ref = db.collection('chats').document(str(cid)).collection('clans')
                clan_docs = await clans_ref.get()
                for cdoc in clan_docs:
                    if cdoc.id:
                        batch.set(clans_ref.document(cdoc.id), {
                            'treasury': 0
                        }, merge=True)
                        clans_wiped += 1
                        count += 1
                        if count >= 500:
                            await batch.commit()
                            batch = db.batch()
                            count = 0
                            
                if count > 0:
                    await batch.commit()
            
            await status_msg.edit_text(f"✅ <b>Глобальный сброс экономики завершен!</b>\n👤 Игроков сброшено: <b>{users_wiped}</b>\n🛡 Кланов сброшено: <b>{clans_wiped}</b>\n📈 Биржа сброшена.")
            
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка вайпа: {e}")
        
    await callback.answer(show_alert=True, text="Экономика сброшена!")
    await asyncio.sleep(3.0)
    await cb_global_wipes_menu(callback, state)


# ===================== УПРАВЛЕНИЕ ЗППП ИГРОКА =====================
@router.callback_query(F.data.startswith("db_pdiseases_menu_"))
async def cb_pdiseases_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    from diseases import get_active_diseases, DISEASES
    active = await get_active_diseases(chat_id, target_id)
    active_names = []
    for d in active:
        if d in DISEASES:
            active_names.append(DISEASES[d]['name'])
    
    status_text = ", ".join(active_names) if active_names else "Здоров(а)"
    text = (
        f"🩺 <b>Управление заболеваниями (ЗППП) игрока</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n"
        f"🦠 Активные болезни: <b>{status_text}</b>\n\n"
        f"Выберите действие:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🧼 Вылечить всё", callback_data=f"db_pdis_cure_{chat_id}_{target_id}")
    builder.button(text="🦠 Чесотка", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_scabies")
    builder.button(text="🦠 Сифилис", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_syphilis")
    builder.button(text="🦠 Гепатит", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_hepatitis")
    builder.button(text="🦠 СПИД", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_aids")
    builder.button(text="🦠 Грипп Реальности", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_reality_flu")
    builder.button(text="🤮 Полный букет ЗППП", callback_data=f"db_pdis_inf_{chat_id}_{target_id}_fullhouse")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(2, 2, 2, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_pdis_cure_"))
async def cb_pdis_cure(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    await update_user_field(chat_id, target_id, 'diseases', {})
    await flush_user_cache_immediately(chat_id, target_id)
    
    await callback.answer("✅ Все болезни успешно вылечены!", show_alert=True)
    await cb_pdiseases_menu(callback, state)


@router.callback_query(F.data.startswith("db_pdis_inf_"))
async def cb_pdis_inf(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    disease_id = parts[5]
    
    from diseases import infect_full_house, DISEASES
    
    if disease_id == "fullhouse":
        await infect_full_house(chat_id, target_id)
        await callback.answer("✅ Игрок заражен всеми болезнями!", show_alert=True)
    else:
        # Заражаем конкретной болезнью на 1 час
        data = await get_user_data(chat_id, target_id)
        current_diseases = data.get('diseases')
        if not isinstance(current_diseases, dict):
            current_diseases = {}
        
        current_diseases[disease_id] = time.time() + 3600
        await update_user_field(chat_id, target_id, 'diseases', current_diseases)
        
        d_name = DISEASES.get(disease_id, {}).get('name', disease_id)
        await callback.answer(f"✅ Игрок заражен: {d_name}!", show_alert=True)
        
    await flush_user_cache_immediately(chat_id, target_id)
    await cb_pdiseases_menu(callback, state)


# ===================== УПРАВЛЕНИЕ ИНВЕНТАРЕМ ИГРОКА =====================
@router.callback_query(F.data.startswith("db_pim_"))
async def cb_pinv_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    
    data = await get_user_data(chat_id, target_id)
    inventory = data.get('inventory', {})
    
    from shop import ITEMS
    inv_lines = []
    for k, v in inventory.items():
        item_cfg = ITEMS.get(k, {})
        item_name = item_cfg.get('name', k)
        inv_lines.append(f"• {item_name}: <b>{v} шт.</b>")
        
    inv_text = "\n".join(inv_lines) if inv_lines else "<i>Инвентарь пуст.</i>"
    
    text = (
        f"🎒 <b>Управление инвентарем игрока</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n\n"
        f"<b>Текущие вещи:</b>\n{inv_text}\n\n"
        f"Выберите категорию предметов для выдачи/забора:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏢 Бизнесы", callback_data=f"db_pic_{chat_id}_{target_id}_biz")
    builder.button(text="🚗 Машины", callback_data=f"db_pic_{chat_id}_{target_id}_cars")
    builder.button(text="🎒 Прочее", callback_data=f"db_pic_{chat_id}_{target_id}_other")
    builder.button(text="🧹 Очистить инвентарь", callback_data=f"db_pia_{chat_id}_{target_id}_clear")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(3, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_pic_"))
async def cb_pinv_cat(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    cat = parts[4] # 'biz', 'cars', 'other'
    
    data = await get_user_data(chat_id, target_id)
    inventory = data.get('inventory', {})
    
    from shop import ITEMS
    cat_names = {"biz": "🏢 Бизнесы", "cars": "🚗 Машины", "other": "🎒 Разное"}
    
    text = (
        f"🎒 <b>Категория: {cat_names.get(cat, cat)}</b>\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n\n"
        f"Нажимайте ➖ или ➕ для изменения количества предметов в инвентаре:"
    )
    
    builder = InlineKeyboardBuilder()
    
    for item_id, item_cfg in ITEMS.items():
        if item_cfg.get('cat') != cat:
            continue
            
        qty = inventory.get(item_id, 0)
        item_name = item_cfg.get('name', item_id)
        
        builder.button(text="➖", callback_data=f"db_pich_{chat_id}_{target_id}_{item_id}_m_{cat}")
        builder.button(text=f"{item_name} ({qty})", callback_data=f"db_piq_{chat_id}_{target_id}_{item_id}_{cat}")
        builder.button(text="➕", callback_data=f"db_pich_{chat_id}_{target_id}_{item_id}_p_{cat}")
        
    builder.button(text="⬅️ Назад к категориям", callback_data=f"db_pim_{chat_id}_{target_id}")
    
    grid = []
    for item_id, item_cfg in ITEMS.items():
        if item_cfg.get('cat') == cat:
            grid.extend([1, 1, 1])
            
    builder.adjust(*[3 for _ in range(len(grid) // 3)], 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_pich_"))
async def cb_pinv_change(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    item_id = parts[4]
    action = parts[5] # 'p' or 'm'
    cat = parts[6]
    
    data = await get_user_data(chat_id, target_id)
    inventory = dict(data.get('inventory', {}))
    
    current_qty = inventory.get(item_id, 0)
    
    if action == "p":
        inventory[item_id] = current_qty + 1
        await callback.answer("➕ Количество увеличено!")
    elif action == "m":
        if current_qty <= 0:
            return await callback.answer("❌ Предмета уже 0 в инвентаре!", show_alert=True)
        elif current_qty == 1:
            del inventory[item_id]
        else:
            inventory[item_id] = current_qty - 1
        await callback.answer("➖ Количество уменьшено!")
        
    await update_user_field(chat_id, target_id, 'inventory', inventory)
    asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))
    
    class MockCallback:
        def __init__(self):
            self.message = callback.message
            self.bot = callback.bot
            self.data = f"db_pic_{chat_id}_{target_id}_{cat}"
        async def answer(self):
            pass
            
    await cb_pinv_cat(MockCallback(), state)


@router.callback_query(F.data == "db_noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("db_pia_"))
async def cb_pinv_act(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    action = parts[4]
    
    if action == "clear":
        await update_user_field(chat_id, target_id, 'inventory', {})
        asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))
        await callback.answer("✅ Инвентарь очищен!", show_alert=True)
        await cb_pinv_menu(callback, state)


# Запрос ввода количества предметов
@router.callback_query(F.data.startswith("db_piq_"))
async def cb_player_inv_qty_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    item_id = parts[4]
    cat = parts[5]
    
    data = await get_user_data(chat_id, target_id)
    inventory = data.get('inventory', {})
    current_qty = inventory.get(item_id, 0)
    
    from shop import ITEMS
    item_cfg = ITEMS.get(item_id, {})
    item_name = item_cfg.get('name', item_id)
    
    await state.set_state(AdminPanelState.waiting_for_player_inv_qty)
    await state.update_data(
        chat_id=chat_id,
        target_user_id=target_id,
        item_id=item_id,
        cat=cat,
        menu_message_id=callback.message.message_id
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pic_{chat_id}_{target_id}_{cat}")
    
    await callback.message.edit_text(
        f"🎒 <b>Изменение количества в инвентаре</b>\n\n"
        f"Предмет: <b>{item_name}</b>\n"
        f"Текущее количество: <b>{current_qty} шт.</b>\n\n"
        f"Введите новое целое количество (от 0 до 1000) в ответ на это сообщение:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# Обработчик ввода количества
@router.message(AdminPanelState.waiting_for_player_inv_qty)
async def process_player_inv_qty_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    item_id = state_data["item_id"]
    cat = state_data["cat"]
    
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
        if val < 0 or val > 1000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Количество должно быть целым числом от 0 до 1000. Попробуйте еще раз:")
        return
        
    data = await get_user_data(chat_id, target_id)
    inventory = dict(data.get('inventory', {}))
    
    if val == 0:
        inventory.pop(item_id, None)
    else:
        inventory[item_id] = val
        
    await update_user_field(chat_id, target_id, 'inventory', inventory)
    asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))
    
    await message.answer(f"✅ Количество предметов в инвентаре успешно установлено в {val}.")
    await state.clear()
    
    await cb_pinv_cat(MockCallback(message, state_data["menu_message_id"], f"db_pic_{chat_id}_{target_id}_{cat}"), state)
    try:
        await message.delete()
    except Exception:
        pass


# ===================== ДОПОЛНИТЕЛЬНЫЙ ФУНКЦИОНАЛ ИГРОКА =====================

# Изменение репутации (Запрос)
@router.callback_query(F.data.startswith("db_prep_prompt_"))
async def cb_player_reputation_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    await state.set_state(AdminPanelState.waiting_for_player_reputation)
    await state.update_data(chat_id=chat_id, target_user_id=target_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    
    await callback.message.edit_text(
        "📈 <b>Изменение репутации игрока</b>\n\n"
        "Введите новое целое число репутации (может быть отрицательным) в ответ на это сообщение:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода репутации
@router.message(AdminPanelState.waiting_for_player_reputation)
async def process_player_reputation_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("❌ Репутация должна быть целым числом. Попробуйте еще раз:")
        return
        
    await update_user_field(chat_id, target_id, 'reputation', val)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await message.answer(f"✅ Репутация игрока успешно установлена в {val}.")
    await show_player_details_screen(message, state, chat_id, target_id)
    try:
        await message.delete()
    except Exception:
        pass


# Меню питомцев
@router.callback_query(F.data.startswith("db_ppet_menu_"))
async def cb_player_pet_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    data = await get_user_data(chat_id, target_id)
    pet = data.get('pet')
    
    from pets import PETS_SHOP
    pet_text = "Нет питомца"
    if isinstance(pet, dict):
        p_id = pet.get('id')
        p_name = PETS_SHOP.get(p_id, {}).get('name', p_id)
        last_fed = pet.get('last_fed', 0)
        fed_hours_ago = (time.time() - last_fed) / 3600
        if fed_hours_ago > 48:
            pet_text = f"{p_name} (Сбежал/Голодает)"
        else:
            pet_text = f"{p_name} (Сыт, кормили {int(fed_hours_ago)}ч назад)"
            
    text = (
        f"🐾 <b>Управление питомцем игрока</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n"
        f"🐾 Текущий питомец: <b>{pet_text}</b>\n\n"
        f"Выберите действие:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🐱 Выдать Кота", callback_data=f"db_ppet_act_{chat_id}_{target_id}_set_cat")
    builder.button(text="🐶 Выдать Собаку", callback_data=f"db_ppet_act_{chat_id}_{target_id}_set_dog")
    builder.button(text="🐉 Выдать Дракона", callback_data=f"db_ppet_act_{chat_id}_{target_id}_set_dragon")
    builder.button(text="🍗 Покормить питомца", callback_data=f"db_ppet_act_{chat_id}_{target_id}_feed")
    builder.button(text="🗑 Убрать питомца", callback_data=f"db_ppet_act_{chat_id}_{target_id}_remove")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Действие с питомцем
@router.callback_query(F.data.startswith("db_ppet_act_"))
async def cb_player_pet_act(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    action = parts[5]
    
    data = await get_user_data(chat_id, target_id)
    pet = data.get('pet')
    
    if action == "remove":
        await update_user_field(chat_id, target_id, 'pet', None)
        await callback.answer("🐾 Питомец успешно убран.", show_alert=True)
    elif action == "feed":
        if not isinstance(pet, dict):
            return await callback.answer("❌ У игрока нет питомца для кормления!", show_alert=True)
        pet['last_fed'] = int(time.time())
        await update_user_field(chat_id, target_id, 'pet', pet)
        await callback.answer("🍗 Питомец сыт и доволен!", show_alert=True)
    elif action.startswith("set_"):
        pet_id = action.replace("set_", "")
        pet_data = {
            'id': pet_id,
            'last_fed': int(time.time())
        }
        await update_user_field(chat_id, target_id, 'pet', pet_data)
        from pets import PETS_SHOP
        p_name = PETS_SHOP.get(pet_id, {}).get('name', pet_id)
        await callback.answer(f"✅ Игроку выдан питомец: {p_name}!", show_alert=True)
        
    await flush_user_cache_immediately(chat_id, target_id)
    await cb_player_pet_menu(callback, state)


# Меню навыков
@router.callback_query(F.data.startswith("db_pskills_menu_"))
async def cb_player_skills_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    data = await get_user_data(chat_id, target_id)
    skills = data.get('skills', {})
    
    from skills import SKILLS
    text = f"🎯 <b>Управление навыками игрока</b>\n\n👤 Игрок ID: <code>{target_id}</code>\n\n"
    
    builder = InlineKeyboardBuilder()
    for sk_id, sk_cfg in SKILLS.items():
        lvl = skills.get(sk_id, 0)
        text += f"{sk_cfg['name']}: <b>{lvl}/5</b>\n<i>{sk_cfg['desc']}</i>\n\n"
        
        builder.button(text=f"➖ {sk_cfg['name']}", callback_data=f"db_psc_{chat_id}_{target_id}_{sk_id}_m")
        builder.button(text=f"➕ {sk_cfg['name']}", callback_data=f"db_psc_{chat_id}_{target_id}_{sk_id}_p")
        
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(2, 2, 2, 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Действие с навыками
@router.callback_query(F.data.startswith("db_psc_"))
async def cb_player_skills_change(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[2])
    target_id = int(parts[3])
    sk_id = parts[4]
    action = parts[5] # 'p' or 'm'
    
    data = await get_user_data(chat_id, target_id)
    skills = dict(data.get('skills', {}))
    
    current_lvl = skills.get(sk_id, 0)
    if action == "p":
        if current_lvl >= 5:
            return await callback.answer("❌ Навык уже прокачан до максимума (5)!", show_alert=True)
        skills[sk_id] = current_lvl + 1
        await callback.answer("✅ Уровень навыка повышен!", show_alert=True)
    elif action == "m":
        if current_lvl <= 0:
            return await callback.answer("❌ Уровень навыка уже равен 0!", show_alert=True)
        skills[sk_id] = current_lvl - 1
        await callback.answer("✅ Уровень навыка понижен!", show_alert=True)
        
    await update_user_field(chat_id, target_id, 'skills', skills)
    asyncio.create_task(flush_user_cache_immediately(chat_id, target_id))
    await cb_player_skills_menu(callback, state)


# Меню долгов
@router.callback_query(F.data.startswith("db_pdebts_menu_"))
async def cb_player_debts_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})
    
    text = f"💸 <b>Управление долгами игрока</b>\n\n👤 Игрок ID: <code>{target_id}</code>\n\n"
    
    builder = InlineKeyboardBuilder()
    debt_keys = []
    
    if not debts:
        text += "<i>У игрока нет активных долгов.</i>"
    else:
        index = 0
        for key, val in list(debts.items()):
            debt_keys.append(key)
            if key.startswith("bank_"):
                k_parts = key.split("_")
                banker_id = k_parts[1]
                bank_info = await get_bank_info(chat_id, banker_id)
                bank_name = bank_info.get('name', f"Банк {banker_id}") if bank_info else f"Банк {banker_id}"
                line = f"🏦 {escape_html(bank_name)}: <b>{val:,}</b> сыр."
            else:
                cred_data = await get_user_data(chat_id, key)
                cred_name = cred_data.get('full_name', f"Игрок {key}") if cred_data else f"Игрок {key}"
                line = f"👤 {escape_html(cred_name)}: <b>{val:,}</b> сыр."
                
            text += f"{index + 1}. {line}\n"
            builder.button(text=f"🗑 Списать долг {index + 1}", callback_data=f"db_pdebts_del_{chat_id}_{target_id}_{index}")
            index += 1
            
    await state.update_data(debt_keys=debt_keys)
    
    builder.button(text="➕ Выдать долг", callback_data=f"db_pdebts_add_{chat_id}_{target_id}")
    builder.button(text="🧹 Простить ВСЕ долги", callback_data=f"db_pdebts_clear_{chat_id}_{target_id}")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Удаление конкретного долга по индексу
@router.callback_query(F.data.startswith("db_pdebts_del_"))
async def cb_player_debt_delete(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    index = int(parts[5])
    
    state_data = await state.get_data()
    debt_keys = state_data.get('debt_keys', [])
    
    if index >= len(debt_keys):
        return await callback.answer("❌ Ошибка: долг не найден.", show_alert=True)
        
    key_to_delete = debt_keys[index]
    
    data = await get_user_data(chat_id, target_id)
    debts = dict(data.get('debts', {}))
    
    if key_to_delete in debts:
        del debts[key_to_delete]
        await update_user_field(chat_id, target_id, 'debts', debts)
        await flush_user_cache_immediately(chat_id, target_id)
        await callback.answer("✅ Долг списан!", show_alert=True)
    else:
        await callback.answer("❌ Долг уже был погашен или списан.", show_alert=True)
        
    await cb_player_debts_menu(callback, state)

# Прощение всех долгов
@router.callback_query(F.data.startswith("db_pdebts_clear_"))
async def cb_player_debts_clear(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    await update_user_field(chat_id, target_id, 'debts', {})
    await flush_user_cache_immediately(chat_id, target_id)
    await callback.answer("🧹 Все долги игрока прощены!", show_alert=True)
    await cb_player_debts_menu(callback, state)

# Запрос добавления долга (выбор кредитора)
@router.callback_query(F.data.startswith("db_pdebts_add_"))
async def cb_player_debt_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    db = get_db()
    banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
    banks_docs = await banks_ref.get()
    
    text = (
        f"➕ <b>Добавление долга игроку</b>\n\n"
        f"Выберите банк в качестве кредитора или введите ID игрока-кредитора в ответ на это сообщение:"
    )
    
    builder = InlineKeyboardBuilder()
    
    for doc in banks_docs:
        b_data = doc.to_dict()
        b_name = b_data.get('name', 'Банк')
        b_id = doc.id
        builder.button(text=f"🏦 {b_name}", callback_data=f"db_pdebts_cbank_{chat_id}_{target_id}_{b_id}")
        
    builder.button(text="❌ Отмена", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
    builder.adjust(1)
    
    await state.set_state(AdminPanelState.waiting_for_debt_creditor)
    await state.update_data(chat_id=chat_id, target_user_id=target_id, menu_message_id=callback.message.message_id)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Обработчик ввода ID игрока-кредитора
@router.message(AdminPanelState.waiting_for_debt_creditor)
async def process_debt_creditor_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    
    creditor_input = message.text.strip()
    
    try:
        cred_id, cred_data = await get_user_by_username_or_id(chat_id, creditor_input)
        if not cred_id:
            await message.answer("❌ Кредитор не найден в базе этого чата. Попробуйте еще раз:")
            return
            
        await state.set_state(AdminPanelState.waiting_for_debt_amount)
        await state.update_data(creditor_key=str(cred_id), creditor_name=cred_data.get('full_name', 'Игрок'))
        
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
        
        await message.answer(
            f"💰 <b>Выдача долга игроку</b>\n"
            f"Кредитор: <b>{escape_html(cred_data.get('full_name'))}</b>\n\n"
            f"Введите сумму долга (сыроежек):",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Введите ID кредитора повторно:")
        return
        
    try:
        await message.delete()
    except Exception:
        pass

# Выбор банка-кредитора через callback
@router.callback_query(F.data.startswith("db_pdebts_cbank_"))
async def cb_player_debt_select_bank(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    banker_id = parts[5]
    
    bank_info = await get_bank_info(chat_id, banker_id)
    if not bank_info:
        return await callback.answer("Банк не найден.", show_alert=True)
        
    debt_key = f"bank_{banker_id}_0_0_0"
    
    await state.set_state(AdminPanelState.waiting_for_debt_amount)
    await state.update_data(creditor_key=debt_key, creditor_name=bank_info.get('name', 'Банк'))
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_pdebts_menu_{chat_id}_{target_id}")
    
    await callback.message.edit_text(
        f"💰 <b>Выдача долга игроку</b>\n"
        f"Кредитор (Банк): <b>{escape_html(bank_info.get('name'))}</b>\n\n"
        f"Введите сумму долга (сыроежек):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода суммы долга
@router.message(AdminPanelState.waiting_for_debt_amount)
async def process_debt_amount_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    target_id = state_data["target_user_id"]
    creditor_key = state_data["creditor_key"]
    creditor_name = state_data["creditor_name"]
    
    try:
        amount = int(message.text.replace(" ", "").replace(",", ""))
        if amount <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Сумма должна быть целым числом больше нуля. Введите сумму повторно:")
        return
        
    data = await get_user_data(chat_id, target_id)
    debts = dict(data.get('debts', {}))
    
    debts[creditor_key] = debts.get(creditor_key, 0) + amount
    
    await update_user_field(chat_id, target_id, 'debts', debts)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await message.answer(f"✅ Игроку добавлен долг кредитору <b>{escape_html(creditor_name)}</b> на сумму {amount:,} сыр.")
    
    await state.clear()
    await show_player_details_screen(message, state, chat_id, target_id)
    
    try:
        await message.delete()
    except Exception:
        pass


# Запрос подтверждения казни
@router.callback_query(F.data.startswith("db_pexecute_ask_"))
async def cb_player_execute_ask(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    text = (
        f"⚔️ <b>ВЫСШАЯ МЕРА НАКАЗАНИЯ (Казнь)</b>\n\n"
        f"Вы собираетесь казнить игрока ID <code>{target_id}</code>.\n"
        f"Сообщение о казни будет отправлено в управляемый чат.\n"
        f"Выберите тип приговора:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💀 Только казнь (Визуальная)", callback_data=f"db_pexecute_do_{chat_id}_{target_id}_visual")
    builder.button(text="🔨 Казнить + Забанить в боте", callback_data=f"db_pexecute_do_{chat_id}_{target_id}_botban")
    builder.button(text="🚨 Казнить + Забанить везде", callback_data=f"db_pexecute_do_{chat_id}_{target_id}_fullban")
    builder.button(text="❌ Отмена", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

# Выполнение казни
@router.callback_query(F.data.startswith("db_pexecute_do_"))
async def cb_player_execute_do(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    mode = parts[5]
    
    data = await get_user_data(chat_id, target_id)
    target_name = escape_html(data.get('full_name', 'Грешник'))
    
    from aiogram.types import FSInputFile
    import os
    
    image_path = "assets/execution.png"
    caption = (
        f"⚖️ <b>ВЫСШАЯ МЕРА НАКАЗАНИЯ!</b>\n\n"
        f"Пользователь <b>{target_name}</b> (<code>{target_id}</code>) был признан виновным в предательстве и приговорен к <b>казни</b>!\n\n"
        f"⚔️ <i>Приговор приведен в исполнение немедленно по воле Создателя.</i>\n"
        f"💀 Да смилуются боги над его душой!"
    )
    
    try:
        if os.path.exists(image_path):
            photo = FSInputFile(image_path)
            await callback.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
        else:
            await callback.bot.send_photo(
                chat_id=chat_id,
                photo="https://i.imgur.com/8Qp4S3q.png",
                caption=caption
            )
    except Exception as e:
        print(f"Error sending execution photo: {e}")
        try:
            await callback.bot.send_message(chat_id=chat_id, text=caption)
        except Exception:
            pass
            
    if mode in ['botban', 'fullban']:
        await update_user_field(chat_id, target_id, 'is_banned', True)
        await flush_user_cache_immediately(chat_id, target_id)
        
    if mode == 'fullban':
        try:
            await callback.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        except Exception:
            pass
            
    act_text = "Казнь успешно приведена в исполнение!"
    if mode == 'botban':
        act_text += " Пользователь забанен в боте."
    elif mode == 'fullban':
        act_text += " Пользователь забанен в боте и в чате."
        
    await callback.answer(act_text, show_alert=True)
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


# Сброс FSM / игры
@router.callback_query(F.data.startswith("db_pfsm_reset_"))
async def cb_player_fsm_reset(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    try:
        from aiogram.fsm.storage.base import StorageKey
        state_to_clear = FSMContext(
            storage=callback.bot.dispatcher.storage,
            key=StorageKey(bot_id=callback.bot.id, chat_id=chat_id, user_id=target_id)
        )
        await state_to_clear.clear()
        await callback.answer("🔄 Все FSM состояния игрока (включая игры) сброшены!", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка сброса: {e}", show_alert=True)
        
    await show_player_details_screen(callback, state, chat_id, target_id, edit=True)


# ===================== ГЛОБАЛЬНЫЕ ДЕЙСТВИЯ АДМИНИСТРАТОРА =====================

# Переключение режима тех. работ
@router.callback_query(F.data.startswith("db_gtm_"))
async def cb_toggle_maintenance(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    chat_id = int(callback.data.split("_")[2])
    
    from utils import check_maintenance
    current = await check_maintenance()
    new_val = not current
    
    db = get_db()
    await db.collection('bot_settings').document('maintenance').set({"active": new_val})
    
    from utils_pkg.cache_manager import global_cache
    global_cache.set("maintenance_mode", new_val, ttl=60)
    
    await callback.answer(f"Режим тех. работ установлен: {new_val}", show_alert=True)
    await cb_global_settings_view(callback, state)


# Запрос на рассылку
@router.callback_query(F.data.startswith("db_gbroadcast_prompt_"))
async def cb_global_broadcast_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer("❌ У вас нет доступа.", show_alert=True)
    chat_id = int(callback.data.split("_")[3])
    
    await state.set_state(AdminPanelState.waiting_for_global_broadcast)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_glob_{chat_id}")
    
    await callback.message.edit_text(
        "📡 <b>Создание глобальной рассылки</b>\n\n"
        "Введите текст сообщения, которое будет разослано во все разрешенные группы бота (белый список):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Обработчик ввода рассылки
@router.message(AdminPanelState.waiting_for_global_broadcast)
async def process_global_broadcast_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    
    whitelist = await get_whitelist()
    
    status_msg = await message.answer(
        f"📡 <b>Рассылка запущена в фоновом режиме!</b>\n"
        f"Ожидаемое количество чатов: {len(whitelist)}\n\n"
        f"Бот оповестит вас о завершении."
    )
    
    async def run_broadcast_task():
        success, fail = 0, 0
        for cid in whitelist.keys():
            try:
                await message.send_copy(chat_id=cid)
                success += 1
                await asyncio.sleep(0.15)
            except Exception:
                fail += 1
        
        try:
            await message.bot.send_message(
                chat_id=message.from_user.id,
                text=f"✅ <b>Фоновая рассылка завершена!</b>\n\n"
                     f"Успешно отправлено: <b>{success}</b> чатов\n"
                     f"Не удалось отправить: <b>{fail}</b> чатов."
            )
        except Exception:
            pass

    from utils import fire_and_forget
    fire_and_forget(run_broadcast_task())
    
    await state.clear()
    
    await cb_global_settings_view(MockCallback(message, state_data.get("menu_message_id"), f"db_glob_{chat_id}"), state)
    try:
        await message.delete()
    except Exception:
        pass
    try:
        await status_msg.delete()
    except Exception:
        pass


# ===================== МУТ / РАЗМУТ ИГРОКА =====================
@router.callback_query(F.data.startswith("db_pmute_menu_"))
async def cb_pmute_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    
    text = (
        f"🔇 <b>Управление ограничениями отправки сообщений (Мут)</b>\n\n"
        f"👤 Игрок ID: <code>{target_id}</code>\n"
        f"🏢 Чат: <code>{chat_id}</code>\n\n"
        f"Выберите длительность мута:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ 15 минут", callback_data=f"db_pmute_act_{chat_id}_{target_id}_15")
    builder.button(text="⏳ 1 час", callback_data=f"db_pmute_act_{chat_id}_{target_id}_60")
    builder.button(text="⏳ 1 день", callback_data=f"db_pmute_act_{chat_id}_{target_id}_1440")
    builder.button(text="⏳ 7 дней", callback_data=f"db_pmute_act_{chat_id}_{target_id}_10080")
    builder.button(text="🔊 Снять мут (Разглушить)", callback_data=f"db_pmute_act_{chat_id}_{target_id}_unmute")
    builder.button(text="⬅️ Назад к профилю", callback_data=f"db_pv_{chat_id}_{target_id}")
    builder.adjust(2, 2, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_pmute_act_"))
async def cb_pmute_act(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    target_id = int(parts[4])
    duration = parts[5]
    
    bot = callback.bot
    
    try:
        if duration == "unmute":
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=types.ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await callback.answer("🔊 Мут успешно снят!", show_alert=True)
        else:
            minutes = int(duration)
            until_date = int(time.time()) + (minutes * 60)
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            await callback.answer(f"🔇 Игрок замучен на {minutes} минут!", show_alert=True)
            
            # Логируем
            from log_system import log_action
            log_action(f"🔇 <b>Мут (Панель):</b> {callback.from_user.full_name} замутил {target_id} на {minutes} мин. в чате {chat_id}")
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        
    await cb_pmute_menu(callback, state)


# ===================== РАЗДЕЛ: УПРАВЛЕНИЕ КЛАНАМИ =====================
# ===================== РАЗДЕЛ: УПРАВЛЕНИЕ КЛАНАМИ =====================

import hashlib

def get_clan_hash(clan_name: str) -> str:
    return hashlib.md5(clan_name.encode('utf-8')).hexdigest()[:16]

async def get_clan_name_by_hash(chat_id: int, clan_hash: str) -> Optional[str]:
    db = get_db()
    clans_ref = db.collection('chats').document(str(chat_id)).collection('clans')
    clans_docs = await clans_ref.get()
    for doc in clans_docs:
        c_name = doc.id
        if get_clan_hash(c_name) == clan_hash:
            return c_name
    return None

async def parse_clan_callback(callback_data: str) -> tuple:
    """
    Parses both old (long/raw names) and new (short/hashed) callback formats.
    Returns (chat_id, clan_name, member_id_or_none)
    """
    parts = callback_data.split("_")
    if len(parts) < 4:
        return None, None, None
        
    data_str = callback_data
    try:
        # 1. db_clan_view_
        if data_str.startswith("db_clan_view_"):
            chat_id = int(parts[3])
            clan_hash = parts[4]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[4:])
            return chat_id, clan_name, None
            
        # 2. db_clan_treasury_
        elif data_str.startswith("db_clan_treasury_"):
            chat_id = int(parts[3])
            clan_hash = parts[4]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[4:])
            return chat_id, clan_name, None
            
        # 3. db_clan_leader_
        elif data_str.startswith("db_clan_leader_"):
            chat_id = int(parts[3])
            clan_hash = parts[4]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[4:])
            return chat_id, clan_name, None
            
        # 4. db_clan_dask_ / db_clan_del_ask_
        elif data_str.startswith("db_clan_dask_"):
            chat_id = int(parts[3])
            clan_hash = parts[4]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[4:])
            return chat_id, clan_name, None
        elif data_str.startswith("db_clan_del_ask_"):
            chat_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, None
            
        # 5. db_clan_dconf_ / db_clan_del_confirm_
        elif data_str.startswith("db_clan_dconf_"):
            chat_id = int(parts[3])
            clan_hash = parts[4]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[4:])
            return chat_id, clan_name, None
        elif data_str.startswith("db_clan_del_confirm_"):
            chat_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, None
            
        # 6. db_clan_mlist_ / db_clan_members_list_
        elif data_str.startswith("db_clan_mlist_"):
            chat_id = int(parts[3])
            clan_hash = parts[4]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[4:])
            return chat_id, clan_name, None
        elif data_str.startswith("db_clan_members_list_"):
            chat_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, None
            
        # 7. db_clan_mem_ / db_clan_member_
        elif data_str.startswith("db_clan_mem_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_hash = parts[5]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
        elif data_str.startswith("db_clan_member_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
            
        # 8. db_clan_prom_ / db_clan_promote_
        elif data_str.startswith("db_clan_prom_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_hash = parts[5]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
        elif data_str.startswith("db_clan_promote_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
            
        # 9. db_clan_dem_ / db_clan_demote_
        elif data_str.startswith("db_clan_dem_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_hash = parts[5]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
        elif data_str.startswith("db_clan_demote_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
            
        # 10. db_clan_kck_ / db_clan_kick_
        elif data_str.startswith("db_clan_kck_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_hash = parts[5]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
        elif data_str.startswith("db_clan_kick_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
            
        # 11. db_clan_ltr_ / db_clan_leadtransfer_
        elif data_str.startswith("db_clan_ltr_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_hash = parts[5]
            clan_name = await get_clan_name_by_hash(chat_id, clan_hash)
            if not clan_name:
                clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
        elif data_str.startswith("db_clan_leadtransfer_"):
            chat_id = int(parts[3])
            member_id = int(parts[4])
            clan_name = "_".join(parts[5:])
            return chat_id, clan_name, member_id
            
    except (ValueError, IndexError):
        pass
        
    return None, None, None

@router.callback_query(F.data.startswith("db_clans_list_"))
async def cb_clans_list(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    await state.clear()
    chat_id = int(callback.data.split("_")[3])
    
    db = get_db()
    clans_ref = db.collection('chats').document(str(chat_id)).collection('clans')
    clans_docs = await clans_ref.get()
    
    text = "🛡 <b>Управление кланами чата</b>\n\nВыберите клан для настройки:"
    builder = InlineKeyboardBuilder()
    
    has_clans = False
    for doc in clans_docs:
        c_name = doc.id
        c_data = doc.to_dict()
        treasury = c_data.get('treasury', 0)
        c_hash = get_clan_hash(c_name)
        builder.button(text=f"🛡 {c_name} ({treasury:,} сыр)", callback_data=f"db_clan_view_{chat_id}_{c_hash}")
        has_clans = True
        
    if not has_clans:
        text += "\n\n<i>В этой группе еще не создано ни одного клана.</i>"
        
    builder.button(text="⬅️ Назад к меню", callback_data=f"db_m_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


async def show_clan_detail_screen(callback_or_message, state: FSMContext, chat_id: int, clan_name: str):
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        text = "❌ Клан не найден или был распущен."
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data=f"db_clans_list_{chat_id}")
        
        if isinstance(callback_or_message, types.CallbackQuery) or hasattr(callback_or_message, 'message'):
            await callback_or_message.message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await callback_or_message.answer(text, reply_markup=builder.as_markup())
        return

    c_data = doc.to_dict()
    leader_id = c_data.get('leader_id')
    deputies = c_data.get('deputy_ids', [])
    members = c_data.get('members', [])
    treasury = c_data.get('treasury', 0)
    
    # Пытаемся получить имя лидера
    leader_name = "Неизвестный"
    try:
        l_data = await get_user_data(chat_id, leader_id)
        leader_name = l_data.get('full_name', f"ID: {leader_id}")
    except Exception:
        pass

    member_names = []
    for m_id in members:
        try:
            m_data = await get_user_data(chat_id, m_id)
            m_name = m_data.get('full_name', f"ID: {m_id}")
        except Exception:
            m_name = f"ID: {m_id}"
        role = ""
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
        f"💰 Казна клана: <b>{treasury:,}</b> сыр.\n\n"
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
    
    if isinstance(callback_or_message, types.CallbackQuery) or hasattr(callback_or_message, 'message'):
        await callback_or_message.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        bot = callback_or_message.bot if hasattr(callback_or_message, 'bot') else callback_or_message.message.bot
        state_data = await state.get_data()
        msg_id = state_data.get("menu_message_id")
        if msg_id:
            try:
                await bot.edit_message_text(chat_id=callback_or_message.chat.id, message_id=msg_id, text=text, reply_markup=builder.as_markup())
                return
            except Exception:
                pass
        msg = await callback_or_message.answer(text, reply_markup=builder.as_markup())
        await state.update_data(menu_message_id=msg.message_id)


@router.callback_query(F.data.startswith("db_clan_view_"))
async def cb_clan_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    await state.clear()
    
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    await show_clan_detail_screen(callback, state, chat_id, clan_name)
    await callback.answer()


@router.callback_query(F.data.startswith("db_clan_treasury_"))
async def cb_clan_treasury_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    await state.set_state(AdminPanelState.waiting_for_clan_treasury)
    await state.update_data(chat_id=chat_id, clan_name=clan_name, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    clan_hash = get_clan_hash(clan_name)
    builder.button(text="❌ Отмена", callback_data=f"db_clan_view_{chat_id}_{clan_hash}")
    
    await callback.message.edit_text(
        f"💰 <b>Изменение казны клана: {escape_html(clan_name)}</b>\n\n"
        f"Введите новую сумму казны (целое число сыроежек):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.message(AdminPanelState.waiting_for_clan_treasury)
async def process_clan_treasury_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    clan_name = state_data["clan_name"]
    menu_message_id = state_data.get("menu_message_id")
    
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
        if val < 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Сумма должна быть положительным целым числом. Введите корректно:")
        return
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    await clan_ref.update({'treasury': val})
    
    await message.answer(f"✅ Казна клана <b>{escape_html(clan_name)}</b> успешно изменена на {val:,} сыроежек.")
    
    await state.clear()
    
    c_hash = get_clan_hash(clan_name)
    mock_cb = MockCallback(message, menu_message_id, f"db_clan_view_{chat_id}_{c_hash}")
    await show_clan_detail_screen(mock_cb, state, chat_id, clan_name)
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("db_clan_leader_"))
async def cb_clan_leader_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    await state.set_state(AdminPanelState.waiting_for_clan_leader)
    await state.update_data(chat_id=chat_id, clan_name=clan_name, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    clan_hash = get_clan_hash(clan_name)
    builder.button(text="❌ Отмена", callback_data=f"db_clan_view_{chat_id}_{clan_hash}")
    
    await callback.message.edit_text(
        f"👑 <b>Смена лидера клана: {escape_html(clan_name)}</b>\n\n"
        f"Введите @username или числовой ID нового Лидера:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.message(AdminPanelState.waiting_for_clan_leader)
async def process_clan_leader_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    clan_name = state_data["clan_name"]
    menu_message_id = state_data.get("menu_message_id")
    
    identifier = message.text.strip()
    
    target_id, target_data = await get_user_by_username_or_id(chat_id, identifier)
    if not target_id:
        await message.answer("❌ Пользователь не найден в кэше/базе этого чата. Попробуйте еще раз:")
        return
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    clan_data = doc.to_dict()
    
    members = list(clan_data.get('members', []))
    if target_id not in members:
        members.append(target_id)
        
    deputy_ids = list(clan_data.get('deputy_ids', []))
    if target_id in deputy_ids:
        deputy_ids.remove(target_id)
        
    # Обновляем клан в Firestore
    await clan_ref.update({
        'leader_id': target_id,
        'members': members,
        'deputy_ids': deputy_ids
    })
    
    # Назначаем поле clan юзеру
    await update_user_field(chat_id, target_id, 'clan', clan_name)
    await flush_user_cache_immediately(chat_id, target_id)
    
    await message.answer(f"✅ Лидером клана <b>{escape_html(clan_name)}</b> назначен {target_data.get('full_name', 'Игрок')} ({target_id}).")
    
    await state.clear()
    
    c_hash = get_clan_hash(clan_name)
    mock_cb = MockCallback(message, menu_message_id, f"db_clan_view_{chat_id}_{c_hash}")
    await show_clan_detail_screen(mock_cb, state, chat_id, clan_name)
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("db_clan_dask_") | F.data.startswith("db_clan_del_ask_"))
async def cb_clan_del_ask_screen(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    text = (
        f"🚨 <b>ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ!</b> 🚨\n\n"
        f"Вы собираетесь распустить клан <b>{escape_html(clan_name)}</b>.\n"
        f"Это действие безвозвратно удалит клан и очистит принадлежность к клану у всех его участников.\n\n"
        f"Вы абсолютно уверены?"
    )
    
    builder = InlineKeyboardBuilder()
    clan_hash = get_clan_hash(clan_name)
    builder.button(text="💥 Да, распустить клан", callback_data=f"db_clan_dconf_{chat_id}_{clan_hash}")
    builder.button(text="❌ Отмена", callback_data=f"db_clan_view_{chat_id}_{clan_hash}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_clan_dconf_") | F.data.startswith("db_clan_del_confirm_"))
async def cb_perform_clan_delete(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    
    if doc.exists:
        clan_data = doc.to_dict()
        for m_id in clan_data.get('members', []):
            await update_user_field(chat_id, m_id, 'clan', None)
            await flush_user_cache_immediately(chat_id, m_id)
            
        await clan_ref.delete()
        await callback.answer(f"Клан {clan_name} успешно распущен!", show_alert=True)
    else:
        await callback.answer("Клан не найден.")
        
    await cb_clans_list(callback, state)


# ===================== РАЗДЕЛ: УПРАВЛЕНИЕ СОСТАВОМ КЛАНА =====================

@router.callback_query(F.data.startswith("db_clan_mlist_") | F.data.startswith("db_clan_members_list_"))
async def cb_clan_members_list(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    await state.clear()
    
    chat_id, clan_name, _ = await parse_clan_callback(callback.data)
    if not clan_name:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.answer("Клан не найден.", show_alert=True)
        
    clan_data = doc.to_dict()
    members = clan_data.get('members', [])
    leader_id = clan_data.get('leader_id')
    deputy_ids = clan_data.get('deputy_ids', [])
    
    text = f"👥 <b>Состав клана {escape_html(clan_name)}</b>\n\nВыберите участника для управления:"
    builder = InlineKeyboardBuilder()
    
    clan_hash = get_clan_hash(clan_name)
    for m_id in members:
        try:
            m_data = await get_user_data(chat_id, m_id)
            m_name = m_data.get('full_name', f"ID: {m_id}")
        except Exception:
            m_name = f"ID: {m_id}"
            
        role = ""
        if m_id == leader_id:
            role = "👑"
        elif m_id in deputy_ids:
            role = "⭐"
        else:
            role = "👤"
            
        builder.button(text=f"{role} {m_name}", callback_data=f"db_clan_mem_{chat_id}_{m_id}_{clan_hash}")
        
    builder.button(text="⬅️ Назад к деталям клана", callback_data=f"db_clan_view_{chat_id}_{clan_hash}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_clan_mem_") | F.data.startswith("db_clan_member_"))
async def cb_clan_member_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    await state.clear()
    
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await callback.answer("❌ Клан не найден.", show_alert=True)
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.answer("Клан не найден.", show_alert=True)
        
    clan_data = doc.to_dict()
    leader_id = clan_data.get('leader_id')
    deputies = clan_data.get('deputy_ids', [])
    
    try:
        m_data = await get_user_data(chat_id, member_id)
        m_name = m_data.get('full_name', f"ID: {member_id}")
    except Exception:
        m_name = f"ID: {member_id}"
        
    if member_id == leader_id:
        role_desc = "👑 Лидер (Нельзя исключить / сменить роль)"
    elif member_id in deputies:
        role_desc = "⭐ Заместитель"
    else:
        role_desc = "👤 Участник"
        
    text = (
        f"👤 <b>Управление участником клана</b>\n\n"
        f"Клан: <b>{escape_html(clan_name)}</b>\n"
        f"Игрок: <b>{escape_html(m_name)}</b> (ID: <code>{member_id}</code>)\n"
        f"Текущая роль: <b>{role_desc}</b>"
    )
    
    builder = InlineKeyboardBuilder()
    clan_hash = get_clan_hash(clan_name)
    
    if member_id != leader_id:
        if member_id in deputies:
            builder.button(text="👤 Сделать Участником", callback_data=f"db_clan_dem_{chat_id}_{member_id}_{clan_hash}")
        else:
            builder.button(text="⭐ Сделать Заместителем", callback_data=f"db_clan_prom_{chat_id}_{member_id}_{clan_hash}")
            
        builder.button(text="👑 Сделать Лидером", callback_data=f"db_clan_ltr_{chat_id}_{member_id}_{clan_hash}")
        builder.button(text="👞 Исключить из клана", callback_data=f"db_clan_kck_{chat_id}_{member_id}_{clan_hash}")
        
    builder.button(text="⬅️ К списку участников", callback_data=f"db_clan_mlist_{chat_id}_{clan_hash}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_clan_prom_") | F.data.startswith("db_clan_promote_"))
async def cb_clan_promote(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await callback.answer("❌ Клан не найден.")
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.answer("Клан не найден.")
        
    clan_data = doc.to_dict()
    deputies = list(clan_data.get('deputy_ids', []))
    if member_id not in deputies:
        deputies.append(member_id)
        await clan_ref.update({'deputy_ids': deputies})
        await callback.answer("Участник назначен Заместителем!", show_alert=True)
        
    clan_hash = get_clan_hash(clan_name)
    callback.data = f"db_clan_mem_{chat_id}_{member_id}_{clan_hash}"
    await cb_clan_member_view(callback, state)


@router.callback_query(F.data.startswith("db_clan_dem_") | F.data.startswith("db_clan_demote_"))
async def cb_clan_demote(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await callback.answer("❌ Клан не найден.")
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.answer("Клан не найден.")
        
    clan_data = doc.to_dict()
    deputies = list(clan_data.get('deputy_ids', []))
    if member_id in deputies:
        deputies.remove(member_id)
        await clan_ref.update({'deputy_ids': deputies})
        await callback.answer("Заместитель разжалован до участника!", show_alert=True)
        
    clan_hash = get_clan_hash(clan_name)
    callback.data = f"db_clan_mem_{chat_id}_{member_id}_{clan_hash}"
    await cb_clan_member_view(callback, state)


@router.callback_query(F.data.startswith("db_clan_kck_") | F.data.startswith("db_clan_kick_"))
async def cb_clan_kick(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await callback.answer("❌ Клан не найден.")
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.answer("Клан не найден.")
        
    clan_data = doc.to_dict()
    members = list(clan_data.get('members', []))
    deputies = list(clan_data.get('deputy_ids', []))
    
    if member_id in members:
        members.remove(member_id)
    if member_id in deputies:
        deputies.remove(member_id)
        
    await clan_ref.update({
        'members': members,
        'deputy_ids': deputies
    })
    
    await update_user_field(chat_id, member_id, 'clan', None)
    await flush_user_cache_immediately(chat_id, member_id)
    
    await callback.answer("Игрок успешно исключен из клана!", show_alert=True)
    
    clan_hash = get_clan_hash(clan_name)
    callback.data = f"db_clan_mlist_{chat_id}_{clan_hash}"
    await cb_clan_members_list(callback, state)


@router.callback_query(F.data.startswith("db_clan_ltr_") | F.data.startswith("db_clan_leadtransfer_"))
async def cb_clan_leadtransfer(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    
    chat_id, clan_name, member_id = await parse_clan_callback(callback.data)
    if not clan_name or not member_id:
        return await callback.answer("❌ Клан не найден.")
        
    db = get_db()
    clan_ref = db.collection('chats').document(str(chat_id)).collection('clans').document(clan_name)
    doc = await clan_ref.get()
    if not doc.exists:
        return await callback.answer("Клан не найден.")
        
    clan_data = doc.to_dict()
    deputies = list(clan_data.get('deputy_ids', []))
    
    if member_id in deputies:
        deputies.remove(member_id)
        
    await clan_ref.update({
        'leader_id': member_id,
        'deputy_ids': deputies
    })
    
    await update_user_field(chat_id, member_id, 'clan', clan_name)
    await flush_user_cache_immediately(chat_id, member_id)
    
    await callback.answer("Лидерство успешно передано!", show_alert=True)
    
    clan_hash = get_clan_hash(clan_name)
    callback.data = f"db_clan_mem_{chat_id}_{member_id}_{clan_hash}"
    await cb_clan_member_view(callback, state)


# ===================== РАЗДЕЛ: УПРАВЛЕНИЕ ПРОМОКОДАМИ =====================
@router.callback_query(F.data.startswith("db_promos_list_"))
async def cb_promos_list(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[3])
    
    db = get_db()
    promos_ref = db.collection('bot_settings').document('promocodes').collection('active')
    promos_docs = await promos_ref.get()
    
    text = "🏷 <b>Управление промокодами (Глобально)</b>\n\nАктивные промокоды:"
    builder = InlineKeyboardBuilder()
    
    has_promos = False
    for doc in promos_docs:
        code = doc.id
        p_data = doc.to_dict()
        reward = p_data.get('reward', 0)
        used_by = p_data.get('used_by', [])
        max_act = p_data.get('max_activations', 0)
        
        builder.button(text=f"❌ {code} ({reward} сыр, {len(used_by)}/{max_act} исп.)", callback_data=f"db_promo_del_{chat_id}_{code}")
        has_promos = True
        
    if not has_promos:
        text += "\n\n<i>Активных промокодов нет.</i>"
        
    builder.button(text="➕ Создать промокод", callback_data=f"db_promo_create_{chat_id}")
    builder.button(text="⬅️ Назад к глобальным", callback_data=f"db_glob_{chat_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("db_promo_del_"))
async def cb_promo_del(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    parts = callback.data.split("_")
    chat_id = int(parts[3])
    code = "_".join(parts[4:])
    
    db = get_db()
    await db.collection('bot_settings').document('promocodes').collection('active').document(code).delete()
    await callback.answer(f"Промокод {code} успешно удален!", show_alert=True)
    await cb_promos_list(callback, state)


@router.callback_query(F.data.startswith("db_promo_create_"))
async def cb_promo_create_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[3])
    
    await state.set_state(AdminPanelState.waiting_for_promo_code)
    await state.update_data(chat_id=chat_id, menu_message_id=callback.message.message_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_promos_list_{chat_id}")
    
    await callback.message.edit_text(
        "🏷 <b>Создание нового промокода</b>\n\n"
        "Шаг 1: Введите текст (код) промокода:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.message(AdminPanelState.waiting_for_promo_code)
async def process_promo_code_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    code = message.text.strip().upper()
    
    db = get_db()
    doc = await db.collection('bot_settings').document('promocodes').collection('active').document(code).get()
    if doc.exists:
        await message.answer("❌ Такой промокод уже существует. Введите другое имя:")
        return
        
    await state.set_state(AdminPanelState.waiting_for_promo_reward)
    await state.update_data(promo_code=code)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_promos_list_{chat_id}")
    
    await message.answer(
        f"🏷 <b>Промокод {code}</b>\n\n"
        f"Шаг 2: Введите сумму награды в сыроежках (целое число):",
        reply_markup=builder.as_markup()
    )
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AdminPanelState.waiting_for_promo_reward)
async def process_promo_reward_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    code = state_data["promo_code"]
    
    try:
        reward = int(message.text.replace(" ", "").replace(",", ""))
        if reward <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Награда должна быть целым числом больше нуля. Попробуйте еще раз:")
        return
        
    await state.set_state(AdminPanelState.waiting_for_promo_max_uses)
    await state.update_data(promo_reward=reward)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"db_promos_list_{chat_id}")
    
    await message.answer(
        f"🏷 <b>Промокод {code} (Награда: {reward} сыр)</b>\n\n"
        f"Шаг 3: Введите максимальное количество использований (целое число):",
        reply_markup=builder.as_markup()
    )
    try:
        await message.delete()
    except Exception:
        pass


@router.message(AdminPanelState.waiting_for_promo_max_uses)
async def process_promo_max_uses_input(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    code = state_data["promo_code"]
    reward = state_data["promo_reward"]
    
    try:
        max_uses = int(message.text.replace(" ", "").replace(",", ""))
        if max_uses <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Количество активаций должно быть целым числом больше нуля. Попробуйте еще раз:")
        return
        
    db = get_db()
    ref = db.collection('bot_settings').document('promocodes').collection('active').document(code)
    await ref.set({
        'reward': reward,
        'max_activations': max_uses,
        'used_by': []
    })
    
    await message.answer(f"✅ Промокод <b>{code}</b> успешно создан!\nНаграда: {reward} сыроежек\nЛимит активаций: {max_uses}")
    
    await state.clear()
    
    await cb_promos_list(MockCallback(message, state_data.get("menu_message_id"), f"db_promos_list_{chat_id}"), state)
    try:
        await message.delete()
    except Exception:
        pass
