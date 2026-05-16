"""
═══════════════════════════════════════════════════════════════════════════════
                    🎰 ВИДЕОПОКЕР "JACKS OR BETTER" 🎰
═══════════════════════════════════════════════════════════════════════════════
    Классическая казино-игра с дружелюбным интерфейсом для новичков.
    
    ▸ Подробный туториал и подсказки на каждом шаге
    ▸ Красивое визуальное оформление
    ▸ Анимация раздачи карт
    ▸ Таблица выплат и история игр
    ▸ Умные советы для начинающих
═══════════════════════════════════════════════════════════════════════════════
"""

import asyncio
import secrets
import logging
from typing import Optional
from collections import Counter

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from user_manager import get_user_data, update_user_balance, invalidate_user_cache
from cards import SUITS, RANKS, format_cards
from escape import escape_html
from utils import schedule_delete

logger = logging.getLogger(__name__)
router = Router()


# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 СОСТОЯНИЯ FSM
# ═══════════════════════════════════════════════════════════════════════════════

class PokerState(StatesGroup):
    """Состояния игровой сессии видеопокера."""
    playing = State()      # Игрок выбирает карты для удержания
    confirming = State()   # Подтверждение обмена карт


# ═══════════════════════════════════════════════════════════════════════════════
# 💰 ИГРОВЫЕ КОНСТАНТЫ
# ═══════════════════════════════════════════════════════════════════════════════

# Лимиты ставок (в сыроежках)
MIN_BET = 100
MAX_BET = 50_000_000
CREDIT_LIMIT = -5000        # Допустимый "овердрафт" игрока
AUTO_DELETE_DELAY = 60      # Сек. до автоудаления финального сообщения

# Таймауты
GAME_TIMEOUT = 300          # 5 минут на ход — потом авто-сброс

# ─── ТАБЛИЦА ВЫПЛАТ (от лучшей к худшей) ───────────────────────────────────────
PAYOUT_TABLE = {
    "Royal Flush":      250,   # 🌟 Роял Флеш: 10-J-Q-K-A одной масти
    "Straight Flush":   50,    # 💎 Стрит-флеш: 5 подряд одной масти
    "Four of a Kind":   25,    # 🔥 Каре: 4 карты одного ранга
    "Full House":       9,     # 🏠 Фулл-хаус: тройка + пара
    "Flush":            6,     # 🌊 Флеш: 5 карт одной масти
    "Straight":         4,     # ➡️ Стрит: 5 карт подряд
    "Three of a Kind":  3,     # 🎯 Сет: 3 карты одного ранга
    "Two Pair":         2,     # 👬 Две пары
    "Jacks or Better":  1,     # 🤴 Пара валетов или выше
}

# Описания комбинаций для туториала (русские названия и пояснения)
COMBINATION_INFO = {
    "Royal Flush":     ("🌟 Роял Флеш",      "10, J, Q, K, A одной масти — максимум!"),
    "Straight Flush":  ("💎 Стрит-флеш",     "5 карт по порядку одной масти"),
    "Four of a Kind":  ("🔥 Каре",           "4 карты одного ранга (4 туза и т.п.)"),
    "Full House":      ("🏠 Фулл-хаус",      "Тройка + пара (например, 3 дамы + 2 семёрки)"),
    "Flush":           ("🌊 Флеш",           "Любые 5 карт одной масти"),
    "Straight":        ("➡️ Стрит",          "5 карт по порядку любых мастей"),
    "Three of a Kind": ("🎯 Сет (тройка)",   "3 карты одного ранга"),
    "Two Pair":        ("👬 Две пары",        "Две разные пары карт"),
    "Jacks or Better": ("🤴 Пара J/Q/K/A",   "Пара валетов, дам, королей или тузов"),
    "Nothing":         ("❌ Нет комбинации", "Соберите хотя бы пару валетов!"),
}

# Численные значения рангов для сравнения
RANK_VALUES = {
    '2': 2,  '3': 3,  '4': 4,  '5': 5,  '6': 6,  '7': 7,  '8': 8,
    '9': 9,  '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14
}

# Визуальные элементы интерфейса
HOLD_BADGE      = "🔒"  # Карта удержана
DROP_BADGE      = "🔄"  # Карта будет сброшена
CARD_BACK       = "🂠"  # Рубашка карты
SEPARATOR_LINE  = "━" * 27
DOUBLE_LINE     = "═" * 27

