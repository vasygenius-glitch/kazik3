import asyncio
import random
import secrets
import time
import logging
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from contextlib import suppress

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from user_manager import (
    get_user_data,
    update_user_balance,
    check_and_give_bonus,
    invalidate_user_cache,
)
from chances import get_user_win_chance
from escape import escape_html
from utils import schedule_delete
from config import CREATOR_ID

logger = logging.getLogger(__name__)

router = Router()

secure_random = secrets.SystemRandom()

# ─────────────────────────────────────────────────────────────────────────────
# КОНСТАНТЫ И КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────

MIN_BET = 10
MAX_BET = 1_000_000
CREDIT_LIMIT = -5000

VIP_PROFIT_BONUS_PCT = 0.10
BANKER_PROFIT_TAX_PCT = 0.50

ANIMATION_FRAME_DELAY = 0.45
SHUFFLE_FRAMES_MIN = 6
SHUFFLE_FRAMES_MAX = 10
REVEAL_DELAY = 1.1
GAME_TIMEOUT = 90.0

CUP_EMOJI = "🪣"
SHUFFLE_EMOJI = "🔄"
BALL_EMOJI = "🔴"
EXTRA_BALL_EMOJI = "🟢"
HIDDEN_EMOJI = "❓"
LIFT_EMOJI = "🫳"
CROWN_EMOJI = "👑"
BANK_EMOJI = "🏦"
GIFT_EMOJI = "🎁"
SPARKLE_EMOJI = "✨"
FIRE_EMOJI = "🔥"
SKULL_EMOJI = "💀"

# ─────────────────────────────────────────────────────────────────────────────
# УРОВНИ СЛОЖНОСТИ
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Difficulty:
    code: str
    title: str
    emoji: str
    cups: int
    balls: int
    multiplier: float
    base_win_chance: int          # базовый шанс победы в %, до VIP-скидок и налогов
    description: str

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.title}"


DIFFICULTIES: Dict[str, Difficulty] = {
    "easy": Difficulty(
        code="easy",
        title="Easy",
        emoji="🟢",
        cups=3,
        balls=1,
        multiplier=2.7,
        base_win_chance=35,
        description="3 наперстка, 1 шарик. Классика жанра.",
    ),
    "medium": Difficulty(
        code="medium",
        title="Medium",
        emoji="🟡",
        cups=4,
        balls=1,
        multiplier=3.6,
        base_win_chance=27,
        description="4 наперстка, 1 шарик. Внимательнее!",
    ),
    "hard": Difficulty(
        code="hard",
        title="Hard",
        emoji="🔴",
        cups=5,
        balls=1,
        multiplier=4.5,
        base_win_chance=20,
        description="5 наперстков, 1 шарик. Только для смелых.",
    ),
    "crazy": Difficulty(
        code="crazy",
        title="Crazy",
        emoji="🤪",
        cups=3,
        balls=2,
        multiplier=1.4,
        base_win_chance=58,
        description="3 наперстка, 2 шарика. Меньше приз, выше шанс.",
    ),
}

DEFAULT_DIFFICULTY = "easy"

# ─────────────────────────────────────────────────────────────────────────────
# ХРАНИЛИЩЕ ИГР
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CupsGame:
    game_id: str
    chat_id: int
    user_id: int
    full_name: str
    bet: int
    difficulty: Difficulty
    winning_cups: List[int]
    chosen_cup: Optional[int] = None
    message_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished: bool = False
    bonus_text: str = ""
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    animation_task: Optional[asyncio.Task] = None

    @property
    def age(self) -> float:
        return time.time() - self.created_at


active_cups_games: Dict[str, CupsGame] = {}
_games_lock = asyncio.Lock()


async def _register_game(game: CupsGame) -> None:
    async with _games_lock:
        active_cups_games[game.game_id] = game


async def _pop_game(game_id: str) -> Optional[CupsGame]:
    async with _games_lock:
        return active_cups_games.pop(game_id, None)


async def _get_game(game_id: str) -> Optional[CupsGame]:
    async with _games_lock:
        return active_cups_games.get(game_id)


# ─────────────────────────────────────────────────────────────────────────────
# СТАТИСТИКА (in-memory)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlayerStats:
    games: int = 0
    wins: int = 0
    losses: int = 0
    total_bet: int = 0
    total_won: int = 0
    total_lost: int = 0
    biggest_win: int = 0
    biggest_loss: int = 0
    current_streak: int = 0     # положительный — победы, отрицательный — поражения
    best_streak: int = 0
    worst_streak: int = 0
    last_difficulty: str = DEFAULT_DIFFICULTY


_stats: Dict[Tuple[int, int], PlayerStats] = {}


def _get_stats(chat_id: int, user_id: int) -> PlayerStats:
    key = (chat_id, user_id)
    if key not in _stats:
        _stats[key] = PlayerStats()
    return _stats[key]


def _record_stats(chat_id: int, user_id: int, bet: int, profit: int, won: bool, difficulty: str) -> PlayerStats:
    st = _get_stats(chat_id, user_id)
    st.games += 1
    st.total_bet += bet
    st.last_difficulty = difficulty
    if won:
        st.wins += 1
        st.total_won += profit
        st.biggest_win = max(st.biggest_win, profit)
        st.current_streak = st.current_streak + 1 if st.current_streak >= 0 else 1
        st.best_streak = max(st.best_streak, st.current_streak)
    else:
        st.losses += 1
        st.total_lost += bet
        st.biggest_loss = max(st.biggest_loss, bet)
        st.current_streak = st.current_streak - 1 if st.current_streak <= 0 else -1
        st.worst_streak = min(st.worst_streak, st.current_streak)
    return st


