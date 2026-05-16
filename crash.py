import asyncio
import secrets
import logging
from typing import Optional
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from user_manager import get_user_data, update_user_balance, invalidate_user_cache
from escape import escape_html
from utils import schedule_delete

logger = logging.getLogger(__name__)
router = Router()

class CrashState(StatesGroup):
    playing = State()      # Игрок летит и ждет обналичивания

# ─────────────────────────────────────────────────────────────
#  НАСТРОЙКИ ИГРЫ
# ─────────────────────────────────────────────────────────────
MIN_BET = 100
MAX_BET = 50_000_000
CREDIT_LIMIT = -5000
AUTO_DELETE_DELAY = 60

# Крипторандом
_rng = secrets.SystemRandom()

# ─────────────────────────────────────────────────────────────
#  ГЕНЕРАЦИЯ ТОЧКИ КРАША (Честное распределение с преимуществом казино)
# ─────────────────────────────────────────────────────────────
def generate_crash_point() -> float:
    """
    Генерирует точку краша.
    - В 10% случаев происходит мгновенный краш на 1.00x (House Edge).
    - В остальных случаях множитель распределяется экспоненциально.
    """
    if _rng.randint(1, 100) <= 10:
        return 1.00

    u = _rng.random()
    if u < 0.5:
        # 50% шанс: 1.01x - 2.00x
        return round(_rng.uniform(1.01, 2.00), 2)
    elif u < 0.8:
        # 30% шанс: 2.00x - 5.00x
        return round(_rng.uniform(2.00, 5.00), 2)
    elif u < 0.95:
        # 15% шанс: 5.00x - 15.00x
        return round(_rng.uniform(5.00, 15.00), 2)
    else:
        # 5% шанс: сверхвысокие выигрыши до 100.00x
        return round(_rng.uniform(15.00, 100.00), 2)

# ─────────────────────────────────────────────────────────────
#  ДИНАМИЧЕСКИЙ РЕНДЕРИНГ ASCII-ГРАФИКА
# ─────────────────────────────────────────────────────────────
def draw_ascii_chart(path_points: list[float]) -> str:
    """
    Генерирует красивую сетку ASCII-графика 6x20 с динамическим масштабированием.
    По мере полета кривая поднимается вверх к ракете 🚀.
    """
    rows = 6
    cols = 20
    grid = [[" " for _ in range(cols)] for _ in range(rows)]
    
    n_points = len(path_points)
    if n_points > 0:
        max_val = max(path_points) if max(path_points) > 1.0 else 2.0
        min_val = 1.0
        val_range = max_val - min_val if max_val > min_val else 1.0
        
        for col_idx in range(min(n_points, cols)):
            val = path_points[col_idx]
            # Нормализация высоты ячейки
            norm = (val - min_val) / val_range
            row_idx = int((rows - 1) - (norm * (rows - 1)))
            row_idx = max(0, min(rows - 1, row_idx))
            
            # Ставим ракету на конце пути, на остальных точках - след
            if col_idx == n_points - 1:
                grid[row_idx][col_idx] = "🚀"
            else:
                grid[row_idx][col_idx] = "•"
                
    # Собираем график воедино
    lines = []
    max_val = max(path_points) if path_points else 1.0
    for r in range(rows):
        val_at_row = 1.0 + ((rows - 1 - r) / (rows - 1)) * (max_val - 1.0)
        label = f"{val_at_row:.2f}x"
        row_str = "".join(grid[r])
        lines.append(f"{label:<7} │ {row_str}")
        
    lines.append("        └" + "─" * cols)
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
#  КЛАВИАТУРА
# ─────────────────────────────────────────────────────────────
def get_crash_keyboard(game_id: str, current_mult: float) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text=f"💰 ОБНАЛИЧИТЬ ({current_mult:.2f}x)",
        callback_data=f"crash_cashout_{game_id}"
    ))
    return builder.as_markup()

def get_replay_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text=f"🔁 Сыграть еще (ставка {bet})",
        callback_data=f"crash_replay_{bet}"
    ))
    return builder.as_markup()