# Эмодзи мастей для красивого вывода
SUIT_COLORS = {
    "♠": "♠️",  "♣": "♣️",  "♥": "♥️",  "♦": "♦️",
    "♠️": "♠️", "♣️": "♣️", "♥️": "♥️", "♦️": "♦️",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 📊 ГЛОБАЛЬНАЯ СТАТИСТИКА (в памяти процесса)
# ═══════════════════════════════════════════════════════════════════════════════
# Хранит краткую статистику последних игр пользователя:
#   user_stats[user_id] = {
#       "games": int, "wins": int, "best": str, "biggest_win": int, "total_won": int
#   }
user_stats: dict[int, dict] = {}


def update_stats(user_id: int, combination: str, win_amount: int) -> dict:
    """Обновляет статистику игрока после партии."""
    stats = user_stats.setdefault(user_id, {
        "games": 0, "wins": 0, "best": "Nothing",
        "biggest_win": 0, "total_won": 0,
    })
    stats["games"] += 1
    if win_amount > 0:
        stats["wins"] += 1
        stats["total_won"] += win_amount
        if win_amount > stats["biggest_win"]:
            stats["biggest_win"] = win_amount

    # Обновляем "лучшую комбинацию", если она выше предыдущей
    cur_rank = PAYOUT_TABLE.get(stats["best"], 0)
    new_rank = PAYOUT_TABLE.get(combination, 0)
    if new_rank > cur_rank:
        stats["best"] = combination

    return stats


def get_stats_block(user_id: int) -> str:
    """Возвращает HTML-блок со статистикой игрока."""
    stats = user_stats.get(user_id)
    if not stats or stats["games"] == 0:
        return ""

    win_rate = (stats["wins"] / stats["games"]) * 100
    best_name = COMBINATION_INFO.get(stats["best"], ("—", ""))[0]
    return (
        f"\n📊 <b>Ваша статистика:</b>\n"
        f"  • Игр сыграно: <b>{stats['games']}</b>\n"
        f"  • Побед: <b>{stats['wins']}</b> ({win_rate:.0f}%)\n"
        f"  • Лучшая рука: {best_name}\n"
        f"  • Макс. выигрыш: <b>{stats['biggest_win']:,}</b> сыр.\n"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 🃏 РАБОТА С КОЛОДОЙ
# ═══════════════════════════════════════════════════════════════════════════════

# Криптостойкий генератор случайных чисел (честная раздача)
_rng = secrets.SystemRandom()


def get_unique_card(exclude_cards: list) -> dict:
    """
    Возвращает случайную карту, которой ещё нет в `exclude_cards`.
    Использует SystemRandom для криптографически честной раздачи.
    """
    while True:
        card = {'rank': _rng.choice(RANKS), 'suit': _rng.choice(SUITS)}
        if card not in exclude_cards:
            return card


def deal_initial_hand() -> list[dict]:
    """Сдаёт начальную руку из 5 уникальных карт."""
    hand: list[dict] = []
    for _ in range(5):
        hand.append(get_unique_card(hand))
    return hand


def redraw_cards(cards: list[dict], held_indices: list[int]) -> list[dict]:
    """Заменяет все неудержанные карты на новые уникальные."""
    new_hand = list(cards)
    for i in range(5):
        if i not in held_indices:
            new_hand[i] = get_unique_card(new_hand)
    return new_hand


def format_card(card: dict) -> str:
    """Форматирует одну карту как 'AS♠️' с цветным значком масти."""
    suit = SUIT_COLORS.get(card['suit'], card['suit'])
    return f"{card['rank']}{suit}"


# ═══════════════════════════════════════════════════════════════════════════════
# 🏆 ОЦЕНКА ПОКЕРНЫХ КОМБИНАЦИЙ
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_hand(cards: list[dict]) -> str:
    """
    Определяет покерную комбинацию для 5 карт.
    Возвращает ключ из PAYOUT_TABLE или "Nothing".
    
    Алгоритм:
      1) Считаем повторяющиеся ранги (для пар, троек, каре, фулл-хауса).
      2) Проверяем флеш (одна масть).
      3) Проверяем стрит (5 подряд), включая "колесо" A-2-3-4-5.
      4) Складываем результаты в порядке убывания силы.
    """
    if len(cards) != 5:
        return "Nothing"

    ranks = [c['rank'] for c in cards]
    suits = [c['suit'] for c in cards]
    rank_vals = sorted(RANK_VALUES[r] for r in ranks)

    # Количество повторений каждого ранга
    rank_counts = Counter(ranks)
    counts = sorted(rank_counts.values(), reverse=True)

    # ── Флеш: все карты одной масти ──
    is_flush = len(set(suits)) == 1

    # ── Стрит: 5 уникальных подряд ──
    is_straight = False
    is_low_straight = False  # "колесо" A-2-3-4-5
    if len(set(rank_vals)) == 5:
        if rank_vals[4] - rank_vals[0] == 4:
            is_straight = True
        elif rank_vals == [2, 3, 4, 5, 14]:
            is_straight = True
            is_low_straight = True

    # ── Проверки от старшей к младшей ──
    if is_flush and is_straight:
        # Роял-флеш только для 10-J-Q-K-A
        if not is_low_straight and rank_vals[0] == 10:
            return "Royal Flush"
        return "Straight Flush"

    if counts[0] == 4:
        return "Four of a Kind"

    if counts == [3, 2]:
        return "Full House"

    if is_flush:
        return "Flush"

    if is_straight:
        return "Straight"

    if counts[0] == 3:
        return "Three of a Kind"

    if counts[0] == 2 and counts[1] == 2:
        return "Two Pair"

    if counts[0] == 2:
        # Пара ценная, только если это J, Q, K или A
        pair_rank = next(r for r, cnt in rank_counts.items() if cnt == 2)
        if RANK_VALUES[pair_rank] >= 11:
            return "Jacks or Better"

    return "Nothing"


def get_held_card_indices_by_combo(cards: list[dict], combo: str) -> set[int]:
    """
    Возвращает индексы карт, которые формируют выигрышную комбинацию.
    Используется для подсветки победных карт в итоговом экране.
    """
    if combo == "Nothing":
        return set()

    rank_counts = Counter(c['rank'] for c in cards)

    # Для флешей/стритов/роялов — все 5 карт
    if combo in ("Royal Flush", "Straight Flush", "Flush", "Straight"):
        return {0, 1, 2, 3, 4}

    # Для каре/сета/пар — карты соответствующих рангов
    target_ranks = set()
    if combo == "Four of a Kind":
        target_ranks = {r for r, c in rank_counts.items() if c == 4}
    elif combo == "Full House":
        target_ranks = {r for r, c in rank_counts.items() if c >= 2}
    elif combo == "Three of a Kind":
        target_ranks = {r for r, c in rank_counts.items() if c == 3}
    elif combo == "Two Pair":
        target_ranks = {r for r, c in rank_counts.items() if c == 2}
    elif combo == "Jacks or Better":
        target_ranks = {r for r, c in rank_counts.items()
                        if c == 2 and RANK_VALUES[r] >= 11}

    return {i for i, c in enumerate(cards) if c['rank'] in target_ranks}


# ═══════════════════════════════════════════════════════════════════════════════
# 💡 ПОДСКАЗКИ ДЛЯ НОВИЧКОВ
# ═══════════════════════════════════════════════════════════════════════════════

def get_smart_hint(cards: list[dict]) -> str:
    """
    Анализирует начальную руку и даёт совет, какие карты держать.
    Совет учитывает базовую стратегию видеопокера.
    """
    rank_counts = Counter(c['rank'] for c in cards)
    suit_counts = Counter(c['suit'] for c in cards)

    # 1. Уже готовая выигрышная комбинация → держим всё
    current = evaluate_hand(cards)
    if current != "Nothing" and PAYOUT_TABLE.get(current, 0) >= 6:
        return f"💡 <b>Совет:</b> Уже есть {COMBINATION_INFO[current][0]}! Удержите все 5 карт."

    # 2. Каре, фулл-хаус — держим всё
    if current in ("Four of a Kind", "Full House"):
        return f"💡 <b>Совет:</b> Отличная рука — {COMBINATION_INFO[current][0]}! Держите всё."

    # 3. Тройка → сбросьте 2 лишних ради каре/фулл-хауса
    if 3 in rank_counts.values():
        triple_rank = next(r for r, c in rank_counts.items() if c == 3)
        return f"💡 <b>Совет:</b> Держите тройку <b>{triple_rank}</b> и тяните каре или фулл-хаус."

    # 4. Две пары → держим обе, тянем фулл-хаус
    pairs = [r for r, c in rank_counts.items() if c == 2]
    if len(pairs) == 2:
        return "💡 <b>Совет:</b> Две пары! Держите обе и тяните фулл-хаус."

    # 5. Пара J+ → ценная, держим
    if pairs:
        pr = pairs[0]
        if RANK_VALUES[pr] >= 11:
            return f"💡 <b>Совет:</b> Пара <b>{pr}</b> — уже выплата 1:1. Держите и улучшайте."
        return f"💡 <b>Совет:</b> Маленькая пара <b>{pr}</b>. Держите — есть шанс на сет."

    # 6. 4 карты одной масти → флеш-дро
    if max(suit_counts.values()) == 4:
        suit = suit_counts.most_common(1)[0][0]
        return f"💡 <b>Совет:</b> 4 карты масти {suit} — держите их, есть шанс на флеш!"

    # 7. Иначе — держим только высокие карты (J, Q, K, A)
    highs = [i for i, c in enumerate(cards) if RANK_VALUES[c['rank']] >= 11]
    if highs:
        return f"💡 <b>Совет:</b> Держите старшие карты (J/Q/K/A) — шанс на пару."
    return "💡 <b>Совет:</b> Слабая рука. Сбросьте все 5 карт и попробуйте удачу!"


# ═══════════════════════════════════════════════════════════════════════════════
# 🎨 ОТРИСОВКА ИНТЕРФЕЙСА
# ═══════════════════════════════════════════════════════════════════════════════

def render_card_row(cards: list[dict], held_indices: list[int],
                    highlight: Optional[set[int]] = None) -> str:
    """
    Красиво рисует карты в одну строку и под ними индикаторы:
        🂠  🂠  🂠  🂠  🂠
       A♠ K♥ Q♦ J♣ 10♠
       🔒  🔄  🔒  🔄  🔄
    """
    highlight = highlight or set()
    line_top, line_mid, line_bot = [], [], []

    for i, c in enumerate(cards):
        is_held = i in held_indices
        is_win = i in highlight
        face = format_card(c)

        # Карта оформляется по-разному в зависимости от статуса
        if is_win:
            line_top.append("✨")
            line_mid.append(f"<b>{face}</b>")
            line_bot.append("🏆")
        elif is_held:
            line_top.append("📌")
            line_mid.append(f"<b>{face}</b>")
            line_bot.append(HOLD_BADGE)
        else:
            line_top.append("· ")
            line_mid.append(f"<i>{face}</i>")
            line_bot.append(DROP_BADGE)

    return (
        "  ".join(line_top) + "\n"
        + "  ".join(line_mid) + "\n"
        + "  ".join(f"<code>{i+1}</code>" for i in range(5)) + "\n"
        + "  ".join(line_bot)
    )


def render_card_list(cards: list[dict], held_indices: list[int],
                     highlight: Optional[set[int]] = None) -> str:
    """Текстовый список карт под номерами для тех, у кого узкий экран."""
    highlight = highlight or set()
    lines = []
    for i, c in enumerate(cards):
        face = format_card(c)
        if i in highlight:
            badge, label = "🏆", "<b>ВЫИГРЫШНАЯ</b>"
        elif i in held_indices:
            badge, label = HOLD_BADGE, "<b>Удержана</b>"
        else:
            badge, label = DROP_BADGE, "<i>Будет сброшена</i>"
        lines.append(f"  {badge}  <code>{i+1}.</code> <b>{face}</b> — {label}")
    return "\n".join(lines)


def get_game_screen(cards: list[dict], held_indices: list[int],
                    user_name: str, bet: int, status_text: str,
                    *, highlight: Optional[set[int]] = None,
                    show_hint: bool = False) -> str:
    """Главный экран игры — компонует все секции в одно сообщение."""
    potential_combo = evaluate_hand(cards) if not highlight else None
    potential_text = ""
    if show_hint and potential_combo and potential_combo != "Nothing":
        mult = PAYOUT_TABLE.get(potential_combo, 0)
        name = COMBINATION_INFO[potential_combo][0]
        potential_text = f"\n🎲 <b>Сейчас на руках:</b> {name} (x{mult})"

    hint = ("\n" + get_smart_hint(cards)) if show_hint else ""

    return (
        f"🎰 <b>ВИДЕОПОКЕР</b> · <i>Jacks or Better</i> 🎰\n"
        f"{DOUBLE_LINE}\n"
        f"👤 <b>Игрок:</b> {user_name}\n"
        f"💰 <b>Ставка:</b> {bet:,} сыр.\n"
        f"{SEPARATOR_LINE}\n"
        f"{render_card_list(cards, held_indices, highlight)}\n"
        f"{potential_text}"
        f"{SEPARATOR_LINE}\n"
        f"{status_text}"
        f"{hint}"
    )


def get_payout_table_text() -> str:
    """Возвращает HTML-строку с полной таблицей выплат."""
    lines = ["💰 <b>ТАБЛИЦА ВЫПЛАТ</b>", DOUBLE_LINE]
    for combo, mult in PAYOUT_TABLE.items():
        name, descr = COMBINATION_INFO[combo]
        lines.append(f"<b>x{mult:<3}</b> · {name}\n      <i>{descr}</i>")
    lines.append(DOUBLE_LINE)
    lines.append("ℹ️ Множитель умножается на размер вашей ставки.")
    return "\n".join(lines)


def get_tutorial_text() -> str:
    """Подробный гайд для новичков."""
    return (
        "📖 <b>КАК ИГРАТЬ В ВИДЕОПОКЕР</b>\n"
        f"{DOUBLE_LINE}\n"
        "🎯 <b>Цель:</b> собрать одну из выигрышных комбинаций.\n\n"
        "🎮 <b>Правила игры:</b>\n"
        "  <b>1.</b> Вы делаете ставку командой <code>/poker 100</code>.\n"
        "  <b>2.</b> Получаете 5 случайных карт.\n"
        "  <b>3.</b> Решаете, какие оставить (🔒 Hold), нажав на номер.\n"
        "  <b>4.</b> Нажимаете <b>«Обменять»</b> — несохранённые карты\n"
        "       заменяются новыми.\n"
        "  <b>5.</b> Если итоговая рука — выигрышная комбинация,\n"
        "       вы получаете выплату по таблице.\n\n"
        "💡 <b>Подсказки:</b>\n"
        "  • Минимальная выплата — за пару валетов и выше.\n"
        "  • Не сбрасывайте уже готовые комбинации!\n"
        "  • Если есть 4 карты одной масти — стремитесь к флешу.\n"
        "  • Если 4 карты подряд — пытайтесь поймать стрит.\n"
        "  • Кнопка <b>«Сбросить все»</b> снимает все Hold-метки.\n\n"
        f"{SEPARATOR_LINE}\n"
        "💰 <b>Ставки:</b>\n"
        f"  • Минимальная: <b>{MIN_BET:,}</b> сыр.\n"
        f"  • Максимальная: <b>{MAX_BET:,}</b> сыр.\n\n"
        "📊 Нажмите кнопку ниже, чтобы увидеть таблицу выплат."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ⌨️ КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════════════════════════

def get_poker_keyboard(game_id: str, held_indices: list[int],
                       show_confirm: bool = False) -> types.InlineKeyboardMarkup:
    """
    Главная игровая клавиатура.
    
    Layout (5 карт + действия):
        [ 🔒 1 ] [ 🔄 2 ] [ 🔒 3 ]
        [ 🔄 4 ] [ 🔒 5 ]
        [ 💡 Подсказка ] [ ❌ Сброс всех ]
        [ 🎰 ОБМЕНЯТЬ КАРТЫ ]
    """
    builder = InlineKeyboardBuilder()

    # Кнопки выбора карт
    buttons = []
    for i in range(5):
        held = i in held_indices
        emoji = HOLD_BADGE if held else DROP_BADGE
        text = f"{emoji} {i+1}"
        buttons.append(types.InlineKeyboardButton(
            text=text, callback_data=f"poker_hold_{game_id}_{i}"
        ))

    # Раскладка: 3 + 2 (центрируется визуально)
    builder.row(*buttons[:3])
    builder.row(*buttons[3:])

    # Вспомогательные действия
    builder.row(
        types.InlineKeyboardButton(
            text="💡 Подсказка",
            callback_data=f"poker_hint_{game_id}"
        ),
        types.InlineKeyboardButton(
            text="❌ Сброс всех",
            callback_data=f"poker_reset_{game_id}"
        ),
    )

    # Главная кнопка действия
    if show_confirm:
        builder.row(types.InlineKeyboardButton(
            text="✅ ПОДТВЕРДИТЬ ОБМЕН",
            callback_data=f"poker_confirm_{game_id}"
        ))
        builder.row(types.InlineKeyboardButton(
            text="↩️ Назад",
            callback_data=f"poker_back_{game_id}"
        ))
    else:
        builder.row(types.InlineKeyboardButton(
            text="🎰 ОБМЕНЯТЬ КАРТЫ",
            callback_data=f"poker_draw_{game_id}"
        ))

    # Информационные кнопки внизу
    builder.row(
        types.InlineKeyboardButton(
            text="📖 Правила",
            callback_data=f"poker_help_{game_id}"
        ),
        types.InlineKeyboardButton(
            text="💰 Выплаты",
            callback_data=f"poker_payouts_{game_id}"
        ),
    )
    return builder.as_markup()


def get_close_keyboard(game_id: str) -> types.InlineKeyboardMarkup:
    """Клавиатура для попап-окон правил/выплат — кнопка «назад в игру»."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="↩️ Вернуться к игре",
        callback_data=f"poker_back_{game_id}"
    ))
    return builder.as_markup()


def get_replay_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    """Клавиатура после окончания игры — быстрое повторение ставки."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text=f"🔁 Сыграть ещё (ставка {bet:,})",
            callback_data=f"poker_replay_{bet}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="📖 Правила игры",
            callback_data="poker_help_static"
        ),
        types.InlineKeyboardButton(
            text="💰 Таблица выплат",
            callback_data="poker_payouts_static"
        ),
    )
    return builder.as_markup()


# ═══════════════════════════════════════════════════════════════════════════════
# 🚀 СТАРТ ИГРЫ
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("poker"))
async def cmd_poker(message: types.Message, state: FSMContext):
    """
    Точка входа в игру: /poker [ставка]
    Без аргументов покажет туториал.
    """
    # Если предыдущая игра «зависла» — сбрасываем
    if await state.get_state() == PokerState.playing.state:
        await state.clear()

    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    # ── Проверка бана ──
    if data.get('is_banned'):
        return

    # ── Проверка болезней (если игрок болен гонореей — нельзя) ──
    try:
        from diseases import get_active_diseases
        if 'gonorrhea' in await get_active_diseases(chat_id, user_id):
            return await message.answer(
                "🦠 <b>Гонорея</b>: Крупье брезгует раздавать тебе карты.\n"
                "Сначала вылечись — и возвращайся за стол!"
            )
    except ImportError:
        pass

    args = message.text.split()

    # ── Без аргументов: показываем туториал ──
    if len(args) < 2:
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="💰 Таблица выплат",
                callback_data="poker_payouts_static"
            )
        )
        return await message.answer(
            get_tutorial_text(),
            reply_markup=builder.as_markup()
        )

    # ── Парсинг ставки ──
    try:
        bet = int(args[1])
    except ValueError:
        return await message.answer(
            "❗ Ставка должна быть числом.\n"
            f"Пример: <code>/poker {MIN_BET}</code>"
        )

    if not (MIN_BET <= bet <= MAX_BET):
        return await message.answer(
            f"❗ Ставка должна быть в диапазоне\n"
            f"<b>{MIN_BET:,}</b> — <b>{MAX_BET:,}</b> сыроежек."
        )

    # ── Проверка баланса (с учётом овердрафта) ──
    if data.get('balance', 0) - bet < CREDIT_LIMIT:
        return await message.answer(
            f"💳 Ваш кредитный лимит ({CREDIT_LIMIT:,}) исчерпан.\n"
            "Пополните баланс, чтобы продолжить игру."
        )

    # ── Запрос подтверждения через casino_utils ──
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "poker", bet)