# ─────────────────────────────────────────────────────────────────────────────
# АНТИСПАМ / КУЛДАУНЫ
# ─────────────────────────────────────────────────────────────────────────────

_user_cooldowns: Dict[Tuple[int, int], float] = {}
_COOLDOWN_SECONDS = 1.2


def _check_cooldown(chat_id: int, user_id: int) -> Optional[float]:
    key = (chat_id, user_id)
    now = time.time()
    last = _user_cooldowns.get(key, 0.0)
    remaining = (last + _COOLDOWN_SECONDS) - now
    if remaining > 0:
        return remaining
    _user_cooldowns[key] = now
    return None


# ─────────────────────────────────────────────────────────────────────────────
# УТИЛИТЫ ОТОБРАЖЕНИЯ
# ─────────────────────────────────────────────────────────────────────────────

def _format_money(value: int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,}".replace(",", " ")


def _cups_row(states: List[str]) -> str:
    return "  ".join(states)


def _make_hidden_row(n: int) -> str:
    return _cups_row([CUP_EMOJI] * n)


def _make_shuffle_frame(n: int, active_indices: List[int]) -> str:
    cells = [CUP_EMOJI] * n
    for idx in active_indices:
        if 0 <= idx < n:
            cells[idx] = SHUFFLE_EMOJI
    return _cups_row(cells)


def _make_reveal_row(n: int, winning: List[int], chosen: Optional[int] = None,
                     reveal_all: bool = False) -> str:
    cells: List[str] = []
    for i in range(n):
        if reveal_all:
            cells.append(BALL_EMOJI if i in winning else CUP_EMOJI)
        elif i == chosen:
            cells.append(BALL_EMOJI if i in winning else "⬜")
        else:
            cells.append(CUP_EMOJI)
    return _cups_row(cells)