# ─────────────────────────────────────────────────────────────
#  БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# ─────────────────────────────────────────────────────────────
async def safe_edit_message(message: types.Message, text: str, reply_markup=None) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception as exc:
        logger.debug("Crash edit failed: %s", exc)
        return False

# ─────────────────────────────────────────────────────────────
#  СТАРТ ИГРЫ
# ─────────────────────────────────────────────────────────────
@router.message(Command("crash"))
async def cmd_crash(message: types.Message, state: FSMContext):
    if await state.get_state() == CrashState.playing.state:
        await state.clear()

    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get('is_banned'):
        return

    from diseases import get_active_diseases
    if 'gonorrhea' in await get_active_diseases(chat_id, user_id):
        return await message.answer("🦠 <b>Гонорея</b>: Пилоты самолета отказываются сажать тебя на борт. Лечись!")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите ставку: <code>/crash 100</code>")

    try:
        bet = int(args[1])
        if bet < 100 or bet > 50_000_000:
            raise ValueError
    except ValueError:
        return await message.answer("Ставка должна быть числом от 100 до 50,000,000 сыроежек.")

    if data.get('balance', 0) - bet < CREDIT_LIMIT:
        return await message.answer("Ваш кредитный лимит (-5000) исчерпан. Пополните баланс.")

    # Используем стандартное подтверждение казино
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "crash", bet)

# ─────────────────────────────────────────────────────────────
#  ПОДТВЕРЖДЕНИЕ И НАЧАЛО ВЗЛЕТА
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cas_conf_crash_"))
async def process_crash_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        bet = int(callback.data.split("_")[3])
    except:
        return
    
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    
    new_balance = await update_user_balance(chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="Crash Bet")
    if new_balance is None:
        return await callback.answer("Недостаточно средств!", show_alert=True)

    await callback.message.delete()

    game_id = f"{chat_id}_{user_id}_{callback.message.message_id}"
    crash_point = generate_crash_point()

    await state.set_state(CrashState.playing)
    await state.update_data(
        game_id=game_id,
        user_id=user_id,
        chat_id=chat_id,
        full_name=full_name,
        bet=bet,
        crash_point=crash_point,
        current_multiplier=1.00,
        path_points=[1.00],
        cashed_out=False
    )

    # Стартуем полет
    graph = draw_ascii_chart([1.00])
    text = (
        f"📈 <b>КРАШ-АВИАТОР · Взлет!</b> 📈\n"
        f"<code>{graph}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Игрок: {full_name}\n"
        f"💰 Ставка: <b>{bet}</b> сыр.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 Самолет взлетел! Коэффициент: <b>1.00x</b>\n"
        f"👉 Успей нажать кнопку обналичивания до краша!"
    )

    keyboard = get_crash_keyboard(game_id, 1.00)
    msg = await callback.message.answer(text, reply_markup=keyboard)

    # Запускаем фоновую задачу полета
    asyncio.create_task(run_crash_loop(msg, state, game_id))

