import time
import random
import traceback
import asyncio
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
        f"👑 VIP: <b>{vip_status}</b>\n"
        f"💼 Банкир: <b>{banker_status}</b>\n"
        f"🚫 Статус: <b>{ban_status}</b>\n"
        f"👁 В топе: <b>{hidden_status}</b>\n"
        f"⚠️ Варны: <b>{warns_count}/3</b>\n"
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
    builder.button(text="🧹 Вайпнуть данные", callback_data=f"db_pwi_{chat_id}_{target_id}")
    builder.button(text="⬅️ Назад", callback_data=f"db_m_{chat_id}")
    builder.adjust(2, 2, 2, 2, 1, 1)
    
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
    builder.button(text="❌ Отмена", callback_data=f"db_g_{chat_id}")
    
    await callback.message.edit_text(
        "📣 <b>Отправка сообщения в группу от имени бота</b>\n\n"
        "Введите текст сообщения, которое бот должен немедленно отправить в группу:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AdminPanelState.waiting_for_say_text)
async def process_group_say_text(message: types.Message, state: FSMContext):
    if not is_creator(message): return
    state_data = await state.get_data()
    chat_id = state_data["chat_id"]
    
    text_to_say = message.text
    try:
        await message.bot.send_message(chat_id=chat_id, text=text_to_say)
        await message.answer("✅ Сообщение успешно отправлено в группу.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")
        
    await state.clear()
    await cb_group_settings_view(message, state) # В качестве callback_query передаем message (функция проверит тип)
    try:
        await message.delete()
    except Exception:
        pass

# ===================== РАЗДЕЛ: ГЛОБАЛЬНЫЕ НАСТРОЙКИ =====================

@router.callback_query(F.data.startswith("db_glob_"))
async def cb_global_settings_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_creator(callback): return await callback.answer()
    chat_id = int(callback.data.split("_")[2]) # Может быть 0, если из ЛС
    
    tax = await get_global_tax()
    
    chance_slots = await get_game_chance('slots')
    chance_cups = await get_game_chance('cups')
    chance_roulette = await get_game_chance('roulette')
    
    def format_chance(ch):
        return f"{ch}%" if ch != -1 else "Честный рандом"
        
    text = (
        f"🌍 <b>Глобальные настройки бота</b>\n\n"
        f"💸 Базовый налог на переводы: <b>{tax}%</b>\n\n"
        f"🎰 Установленные шансы побед:\n"
        f"  • Игровые автоматы (Slots): <b>{format_chance(chance_slots)}</b>\n"
        f"  • Стаканы (Cups): <b>{format_chance(chance_cups)}</b>\n"
        f"  • Рулетка (Roulette): <b>{format_chance(chance_roulette)}</b>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Изменить налог", callback_data=f"db_gt_{chat_id}")
    builder.button(text="🎰 Настройка шансов победы", callback_data=f"db_gch_{chat_id}")
    builder.button(text="📝 Белый список групп", callback_data=f"db_gwl_{chat_id}")
    builder.button(text="🧹 Глобальный вайп экономики", callback_data=f"db_gwipes_{chat_id}")
    
    if chat_id != 0:
        builder.button(text="⬅️ Назад к меню группы", callback_data=f"db_m_{chat_id}")
    else:
        builder.button(text="⬅️ К выбору чатов", callback_data="db_sc_0")
        
    builder.adjust(1)
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
    
    chance_slots = await get_game_chance('slots')
    chance_cups = await get_game_chance('cups')
    chance_roulette = await get_game_chance('roulette')
    
    def fmt(ch):
        return f"{ch}%" if ch != -1 else "Честный рандом"
        
    text = (
        f"🎰 <b>Настройка принудительных шансов победы</b>\n\n"
        f"Укажите игру для изменения шанса:\n\n"
        f"🎰 Slots: <b>{fmt(chance_slots)}</b>\n"
        f"🥤 Cups: <b>{fmt(chance_cups)}</b>\n"
        f"🎡 Roulette: <b>{fmt(chance_roulette)}</b>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎰 Slots", callback_data=f"db_gsc_{chat_id}_slots")
    builder.button(text="🥤 Cups", callback_data=f"db_gsc_{chat_id}_cups")
    builder.button(text="🎡 Roulette", callback_data=f"db_gsc_{chat_id}_roulette")
    builder.button(text="⬅️ Назад к настройкам", callback_data=f"db_glob_{chat_id}")
    builder.adjust(3, 1)
    
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
    # Симулируем callback-вызов
    class MockCallback:
        def __init__(self):
            self.message = message
            self.bot = bot
            self.data = f"db_gch_{chat_id}"
            
        async def answer(self):
            pass
            
    await cb_game_chances_menu(MockCallback(), state)
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
    
    # Возвращаемся в whitelist view
    bot = message.bot
    class MockCallback:
        def __init__(self):
            self.message = message
            self.bot = bot
            self.data = f"db_gwl_{chat_id}"
            
        async def answer(self):
            pass
            
    await cb_whitelist_view(MockCallback(), state)
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