# ═══════════════════════════════════════════════════════════════════════════════
# ✅ ПОДТВЕРЖДЕНИЕ СТАВКИ → НАЧАЛО ИГРЫ
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cas_conf_poker_"))
async def process_poker_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Срабатывает после подтверждения ставки в общем UI казино."""
    try:
        bet = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        return await callback.answer("⚠️ Ошибка ставки.", show_alert=True)

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    await get_user_data(chat_id, user_id, full_name)  # синхронизируем кеш

    # ── Списываем ставку (атомарно, с лимитом) ──
    new_balance = await update_user_balance(
        chat_id, user_id, -bet, min_balance=CREDIT_LIMIT,
        action="VideoPoker Bet"
    )
    if new_balance is None:
        return await callback.answer(
            "💸 Недостаточно средств для ставки!", show_alert=True
        )

    try:
        await callback.message.delete()
    except Exception:
        pass

    # ── Создаём игровую сессию ──
    game_id = f"{chat_id}_{user_id}_{callback.message.message_id}"
    cards = deal_initial_hand()

    await state.set_state(PokerState.playing)
    await state.update_data(
        game_id=game_id,
        user_id=user_id,
        chat_id=chat_id,
        full_name=full_name,
        bet=bet,
        cards=cards,
        held_indices=[],
        original_cards=list(cards),  # сохраняем для статистики
    )

    # ── Анимация раздачи ──
    deal_msg = await callback.message.answer(
        "🎴 <b>Крупье тасует колоду...</b>"
    )
    await asyncio.sleep(0.4)
    try:
        await deal_msg.edit_text("🎴 <b>Раздача карт...</b>  🂠 🂠 🂠 🂠 🂠")
        await asyncio.sleep(0.4)
    except Exception:
        pass

    # ── Финальный экран ──
    text = get_game_screen(
        cards, [], full_name, bet,
        status_text=(
            "👆 <b>Ваш ход!</b> Нажмите номера карт, которые хотите\n"
            "оставить (🔒), и нажмите <b>«Обменять карты»</b>."
        ),
        show_hint=True,
    )
    try:
        await deal_msg.edit_text(
            text, reply_markup=get_poker_keyboard(game_id, [])
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=get_poker_keyboard(game_id, [])
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 🔒 УДЕРЖАНИЕ / СБРОС ОТДЕЛЬНОЙ КАРТЫ
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_hold_"))
async def process_poker_hold(callback: types.CallbackQuery, state: FSMContext):
    """Переключает статус Hold/Drop у выбранной карты."""
    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()

    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer("Это не ваша игра!", show_alert=True)

    try:
        idx = int(callback.data.split("_")[4])
    except (ValueError, IndexError):
        return await callback.answer()

    held_indices = list(game['held_indices'])

    if idx in held_indices:
        held_indices.remove(idx)
        answer_text = f"🔄 Карта {idx+1} будет сброшена."
    else:
        held_indices.append(idx)
        answer_text = f"🔒 Карта {idx+1} удержана."

    held_indices.sort()
    await state.update_data(held_indices=held_indices)

    # Краткий статус сверху: сколько удержано
    cnt = len(held_indices)
    if cnt == 0:
        status = "🔄 Все карты будут сброшены — полная замена руки."
    elif cnt == 5:
        status = "🔒 Все 5 карт удержаны — замены не будет."
    else:
        status = f"🔒 Удержано: <b>{cnt}/5</b>. Заменим <b>{5-cnt}</b> карт(ы)."

    text = get_game_screen(
        game['cards'], held_indices, game['full_name'], game['bet'],
        status_text=status, show_hint=False,
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=get_poker_keyboard(game['game_id'], held_indices)
        )
    except Exception:
        pass
    await callback.answer(answer_text)


# ═══════════════════════════════════════════════════════════════════════════════
# ❌ СБРОС ВСЕХ HOLD-МЕТОК
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_reset_"))
async def process_poker_reset(callback: types.CallbackQuery, state: FSMContext):
    """Сбрасывает все Hold-метки разом."""
    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()

    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer("Это не ваша игра!", show_alert=True)

    await state.update_data(held_indices=[])
    text = get_game_screen(
        game['cards'], [], game['full_name'], game['bet'],
        status_text="↺ Все метки сняты. Выберите карты заново.",
        show_hint=True,
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=get_poker_keyboard(game['game_id'], [])
        )
    except Exception:
        pass
    await callback.answer("❌ Все Hold-метки сняты.")


# ═══════════════════════════════════════════════════════════════════════════════
# 💡 ПОДСКАЗКА
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_hint_"))
async def process_poker_hint(callback: types.CallbackQuery, state: FSMContext):
    """Показывает совет на основе текущей руки."""
    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()

    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer("Это не ваша игра!", show_alert=True)

    hint = get_smart_hint(game['cards'])
    text = get_game_screen(
        game['cards'], game['held_indices'], game['full_name'], game['bet'],
        status_text=hint, show_hint=True,
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_poker_keyboard(game['game_id'], game['held_indices'])
        )
    except Exception:
        pass
    await callback.answer("💡 Подсказка от крупье!")


# ═══════════════════════════════════════════════════════════════════════════════
# 📖 ПРАВИЛА / 💰 ВЫПЛАТЫ (попапы)
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_help_"))
async def process_poker_help(callback: types.CallbackQuery, state: FSMContext):
    """Показывает правила игры, не теряя состояние."""
    parts = callback.data.split("_")
    if len(parts) >= 3 and parts[2] == "static":
        return await callback.message.answer(get_tutorial_text())

    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()
    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer()

    try:
        await callback.message.edit_text(
            get_tutorial_text(),
            reply_markup=get_close_keyboard(game['game_id'])
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("poker_payouts_"))
async def process_poker_payouts(callback: types.CallbackQuery, state: FSMContext):
    """Показывает таблицу выплат."""
    parts = callback.data.split("_")
    if len(parts) >= 3 and parts[2] == "static":
        return await callback.message.answer(get_payout_table_text())

    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()
    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer()

    try:
        await callback.message.edit_text(
            get_payout_table_text(),
            reply_markup=get_close_keyboard(game['game_id'])
        )
    except Exception:
        pass
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# ↩️ ВОЗВРАТ ИЗ ПОПАПА К ИГРЕ
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_back_"))
async def process_poker_back(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает игрока на основной экран игры."""
    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()
    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer()

    text = get_game_screen(
        game['cards'], game['held_indices'], game['full_name'], game['bet'],
        status_text="🎯 Продолжайте игру — выберите карты для удержания.",
        show_hint=True,
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_poker_keyboard(game['game_id'], game['held_indices'])
        )
    except Exception:
        pass
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# 🎰 ОБМЕН КАРТ И ПОДВЕДЕНИЕ ИТОГОВ
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_draw_"))
async def process_poker_draw(callback: types.CallbackQuery, state: FSMContext):
    """
    Главный финал игры: меняем неудержанные карты, оцениваем руку,
    начисляем выигрыш и показываем красивый финальный экран.
    """
    if await state.get_state() != PokerState.playing.state:
        return await callback.answer()

    game = await state.get_data()
    if callback.from_user.id != game['user_id']:
        return await callback.answer("Это не ваша игра!", show_alert=True)

    chat_id, user_id = game['chat_id'], game['user_id']
    bet = game['bet']
    held_indices = game['held_indices']
    full_name = game['full_name']

    # ── Анимация замены ──
    if len(held_indices) < 5:
        try:
            await callback.message.edit_text(
                "🎴 <b>Крупье меняет карты...</b>\n"
                + "  ".join(
                    HOLD_BADGE if i in held_indices else "🂠"
                    for i in range(5)
                )
            )
            await asyncio.sleep(0.5)
        except Exception:
            pass

    # ── Замена и оценка ──
    cards = redraw_cards(game['cards'], held_indices)
    combination = evaluate_hand(cards)
    multiplier = PAYOUT_TABLE.get(combination, 0)
    highlight = get_held_card_indices_by_combo(cards, combination)

    # ── Финансы ──
    if multiplier > 0:
        win_amount = bet * multiplier
        await update_user_balance(
            chat_id, user_id, win_amount, action="VideoPoker Win"
        )
    else:
        win_amount = 0

    # ── Статистика ──
    stats = update_stats(user_id, combination, win_amount)

    # ── Формируем красивый результат ──
    name, descr = COMBINATION_INFO.get(combination, ("Без выигрыша", ""))

    if multiplier > 0:
        # Победа
        header = f"🎉 <b>ПОБЕДА!</b> 🎉"
        result = (
            f"\n{header}\n"
            f"{SEPARATOR_LINE}\n"
            f"🏆 Комбинация: <b>{name}</b>\n"
            f"📋 <i>{descr}</i>\n"
            f"✖️ Множитель: <b>x{multiplier}</b>\n"
            f"💰 Выигрыш: <b>+{win_amount:,}</b> сыроежек!\n"
        )
        # Особый эффект для крупных побед
        if multiplier >= 25:
            result += f"🎆🎆🎆 <b>МЕГА-ВЫИГРЫШ!</b> 🎆🎆🎆\n"
    else:
        # Проигрыш
        header = "💔 <b>Не повезло...</b>"
        result = (
            f"\n{header}\n"
            f"{SEPARATOR_LINE}\n"
            f"🃏 Итоговая рука: <b>{name}</b>\n"
            f"📋 <i>{descr}</i>\n"
            f"💸 Потеряно: <b>-{bet:,}</b> сыроежек\n"
            f"🍀 Не сдавайтесь — удача рядом!\n"
        )

    # ── Сборка финального текста ──
    final_text = (
        f"🎰 <b>ВИДЕОПОКЕР</b> · <i>Финал партии</i> 🎰\n"
        f"{DOUBLE_LINE}\n"
        f"👤 <b>Игрок:</b> {full_name}\n"
        f"💰 <b>Ставка:</b> {bet:,} сыр.\n"
        f"{SEPARATOR_LINE}\n"
        f"{render_card_list(cards, held_indices, highlight)}\n"
        f"{result}"
        f"{get_stats_block(user_id)}"
    )

    # ── Инвалидация кеша баланса ──
    invalidate_user_cache(chat_id, user_id)

    try:
        await callback.message.edit_text(
            final_text, reply_markup=get_replay_keyboard(bet)
        )
    except Exception:
        await callback.message.answer(
            final_text, reply_markup=get_replay_keyboard(bet)
        )

    await state.clear()
    await callback.answer(
        f"🏆 +{win_amount:,} сыр." if win_amount > 0 else "💔 Не в этот раз...",
        show_alert=False
    )

    # Автоудаление через AUTO_DELETE_DELAY секунд
    asyncio.create_task(schedule_delete(callback.message, AUTO_DELETE_DELAY))