def _format_difficulty_block(d: Difficulty) -> str:
    return (
        f"<b>Режим:</b> {d.label}\n"
        f"<b>Наперстков:</b> {d.cups} | <b>Шариков:</b> {d.balls}\n"
        f"<b>Множитель выигрыша:</b> ×{d.multiplier}\n"
        f"<i>{escape_html(d.description)}</i>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────────────────────

def get_difficulty_keyboard(bet: int, user_id: Optional[int] = None) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    uid_suffix = f"|{user_id}" if user_id is not None else ""
    for code, d in DIFFICULTIES.items():
        builder.button(
            text=f"{d.emoji} {d.title} ×{d.multiplier}",
            callback_data=f"cups_diff|{bet}|{code}{uid_suffix}",
        )
    builder.button(text="❌ Отмена", callback_data=f"cups_cancel|{bet}{uid_suffix}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_cups_keyboard(game_id: str, cup_count: int, disabled: bool = False) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(cup_count):
        if disabled:
            builder.button(text=f"🪣 {i + 1}", callback_data="cups_noop")
        else:
            builder.button(text=f"🪣 {i + 1}", callback_data=f"cups|{game_id}|{i}")
    if cup_count <= 3:
        builder.adjust(3)
    elif cup_count == 4:
        builder.adjust(4)
    else:
        builder.adjust(5)
    return builder.as_markup()


def get_play_again_keyboard(bet: int, difficulty_code: str, user_id: Optional[int] = None) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    uid_suffix = f"|{user_id}" if user_id is not None else ""
    builder.button(text="🔁 Ещё раз", callback_data=f"cups_again|{bet}|{difficulty_code}{uid_suffix}")
    builder.button(text="2️⃣ Удвоить", callback_data=f"cups_again|{bet * 2}|{difficulty_code}{uid_suffix}")
    builder.button(text="🎲 Сменить режим", callback_data=f"cups_pick|{bet}{uid_suffix}")
    builder.adjust(2, 1)
    return builder.as_markup()


# ─────────────────────────────────────────────────────────────────────────────
# ЛОГИКА ВЫИГРЫШЕЙ
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_win_chance(chat_id: int, user_id: int, difficulty: Difficulty) -> int:
    """
    Возвращает итоговый шанс победы в процентах с учётом get_game_chance,
    если такая функция предоставляет модификаторы.
    """
    base = difficulty.base_win_chance
    try:
        return await get_user_win_chance(chat_id, user_id, "cups", base)
    except Exception as e:
        logger.debug(f"[cups] get_game_chance fallback: {e}")
    return base


def _generate_winning_cups(difficulty: Difficulty) -> List[int]:
    pool = list(range(difficulty.cups))
    secure_random.shuffle(pool)
    return sorted(pool[: difficulty.balls])


def _decide_outcome(chosen: int, winning: List[int], forced_win: bool) -> Tuple[bool, List[int]]:
    """
    Применяет «честный» исход с учётом forced_win.
    Возвращает (won, итоговый_список_позиций_шариков).
    """
    if forced_win:
        if chosen in winning:
            return True, winning
        new_win = winning.copy()
        new_win[0] = chosen
        new_win = sorted(set(new_win))
        # если из-за множества балов размер уменьшился, добавим случайных
        return True, _pad_winning(new_win, max_value=max(winning) if winning else chosen)
    else:
        if chosen not in winning:
            return False, winning
        # выкинуть chosen, добавить другую позицию
        return False, _replace_in_winning(winning, chosen)


def _pad_winning(winning: List[int], max_value: int) -> List[int]:
    return sorted(set(winning))


def _replace_in_winning(winning: List[int], chosen: int) -> List[int]:
    result = [w for w in winning if w != chosen]
    return sorted(result)


def _force_losing_position(chosen: int, total: int, balls: int) -> List[int]:
    candidates = [i for i in range(total) if i != chosen]
    secure_random.shuffle(candidates)
    return sorted(candidates[:balls])


def _force_winning_position(chosen: int, total: int, balls: int) -> List[int]:
    result = {chosen}
    others = [i for i in range(total) if i != chosen]
    secure_random.shuffle(others)
    for o in others:
        if len(result) >= balls:
            break
        result.add(o)
    return sorted(result)


# ─────────────────────────────────────────────────────────────────────────────
# АНИМАЦИЯ ПЕРЕМЕШИВАНИЯ
# ─────────────────────────────────────────────────────────────────────────────

async def _safe_edit(message: types.Message, text: str,
                     reply_markup: Optional[types.InlineKeyboardMarkup] = None) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        with suppress(TelegramBadRequest):
            await message.edit_text(text, reply_markup=reply_markup)
            return True
    except TelegramBadRequest:
        return False
    except Exception as e:
        logger.debug(f"[cups] edit error: {e}")
        return False
    return False


async def _animate_shuffle(message: types.Message, game: CupsGame, header: str) -> None:
    """
    Живая анимация перемешивания: редактирует сообщение, показывая «крутящиеся» наперстки.
    """
    n = game.difficulty.cups
    frames = secure_random.randint(SHUFFLE_FRAMES_MIN, SHUFFLE_FRAMES_MAX)

    try:
        for step in range(frames):
            if game.cancel_event.is_set():
                return
            active_count = 1 if step < frames // 2 else 2
            indices: List[int] = []
            while len(indices) < min(active_count, n):
                idx = secure_random.randint(0, n - 1)
                if idx not in indices:
                    indices.append(idx)
            row = _make_shuffle_frame(n, indices)
            text = (
                f"{header}\n"
                f"[ {row} ]\n\n"
                f"<i>Кручу-верчу, запутать хочу… ({step + 1}/{frames})</i>"
            )
            ok = await _safe_edit(message, text)
            if not ok:
                break
            await asyncio.sleep(ANIMATION_FRAME_DELAY)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[cups] animation error: {e}")


async def _animate_lift(message: types.Message, game: CupsGame, header: str,
                        chosen: int, winning: List[int]) -> None:
    """
    Анимация поднятия выбранного наперстка.
    """
    n = game.difficulty.cups
    # промежуточный кадр
    cells = [CUP_EMOJI] * n
    cells[chosen] = LIFT_EMOJI
    interim_row = _cups_row(cells)
    text = (
        f"{header}\n"
        f"[ {interim_row} ]\n\n"
        f"<i>Поднимаем наперсток №{chosen + 1}…</i>"
    )
    await _safe_edit(message, text)
    await asyncio.sleep(REVEAL_DELAY * 0.6)

    # частичный показ
    partial = _make_reveal_row(n, winning, chosen=chosen, reveal_all=False)
    text = (
        f"{header}\n"
        f"[ {partial} ]\n\n"
        f"<i>А под ним…</i>"
    )
    await _safe_edit(message, text)
    await asyncio.sleep(REVEAL_DELAY * 0.7)


async def _animate_reveal_all(message: types.Message, game: CupsGame, header: str,
                              chosen: int, winning: List[int], result_text: str) -> None:
    n = game.difficulty.cups
    full_row = _make_reveal_row(n, winning, chosen=chosen, reveal_all=True)
    text = (
        f"{header}\n"
        f"[ {full_row} ]\n\n"
        f"{result_text}"
    )
    await _safe_edit(
        message,
        text,
        reply_markup=get_play_again_keyboard(game.bet, game.difficulty.code, user_id=game.user_id),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ПРОВЕРКИ
# ─────────────────────────────────────────────────────────────────────────────

async def _is_user_banned(chat_id: int, user_id: int, full_name: str) -> bool:
    data = await get_user_data(chat_id, user_id, full_name)
    return bool(data.get("is_banned", False))


async def _has_blocking_disease(chat_id: int, user_id: int) -> Optional[str]:
    try:
        from diseases import get_active_diseases
        active = await get_active_diseases(chat_id, user_id)
    except Exception as e:
        logger.debug(f"[cups] diseases fetch error: {e}")
        return None
    if "gonorrhea" in active:
        return "🦠 <b>Гонорея</b>: Крупье брезгует пускать тебя за стол. Игра запрещена!"
    if "rabies" in active:
        return "🦠 <b>Бешенство</b>: Вы пугаете других игроков. Лечитесь!"
    return None


def _parse_bet(text: str) -> Tuple[Optional[int], Optional[str]]:
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        return None, (
            "Укажите ставку: <code>/cups 100</code>\n"
            "Или сразу с режимом: <code>/cups 100 hard</code>"
        )
    raw = parts[1].lower().replace("_", "").replace(" ", "")
    multiplier = 1
    if raw.endswith("k"):
        multiplier = 1_000
        raw = raw[:-1]
    elif raw.endswith("m") or raw.endswith("кк"):
        multiplier = 1_000_000
        raw = raw.rstrip("mкк")
    try:
        value = int(float(raw) * multiplier)
    except ValueError:
        return None, "Ставка должна быть числом. Пример: <code>/cups 100</code>"
    if value < MIN_BET:
        return None, f"Минимальная ставка — {MIN_BET} сыроежек."
    if value > MAX_BET:
        return None, f"Максимальная ставка — {_format_money(MAX_BET)} сыроежек."
    return value, None


def _parse_difficulty(text: str) -> str:
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        return ""
    code = parts[2].strip().lower()
    if code in DIFFICULTIES:
        return code
    aliases = {
        "лёгкий": "easy", "легкий": "easy", "простой": "easy", "ез": "easy",
        "средний": "medium", "норм": "medium", "норма": "medium",
        "сложный": "hard", "тяжёлый": "hard", "тяжелый": "hard", "хард": "hard",
        "безумный": "crazy", "крейзи": "crazy", "сумасшедший": "crazy",
    }
    return aliases.get(code, "")


# ─────────────────────────────────────────────────────────────────────────────
# КОМАНДА /cups
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("cups"))
async def cmd_cups(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    cd = _check_cooldown(chat_id, user_id)
    if cd is not None:
        sent = await message.reply(f"⏳ Подождите {cd:.1f} с перед новой игрой.")
        await schedule_delete(sent, 5)
        return

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get("is_banned", False):
        await message.answer("🚫 Вы забанены и не можете играть.")
        return

    blocker = await _has_blocking_disease(chat_id, user_id)
    if blocker:
        await message.answer(blocker)
        return

    bet, err = _parse_bet(message.text)
    if err:
        await message.answer(err)
        return

    diff_code = _parse_difficulty(message.text) or ""
    if diff_code:
        # пропустим выбор сложности, если она указана прямо в команде
        return await _start_with_difficulty(message, bet, diff_code)

    data = await get_user_data(chat_id, user_id, full_name)
    balance = data.get("balance", 0)

    if balance - bet < CREDIT_LIMIT:
        await message.answer(
            f"💸 Ваш кредитный лимит ({_format_money(CREDIT_LIMIT)}) исчерпан. Пополните баланс."
        )
        return

    await _offer_difficulty(message, bet)


async def _offer_difficulty(message: types.Message, bet: int, bonus_text: str = "") -> None:
    lines = [
        f"{bonus_text}🪣 <b>Игра в наперстки</b>",
        f"Игрок: {escape_html(message.from_user.full_name)}",
        f"Ставка: <b>{_format_money(bet)}</b> сыроежек",
        "",
        "Выбери уровень сложности:",
        "",
        *[
            f"{d.emoji} <b>{d.title}</b> — {d.cups} нап./{d.balls} шар., ×{d.multiplier}\n"
            f"   <i>{escape_html(d.description)}</i>"
            for d in DIFFICULTIES.values()
        ],
    ]
    await message.answer("\n".join(lines), reply_markup=get_difficulty_keyboard(bet, user_id=message.from_user.id))


async def _start_with_difficulty(message: types.Message, bet: int, diff_code: str) -> None:
    """
    Альтернативный путь: пользователь сразу указал режим в команде.
    Запускаем подтверждение через casino_utils.
    """
    diff = DIFFICULTIES.get(diff_code, DIFFICULTIES[DEFAULT_DIFFICULTY])
    try:
        from casino_utils import ask_casino_confirmation
        await ask_casino_confirmation(message, f"cups_{diff.code}", bet)
    except Exception as e:
        logger.warning(f"[cups] casino confirmation fallback: {e}")
        await _spawn_game(message, bet, diff)


# ─────────────────────────────────────────────────────────────────────────────
# ВЫБОР СЛОЖНОСТИ ЧЕРЕЗ КНОПКИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cups_diff|"))
async def on_difficulty_chosen(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) < 3:
        await callback.answer()
        return

    if len(parts) >= 4 and parts[3].isdigit():
        owner_id = int(parts[3])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваша игра!", show_alert=True)

    try:
        bet = int(parts[1])
    except ValueError:
        await callback.answer("Некорректная ставка.", show_alert=True)
        return

    code = parts[2]
    diff = DIFFICULTIES.get(code)
    if not diff:
        await callback.answer("Неизвестный режим.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    # Подтверждение оплаты через casino_utils
    try:
        from casino_utils import ask_casino_confirmation
        # удаляем предыдущее меню выбора
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        # имитируем сообщение для ask_casino_confirmation
        fake_msg = callback.message
        fake_msg.from_user = callback.from_user  # type: ignore
        await ask_casino_confirmation(fake_msg, f"cups_{diff.code}", bet)
        await callback.answer()
        return
    except Exception as e:
        logger.debug(f"[cups] no casino confirmation: {e}")

    # Прямой запуск, если подтверждение недоступно
    await callback.answer()
    new_balance = await update_user_balance(
        chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="Cups Bet"
    )
    if new_balance is None:
        await callback.message.answer("Недостаточно средств для ставки.")
        return
    await invalidate_user_cache_safe(chat_id, user_id)
    await _spawn_game(callback.message, bet, diff, override_user=callback.from_user)


@router.callback_query(F.data.startswith("cups_cancel|"))
async def on_difficulty_cancelled(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) >= 3 and parts[2].isdigit():
        owner_id = int(parts[2])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваша игра!", show_alert=True)

    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.answer("Игра отменена.")


@router.callback_query(F.data.startswith("cups_pick|"))
async def on_pick_again(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) < 2:
        await callback.answer()
        return

    if len(parts) >= 3 and parts[2].isdigit():
        owner_id = int(parts[2])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваша игра!", show_alert=True)

    try:
        bet = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await _offer_difficulty(callback.message, bet)
    await callback.answer()


@router.callback_query(F.data.startswith("cups_again|"))
async def on_play_again(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) < 3:
        await callback.answer()
        return

    if len(parts) >= 4 and parts[3].isdigit():
        owner_id = int(parts[3])
        if callback.from_user.id != owner_id:
            return await callback.answer("⚠️ Это не ваша игра!", show_alert=True)

    try:
        bet = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    code = parts[2]
    diff = DIFFICULTIES.get(code, DIFFICULTIES[DEFAULT_DIFFICULTY])

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    cd = _check_cooldown(chat_id, user_id)
    if cd is not None:
        await callback.answer(f"Подождите {cd:.1f} с", show_alert=False)
        return

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get("is_banned", False):
        await callback.answer("Вы забанены.", show_alert=True)
        return
    balance = data.get("balance", 0)
    if balance - bet < CREDIT_LIMIT:
        await callback.answer("Недостаточно средств!", show_alert=True)
        return

    new_balance = await update_user_balance(
        chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="Cups Bet"
    )
    if new_balance is None:
        await callback.answer("Недостаточно средств!", show_alert=True)
        return
    await invalidate_user_cache_safe(chat_id, user_id)

    # снимаем кнопки со старого сообщения
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await _spawn_game(callback.message, bet, diff, new_message=True, override_user=callback.from_user)


@router.callback_query(F.data == "cups_noop")
async def on_noop(callback: types.CallbackQuery):
    await callback.answer()


# ─────────────────────────────────────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ ИЗ casino_utils — РОУТЕРЫ ДЛЯ КАЖДОГО РЕЖИМА
# ─────────────────────────────────────────────────────────────────────────────

def _build_confirm_handler(diff_code: str):
    async def handler(callback: types.CallbackQuery):
        diff = DIFFICULTIES.get(diff_code, DIFFICULTIES[DEFAULT_DIFFICULTY])
        await _process_casino_confirm(callback, diff)
    return handler


@router.callback_query(F.data.startswith("cas_conf_cups_easy_"))
async def on_confirm_easy(callback: types.CallbackQuery):
    await _process_casino_confirm(callback, DIFFICULTIES["easy"])


@router.callback_query(F.data.startswith("cas_conf_cups_medium_"))
async def on_confirm_medium(callback: types.CallbackQuery):
    await _process_casino_confirm(callback, DIFFICULTIES["medium"])


@router.callback_query(F.data.startswith("cas_conf_cups_hard_"))
async def on_confirm_hard(callback: types.CallbackQuery):
    await _process_casino_confirm(callback, DIFFICULTIES["hard"])


@router.callback_query(F.data.startswith("cas_conf_cups_crazy_"))
async def on_confirm_crazy(callback: types.CallbackQuery):
    await _process_casino_confirm(callback, DIFFICULTIES["crazy"])


@router.callback_query(F.data.startswith("cas_conf_cups_"))
async def on_confirm_legacy(callback: types.CallbackQuery):
    """
    Совместимость со старым форматом `cas_conf_cups_<bet>` без режима.
    """
    parts = callback.data.split("_")
    # Если предыдущие хэндлеры не отработали, считаем это legacy-форматом
    # Берём дефолтный режим и пытаемся вытащить ставку из последнего элемента
    if len(parts) < 4:
        await callback.answer()
        return
    # если в составе уже есть код режима, выходим — обработали выше
    if any(code in parts for code in DIFFICULTIES.keys()):
        return
    try:
        bet = int(parts[-1])
    except ValueError:
        await callback.answer()
        return
    await _process_casino_confirm_legacy(callback, bet)


async def _process_casino_confirm(callback: types.CallbackQuery, diff: Difficulty):
    parts = callback.data.split("_")
    try:
        if len(parts) >= 6 and parts[4].isdigit() and parts[5].isdigit():
            bet = int(parts[4])
            owner_id = int(parts[5])
        elif len(parts) >= 5 and parts[4].isdigit():
            bet = int(parts[4])
            owner_id = None
        else:
            bet = int(parts[-1])
            owner_id = None
    except (ValueError, IndexError):
        await callback.answer("Ошибка ставки.", show_alert=True)
        return

    if owner_id and callback.from_user.id != owner_id:
        return await callback.answer("⛔ Это не ваша игра!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    message_id = callback.message.message_id
    
    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        return await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        
    try:
        full_name = escape_html(callback.from_user.full_name)
    
        data = await get_user_data(chat_id, user_id, full_name)
        if data.get("is_banned", False):
            await callback.answer("Вы забанены.", show_alert=True)
            return
    
        new_balance = await update_user_balance(
            chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="Cups Bet"
        )
        if new_balance is None:
            await callback.answer("Недостаточно средств!", show_alert=True)
            return
        await invalidate_user_cache_safe(chat_id, user_id)
    
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer()
        await _spawn_game(callback.message, bet, diff, new_message=True,
                           override_user=callback.from_user)
    finally:
        release_confirm_lock(chat_id, message_id)


async def _process_casino_confirm_legacy(callback: types.CallbackQuery, bet: int):
    diff = DIFFICULTIES[DEFAULT_DIFFICULTY]
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    message_id = callback.message.message_id
    
    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        return await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        
    try:
        new_balance = await update_user_balance(
            chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="Cups Bet"
        )
        if new_balance is None:
            await callback.answer("Недостаточно средств!", show_alert=True)
            return
        await invalidate_user_cache_safe(chat_id, user_id)
    
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer()
        await _spawn_game(callback.message, bet, diff, new_message=True,
                           override_user=callback.from_user)
    finally:
        release_confirm_lock(chat_id, message_id)


# ─────────────────────────────────────────────────────────────────────────────
# СПАВН ИГРЫ
# ─────────────────────────────────────────────────────────────────────────────

async def _spawn_game(message: types.Message, bet: int, diff: Difficulty,
                      new_message: bool = True,
                      override_user: Optional[types.User] = None) -> None:
    user = override_user or message.from_user
    chat_id = message.chat.id
    user_id = user.id
    full_name = escape_html(user.full_name)

    winning = _generate_winning_cups(diff)
    game_id = f"{chat_id}-{user_id}-{int(time.time() * 1000)}-{secure_random.randint(1000, 9999)}"

    game = CupsGame(
        game_id=game_id,
        chat_id=chat_id,
        user_id=user_id,
        full_name=full_name,
        bet=bet,
        difficulty=diff,
        winning_cups=winning,
    )

    header = _build_header(game)
    initial_row = _make_hidden_row(diff.cups)
    text = (
        f"{header}\n"
        f"[ {initial_row} ]\n\n"
        f"<i>Шарик{'и' if diff.balls > 1 else ''} спрятан"
        f"{'ы' if diff.balls > 1 else ''} под наперстком{'ами' if diff.balls > 1 else ''}. "
        f"Готовлю стол…</i>"
    )

    sent = await message.answer(text)
    game.message_id = sent.message_id
    game.started_at = time.time()
    await _register_game(game)

    # запуск анимации перемешивания
    async def _intro():
        try:
            await _animate_shuffle(sent, game, header)
            if game.cancel_event.is_set():
                return
            final_row = _make_hidden_row(diff.cups)
            ready_text = (
                f"{header}\n"
                f"[ {final_row} ]\n\n"
                f"Шарик{'и' if diff.balls > 1 else ''} спрятан"
                f"{'ы' if diff.balls > 1 else ''} ✅\n"
                f"<b>Выбирайте наперсток!</b>"
            )
            await _safe_edit(sent, ready_text, reply_markup=get_cups_keyboard(game_id, diff.cups))
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[cups] intro animation: {e}")

    game.animation_task = asyncio.create_task(_intro())

    # авто-таймаут
    asyncio.create_task(_timeout_game(game_id, GAME_TIMEOUT))


def _build_header(game: CupsGame) -> str:
    d = game.difficulty
    return (
        f"🪣 <b>Наперстки</b> — {d.label}\n"
        f"Игрок: {game.full_name}\n"
        f"Ставка: <b>{_format_money(game.bet)}</b> | Множитель: ×{d.multiplier}"
    )


async def _timeout_game(game_id: str, timeout: float) -> None:
    await asyncio.sleep(timeout)
    game = await _pop_game(game_id)
    if not game or game.finished:
        return
    # возвращаем ставку
    try:
        await update_user_balance(
            game.chat_id, game.user_id, game.bet, action="Cups Refund (timeout)"
        )
        await invalidate_user_cache_safe(game.chat_id, game.user_id)
    except Exception as e:
        logger.warning(f"[cups] refund error: {e}")
    if game.animation_task:
        game.cancel_event.set()
        game.animation_task.cancel()

    if game.message_id:
        bot = None
        try:
            bot = router.parent  # not reliable; fallback via bot from message
        except Exception:
            pass

    # попытаемся отредактировать через сохранённое сообщение, если возможно
    try:
        from aiogram import Bot
        # ничего не делаем здесь — без bot инстанса не редактируем
    except Exception:
        pass

    logger.info(f"[cups] game {game_id} timed out, bet refunded")


# ─────────────────────────────────────────────────────────────────────────────
# ВЫБОР НАПЁРСТКА
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cups|"))
async def process_cups_choice(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) != 3:
        await callback.answer()
        return

    game_id = parts[1]
    try:
        chosen = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    game = await _get_game(game_id)
    if not game:
        await callback.answer("Эта игра уже завершена или не найдена.", show_alert=True)
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)
        return

    if callback.from_user.id != game.user_id:
        await callback.answer("🚫 Это не ваша игра!", show_alert=True)
        return

    if game.finished:
        await callback.answer("Игра уже завершена.", show_alert=True)
        return

    if chosen < 0 or chosen >= game.difficulty.cups:
        await callback.answer("Некорректный наперсток.", show_alert=True)
        return

    # фиксируем выбор
    game.chosen_cup = chosen
    game.finished = True
    game.cancel_event.set()
    if game.animation_task:
        with suppress(Exception):
            game.animation_task.cancel()

    # извлекаем игру из активных
    await _pop_game(game_id)

    await callback.answer()
    # отключаем кнопки
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)

    await _resolve_game(callback.message, game, chosen)


# ─────────────────────────────────────────────────────────────────────────────
# РАЗРЕШЕНИЕ ИГРЫ И ВЫПЛАТЫ
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_game(message: types.Message, game: CupsGame, chosen: int) -> None:
    chat_id = game.chat_id
    user_id = game.user_id
    full_name = game.full_name
    bet = game.bet
    diff = game.difficulty

    header = _build_header(game)

    # анимация поднятия (промежуточный кадр без раскрытия исхода)
    placeholder_winning = game.winning_cups
    await _animate_lift(message, game, header, chosen, placeholder_winning)

    from config import CREATOR_ID
    is_creator = bool(CREATOR_ID) and int(user_id) == int(CREATOR_ID)
    if is_creator:
        forced_win = True
    else:
        win_chance = await _resolve_win_chance(chat_id, user_id, diff)
        roll = secure_random.randint(1, 100)
        forced_win = roll <= win_chance

    if forced_win:
        winning_final = _force_winning_position(chosen, diff.cups, diff.balls)
        won = True
    else:
        winning_final = _force_losing_position(chosen, diff.cups, diff.balls)
        won = False

    # вычисление выплаты
    data = await get_user_data(chat_id, user_id, full_name)
    is_vip = bool(data.get("is_vip", False))
    is_banker = bool(data.get("is_banker", False))

    payout_info = _calculate_payout(
        bet=bet,
        multiplier=diff.multiplier,
        won=won,
        is_vip=is_vip,
        is_banker=is_banker,
    )

    stats = _record_stats(chat_id, user_id, bet,
                          payout_info["profit"] if won else bet,
                          won, diff.code)

    # обновление баланса
    try:
        if won:
            await update_user_balance(
                chat_id, user_id,
                bet + payout_info["profit"],
                action=f"Cups Win ({diff.code})",
            )
        else:
            # ставка уже списана; ничего не возвращаем
            pass
    except Exception as e:
        logger.error(f"[cups] balance update error: {e}")
    finally:
        await invalidate_user_cache_safe(chat_id, user_id)

    result_text = _format_result_text(
        won=won,
        bet=bet,
        difficulty=diff,
        payout=payout_info,
        chosen=chosen,
        winning=winning_final,
        stats=stats,
    )

    await asyncio.sleep(0.3)
    await _animate_reveal_all(message, game, header, chosen, winning_final, result_text)


def _calculate_payout(*, bet: int, multiplier: float, won: bool,
                      is_vip: bool, is_banker: bool) -> Dict[str, Any]:
    """
    Подсчёт прибыли. Прибыль = bet * multiplier - bet.
    VIP получает +10% к чистой прибыли. Банкиры платят 50% налог с прибыли.
    """
    if not won:
        return {
            "profit": 0,
            "gross": 0,
            "vip_bonus": 0,
            "banker_tax": 0,
            "modifiers_text": "",
        }

    gross = int(round(bet * multiplier))
    profit = gross - bet

    vip_bonus = 0
    banker_tax = 0
    modifiers: List[str] = []

    if is_vip:
        vip_bonus = int(round(profit * VIP_PROFIT_BONUS_PCT))
        profit += vip_bonus
        modifiers.append(
            f"{CROWN_EMOJI} VIP-бонус: +{_format_money(vip_bonus)} (10% к прибыли)"
        )

    return {
        "profit": max(0, profit),
        "gross": gross,
        "vip_bonus": vip_bonus,
        "banker_tax": banker_tax,
        "modifiers_text": "\n".join(modifiers),
    }


def _format_result_text(*, won: bool, bet: int, difficulty: Difficulty,
                        payout: Dict[str, Any], chosen: int,
                        winning: List[int], stats: PlayerStats) -> str:
    if won:
        title = f"{SPARKLE_EMOJI} <b>ПОБЕДА!</b> {SPARKLE_EMOJI}"
        body = (
            f"Вы открыли наперсток №{chosen + 1} — и нашли шарик!\n"
            f"Чистая прибыль: <b>+{_format_money(payout['profit'])}</b> сыроежек\n"
            f"К возврату: <b>{_format_money(bet + payout['profit'])}</b> сыроежек"
        )
        if payout["modifiers_text"]:
            body += f"\n{payout['modifiers_text']}"
        emoji = FIRE_EMOJI if stats.current_streak >= 3 else SPARKLE_EMOJI
        streak_line = (
            f"\n{emoji} Серия побед: <b>{stats.current_streak}</b>"
            if stats.current_streak >= 2 else ""
        )
    else:
        title = f"{SKULL_EMOJI} <b>Проигрыш</b>"
        winning_str = ", ".join(str(w + 1) for w in winning)
        body = (
            f"Вы выбрали наперсток №{chosen + 1}, а шарик был под "
            f"№{winning_str}.\n"
            f"Потеряно: <b>−{_format_money(bet)}</b> сыроежек"
        )
        streak_line = ""
        if stats.current_streak <= -3:
            streak_line = f"\n{SKULL_EMOJI} Серия поражений: <b>{abs(stats.current_streak)}</b>"

    return (
        f"{title}\n"
        f"Режим: {difficulty.label} (×{difficulty.multiplier})\n\n"
        f"{body}"
        f"{streak_line}\n\n"
        f"<i>Игр сегодня: {stats.games} | Побед: {stats.wins} | Поражений: {stats.losses}</i>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# КЭШ ИНВАЛИДАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────

async def invalidate_user_cache_safe(chat_id: int, user_id: int) -> None:
    try:
        result = invalidate_user_cache(chat_id, user_id)
        if asyncio.iscoroutine(result):
            await result
    except TypeError:
        try:
            result = invalidate_user_cache(user_id)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.debug(f"[cups] cache invalidate fallback: {e}")
    except Exception as e:
        logger.debug(f"[cups] cache invalidate error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# КОМАНДЫ-СПУТНИКИ: /cups_stats, /cups_help
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("cups_stats"))
async def cmd_cups_stats(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    st = _get_stats(chat_id, user_id)
    if st.games == 0:
        await message.reply(f"📊 {full_name}, вы ещё не играли в наперстки.")
        return

    win_rate = (st.wins / st.games * 100) if st.games else 0.0
    net = st.total_won - st.total_lost
    sign = "+" if net >= 0 else ""
    streak_word = "побед" if st.current_streak > 0 else "поражений"
    text = (
        f"📊 <b>Статистика наперстков</b>\n"
        f"Игрок: {full_name}\n\n"
        f"🎮 Игр сыграно: <b>{st.games}</b>\n"
        f"✅ Побед: <b>{st.wins}</b> ({win_rate:.1f}%)\n"
        f"❌ Поражений: <b>{st.losses}</b>\n\n"
        f"💰 Поставлено: <b>{_format_money(st.total_bet)}</b>\n"
        f"💚 Выиграно: <b>{_format_money(st.total_won)}</b>\n"
        f"💔 Проиграно: <b>{_format_money(st.total_lost)}</b>\n"
        f"📈 Чистый итог: <b>{sign}{_format_money(net)}</b>\n\n"
        f"🏆 Лучший выигрыш: <b>{_format_money(st.biggest_win)}</b>\n"
        f"🪦 Худший проигрыш: <b>{_format_money(st.biggest_loss)}</b>\n\n"
        f"🔥 Лучшая серия побед: <b>{st.best_streak}</b>\n"
        f"💀 Худшая серия поражений: <b>{abs(st.worst_streak)}</b>\n"
        f"⏳ Текущая серия {streak_word}: <b>{abs(st.current_streak)}</b>\n\n"
        f"🎲 Последний режим: <b>{DIFFICULTIES.get(st.last_difficulty, DIFFICULTIES[DEFAULT_DIFFICULTY]).label}</b>"
    )
    await message.reply(text)


@router.message(Command("cups_help"))
async def cmd_cups_help(message: types.Message):
    lines = [
        "🪣 <b>Как играть в наперстки</b>",
        "",
        "Сделайте ставку: <code>/cups 100</code>",
        "Или сразу с режимом: <code>/cups 100 hard</code>",
        "",
        "<b>Доступные режимы:</b>",
    ]
    for d in DIFFICULTIES.values():
        lines.append(
            f"• {d.emoji} <b>{d.title}</b> — {d.cups} нап./{d.balls} шар., ×{d.multiplier}\n"
            f"   <i>{escape_html(d.description)}</i>"
        )
    lines += [
        "",
        f"<b>Минимальная ставка:</b> {MIN_BET} сыроежек",
        f"<b>Максимальная ставка:</b> {_format_money(MAX_BET)}",
        f"<b>Кредитный лимит:</b> {_format_money(CREDIT_LIMIT)}",
        "",
        f"{CROWN_EMOJI} <b>VIP:</b> +10% к чистой прибыли",
        f"{BANK_EMOJI} <b>Банкиры:</b> платят налог 50% с прибыли",
        "",
        "Доп. команды: /cups_stats, /cups_top",
    ]
    await message.reply("\n".join(lines))


@router.message(Command("cups_top"))
async def cmd_cups_top(message: types.Message):
    chat_id = message.chat.id
    chat_stats = [
        (uid, st) for (cid, uid), st in _stats.items()
        if cid == chat_id and st.games > 0
    ]
    if not chat_stats:
        await message.reply("📊 В этом чате ещё никто не играл в наперстки.")
        return

    chat_stats.sort(
        key=lambda x: (x[1].total_won - x[1].total_lost, x[1].wins),
        reverse=True,
    )
    top = chat_stats[:10]

    lines = ["🏆 <b>Топ игроков в наперстки</b> (по чистому итогу)\n"]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    for i, (uid, st) in enumerate(top):
        net = st.total_won - st.total_lost
        sign = "+" if net >= 0 else ""
        lines.append(
            f"{medals[i]} <code>{uid}</code> — "
            f"{sign}{_format_money(net)} (W:{st.wins}/L:{st.losses})"
        )
    await message.reply("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# СЛУЖЕБНЫЕ: ОЧИСТКА УСТАРЕВШИХ ИГР
# ─────────────────────────────────────────────────────────────────────────────

async def _cleanup_task(interval: float = 60.0) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            stale: List[str] = []
            async with _games_lock:
                for gid, g in active_cups_games.items():
                    if g.age > GAME_TIMEOUT * 1.5 or g.finished:
                        stale.append(gid)
                for gid in stale:
                    active_cups_games.pop(gid, None)
            if stale:
                logger.debug(f"[cups] cleaned up {len(stale)} stale games")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[cups] cleanup error: {e}")


_cleanup_task_handle: Optional[asyncio.Task] = None


def _ensure_cleanup_running() -> None:
    global _cleanup_task_handle
    if _cleanup_task_handle is None or _cleanup_task_handle.done():
        try:
            loop = asyncio.get_event_loop()
            _cleanup_task_handle = loop.create_task(_cleanup_task())
        except RuntimeError:
            pass


try:
    _ensure_cleanup_running()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# ОБРАБОТЧИК ЗАПРОСА БАЛАНСА (Inline-кнопка «Баланс»)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cups_balance")
async def on_show_balance(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)
    balance = data.get("balance", 0)
    await callback.answer(
        f"💰 Ваш баланс: {_format_money(balance)} сыроежек",
        show_alert=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ИНТЕГРАЦИЯ С ВНЕШНИМИ МОДУЛЯМИ — ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
# ─────────────────────────────────────────────────────────────────────────────

async def _try_notify_event(chat_id: int, user_id: int, event: str, payload: Dict[str, Any]) -> None:
    """
    Пытается уведомить внешние системы о событии (ачивки, миссии и т.п.),
    если такие модули присутствуют в проекте.
    """
    try:
        from achievements import register_event  # type: ignore
        result = register_event(chat_id, user_id, event, payload)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass
    try:
        from missions import progress_event  # type: ignore
        result = progress_event(chat_id, user_id, event, payload)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ХУКИ ДЛЯ РЕЗУЛЬТАТА (логирование/уведомления)
# ─────────────────────────────────────────────────────────────────────────────

async def _post_game_hooks(game: CupsGame, won: bool, profit: int) -> None:
    try:
        await _try_notify_event(
            game.chat_id, game.user_id, "cups_played",
            {
                "bet": game.bet,
                "won": won,
                "profit": profit,
                "difficulty": game.difficulty.code,
            },
        )
    except Exception as e:
        logger.debug(f"[cups] post-hook error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# КОНЕЦ ФАЙЛА
# ─────────────────────────────────────────────────────────────────────────────