# ─────────────────────────────────────────────────────────────
#  ФОНОВЫЙ ИГРОВОЙ ЦИКЛ ПОЛЕТА (LOOP)
# ─────────────────────────────────────────────────────────────
async def run_crash_loop(message: types.Message, state: FSMContext, game_id: str):
    current_mult = 1.00
    path_points = [1.00]
    
    # 20 шагов полета (ширина графика)
    for step in range(1, 20):
        # Проверяем, активна ли еще игра
        st = await state.get_state()
        if st != CrashState.playing.state:
            break
            
        data = await state.get_data()
        if data.get('game_id') != game_id or data.get('cashed_out'):
            break
            
        crash_point = data['crash_point']
        bet = data['bet']
        chat_id = data['chat_id']
        user_id = data['user_id']
        full_name = data['full_name']
        
        # Расчет следующего шага множителя (плавный экспоненциальный рост)
        current_mult = round(1.00 + (step ** 1.35) * 0.05, 2)
        
        # КРАШ! Если превысили точку падения
        if current_mult >= crash_point:
            current_mult = crash_point
            path_points.append(current_mult)
            await state.clear()
            
            graph = draw_ascii_chart(path_points)
            final_text = (
                f"📈 <b>КРАШ-АВИАТОР · График взлета</b> 📈\n"
                f"<code>{graph}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Игрок: {full_name}\n"
                f"💰 Ставка: <b>{bet}</b> сыр.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💥 <b>КРАШ!</b> Самолет улетел на коэф. <b>{crash_point:.2f}x</b>!\n"
                f"💸 Вы потеряли свою ставку: <b>-{bet}</b> сыр."
            )
            await safe_edit_message(message, final_text)
            invalidate_user_cache(chat_id, user_id)
            asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))
            return
            
        # Успешный шаг: обновляем состояние и экран
        path_points.append(current_mult)
        await state.update_data(current_multiplier=current_mult, path_points=path_points)
        
        graph = draw_ascii_chart(path_points)
        text = (
            f"📈 <b>КРАШ-АВИАТОР · Полет...</b> 📈\n"
            f"<code>{graph}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Игрок: {full_name}\n"
            f"💰 Ставка: <b>{bet}</b> сыр.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 Самолет летит! Коэффициент: <b>{current_mult:.2f}x</b>\n"
            f"👉 Успей нажать кнопку обналичивания до краша!"
        )
        
        keyboard = get_crash_keyboard(game_id, current_mult)
        await safe_edit_message(message, text, reply_markup=keyboard)
        
        # Задержка между кадрами
        await asyncio.sleep(0.8)
        
    # Если долетели до предела графика (20 шагов) без падения — принудительный авто-выигрыш на максимуме!
    st = await state.get_state()
    if st == CrashState.playing.state:
        data = await state.get_data()
        if data.get('game_id') == game_id and not data.get('cashed_out'):
            await cashout_player(message, state, data, current_mult)

# ─────────────────────────────────────────────────────────────
#  ОБНАЛИЧИВАНИЕ (CASHOUT)
# ─────────────────────────────────────────────────────────────
async def cashout_player(message: types.Message, state: FSMContext, game: dict, multiplier: float):
    chat_id = game['chat_id']
    user_id = game['user_id']
    bet = game['bet']
    full_name = game['full_name']
    path_points = game['path_points']

    await state.update_data(cashed_out=True)
    await state.clear()

    win_amount = int(bet * multiplier)
    await update_user_balance(chat_id, user_id, win_amount, action="Crash Cashout")
    invalidate_user_cache(chat_id, user_id)

    graph = draw_ascii_chart(path_points)
    final_text = (
        f"📈 <b>КРАШ-АВИАТОР · Победа!</b> 📈\n"
        f"<code>{graph}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Игрок: {full_name}\n"
        f"💰 Ставка: <b>{bet}</b> сыр.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 <b>ОБНАЛИЧЕНО!</b> Вы забрали деньги на коэф. <b>{multiplier:.2f}x</b>!\n"
        f"💰 Чистый выигрыш: <b>+{win_amount - bet}</b> сыр. (Всего получено: {win_amount})"
    )

    await safe_edit_message(message, final_text, reply_markup=get_replay_keyboard(bet))
    asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))

@router.callback_query(F.data.startswith("crash_cashout_"))
async def process_crash_cashout(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != CrashState.playing.state:
        return await callback.answer()
        
    game = await state.get_data()
    if callback.from_user.id != game.get('user_id'):
        return await callback.answer("Это не ваш полет!", show_alert=True)

    await callback.answer("💰 Деньги обналичены!")
    await cashout_player(callback.message, state, game, game['current_multiplier'])

# ─────────────────────────────────────────────────────────────
#  БЫСТРЫЙ ПОВТОР (REPLAY)
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("crash_replay_"))
async def process_crash_replay(callback: types.CallbackQuery, state: FSMContext):
    try:
        bet = int(callback.data.split("_")[2])
    except:
        return await callback.answer()

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get('is_banned'):
        return await callback.answer("⛔ Вы заблокированы.", show_alert=True)

    if data.get('balance', 0) - bet < CREDIT_LIMIT:
        return await callback.answer("💳 Недостаточно средств для повтора.", show_alert=True)

    await safe_edit_message(callback.message, "🛫 Готовим взлетную полосу...")
    try:
        await callback.message.delete()
    except:
        pass

    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(callback.message, "crash", bet, user_id=user_id)
    await callback.answer("🔁 Поехали!")