# ═══════════════════════════════════════════════════════════════════════════════
# 🔁 ПОВТОР ИГРЫ
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_replay_"))
async def process_poker_replay(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый рестарт с той же ставкой."""
    try:
        bet = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        return await callback.answer()

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get('is_banned'):
        return await callback.answer("⛔ Вы заблокированы.", show_alert=True)

    if data.get('balance', 0) - bet < CREDIT_LIMIT:
        return await callback.answer(
            "💳 Недостаточно средств для повтора.",
            show_alert=True
        )

    # Имитируем callback подтверждения через casino_utils
    try:
        await callback.message.delete()
    except Exception:
        pass
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(callback.message, "poker", bet, user_id=user_id)
    await callback.answer("🔁 Готовим новую раздачу...")


# ═══════════════════════════════════════════════════════════════════════════════
# 🛡️ ОБРАБОТЧИК НЕИЗВЕСТНЫХ КОЛЛБЭКОВ POKER_*
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("poker_"))
async def process_poker_unknown(callback: types.CallbackQuery):
    """
    Перехватывает устаревшие/неизвестные коллбэки покера
    (например, после рестарта бота).
    """
    await callback.answer(
        "⚠️ Эта игра устарела или завершена.\n"
        "Начните новую: /poker [ставка]",
        show_alert=True
    )


# ═══════════════════════════════════════════════════════════════════════════════
#                              🎰 КОНЕЦ ФАЙЛА 🎰
# ═══════════════════════════════════════════════════════════════════════════════