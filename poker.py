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


class PokerState(StatesGroup):
    playing = State()
    confirming = State()


MIN_BET = 100
MAX_BET = 50_000_000
CREDIT_LIMIT = -5000
AUTO_DELETE_DELAY = 60
GAME_TIMEOUT = 300
HAND_SIZE = 5
HIGH_CARD_VALUE = 11
MEGA_WIN_MULTIPLIER = 25


PAY_ROYAL_FLUSH = 250
PAY_STRAIGHT_FLUSH = 50
PAY_FOUR_OF_A_KIND = 25
PAY_FULL_HOUSE = 9
PAY_FLUSH = 6
PAY_STRAIGHT = 4
PAY_THREE_OF_A_KIND = 3
PAY_TWO_PAIR = 2
PAY_JACKS_OR_BETTER = 1
PAY_NOTHING = 0


PAYOUT_TABLE = {
    "Royal Flush": PAY_ROYAL_FLUSH,
    "Straight Flush": PAY_STRAIGHT_FLUSH,
    "Four of a Kind": PAY_FOUR_OF_A_KIND,
    "Full House": PAY_FULL_HOUSE,
    "Flush": PAY_FLUSH,
    "Straight": PAY_STRAIGHT,
    "Three of a Kind": PAY_THREE_OF_A_KIND,
    "Two Pair": PAY_TWO_PAIR,
    "Jacks or Better": PAY_JACKS_OR_BETTER,
}


COMBO_NAMES = {
    "Royal Flush": "🌟 Роял Флеш",
    "Straight Flush": "💎 Стрит-флеш",
    "Four of a Kind": "🔥 Каре",
    "Full House": "🏠 Фулл-хаус",
    "Flush": "🌊 Флеш",
    "Straight": "➡️ Стрит",
    "Three of a Kind": "🎯 Сет (тройка)",
    "Two Pair": "👬 Две пары",
    "Jacks or Better": "🤴 Пара J/Q/K/A",
    "Nothing": "❌ Нет комбинации",
}


COMBO_DESCRIPTIONS = {
    "Royal Flush": "10, J, Q, K, A одной масти — максимум!",
    "Straight Flush": "5 карт по порядку одной масти",
    "Four of a Kind": "4 карты одного ранга (4 туза и т.п.)",
    "Full House": "Тройка + пара (например, 3 дамы + 2 семёрки)",
    "Flush": "Любые 5 карт одной масти",
    "Straight": "5 карт по порядку любых мастей",
    "Three of a Kind": "3 карты одного ранга",
    "Two Pair": "Две разные пары карт",
    "Jacks or Better": "Пара валетов, дам, королей или тузов",
    "Nothing": "Соберите хотя бы пару валетов!",
}


RANK_VALUES = {
    '2': 2,
    '3': 3,
    '4': 4,
    '5': 5,
    '6': 6,
    '7': 7,
    '8': 8,
    '9': 9,
    '10': 10,
    'J': 11,
    'Q': 12,
    'K': 13,
    'A': 14,
}


HOLD_BADGE = "🔒"
DROP_BADGE = "🔄"
CARD_BACK = "🂠"
WIN_BADGE = "🏆"
WIN_SPARKLE = "✨"
HOLD_PIN = "📌"
SEPARATOR_LINE = "━" * 27
DOUBLE_LINE = "═" * 27


SUIT_EMOJI = {
    "♠": "♠️",
    "♣": "♣️",
    "♥": "♥️",
    "♦": "♦️",
    "♠️": "♠️",
    "♣️": "♣️",
    "♥️": "♥️",
    "♦️": "♦️",
}


user_stats: dict[int, dict] = {}


def make_empty_stats() -> dict:
    return {
        "games": 0,
        "wins": 0,
        "best": "Nothing",
        "biggest_win": 0,
        "total_won": 0,
    }


def get_user_stats(user_id: int) -> dict:
    if user_id not in user_stats:
        user_stats[user_id] = make_empty_stats()
    return user_stats[user_id]


def is_better_combo(new_combo: str, old_combo: str) -> bool:
    new_rank = PAYOUT_TABLE.get(new_combo, 0)
    old_rank = PAYOUT_TABLE.get(old_combo, 0)
    return new_rank > old_rank


def update_stats(user_id: int, combination: str, win_amount: int) -> dict:
    stats = get_user_stats(user_id)
    stats["games"] += 1
    if win_amount > 0:
        stats["wins"] += 1
        stats["total_won"] += win_amount
        if win_amount > stats["biggest_win"]:
            stats["biggest_win"] = win_amount
    if is_better_combo(combination, stats["best"]):
        stats["best"] = combination
    return stats


def calc_win_rate(stats: dict) -> float:
    if stats["games"] == 0:
        return 0.0
    return (stats["wins"] / stats["games"]) * 100


def get_stats_block(user_id: int) -> str:
    stats = user_stats.get(user_id)
    if not stats or stats["games"] == 0:
        return ""
    win_rate = calc_win_rate(stats)
    best_name = COMBO_NAMES.get(stats["best"], "—")
    lines = []
    lines.append("\n📊 <b>Ваша статистика:</b>")
    lines.append(f"  • Игр сыграно: <b>{stats['games']}</b>")
    lines.append(f"  • Побед: <b>{stats['wins']}</b> ({win_rate:.0f}%)")
    lines.append(f"  • Лучшая рука: {best_name}")
    lines.append(f"  • Макс. выигрыш: <b>{stats['biggest_win']:,}</b> сыр.")
    return "\n".join(lines) + "\n"


_rng = secrets.SystemRandom()


def make_random_card() -> dict:
    return {
        'rank': _rng.choice(RANKS),
        'suit': _rng.choice(SUITS),
    }


def is_card_in_list(card: dict, cards: list) -> bool:
    for existing in cards:
        if existing['rank'] == card['rank'] and existing['suit'] == card['suit']:
            return True
    return False


def get_unique_card(exclude_cards: list) -> dict:
    while True:
        card = make_random_card()
        if not is_card_in_list(card, exclude_cards):
            return card


def deal_initial_hand() -> list[dict]:
    hand: list[dict] = []
    for _ in range(HAND_SIZE):
        hand.append(get_unique_card(hand))
    return hand


def redraw_cards(cards: list[dict], held_indices: list[int]) -> list[dict]:
    new_hand = list(cards)
    for i in range(HAND_SIZE):
        if i not in held_indices:
            new_hand[i] = get_unique_card(new_hand)
    return new_hand


def get_suit_emoji(raw_suit: str) -> str:
    return SUIT_EMOJI.get(raw_suit, raw_suit)


def format_card(card: dict) -> str:
    suit = get_suit_emoji(card['suit'])
    return f"{card['rank']}{suit}"


def get_card_ranks(cards: list[dict]) -> list[str]:
    return [c['rank'] for c in cards]


def get_card_suits(cards: list[dict]) -> list[str]:
    return [c['suit'] for c in cards]


def get_rank_values_sorted(cards: list[dict]) -> list[int]:
    return sorted(RANK_VALUES[r] for r in get_card_ranks(cards))


def count_ranks(cards: list[dict]) -> Counter:
    return Counter(get_card_ranks(cards))


def count_suits(cards: list[dict]) -> Counter:
    return Counter(get_card_suits(cards))


def is_flush(cards: list[dict]) -> bool:
    return len(set(get_card_suits(cards))) == 1


def is_normal_straight(values: list[int]) -> bool:
    if len(set(values)) != HAND_SIZE:
        return False
    return values[-1] - values[0] == 4


def is_wheel_straight(values: list[int]) -> bool:
    return values == [2, 3, 4, 5, 14]


def is_straight(values: list[int]) -> bool:
    if is_normal_straight(values):
        return True
    if is_wheel_straight(values):
        return True
    return False


def is_royal(values: list[int]) -> bool:
    if is_wheel_straight(values):
        return False
    return values[0] == 10 and values[-1] == 14


def find_pair_rank(rank_counts: Counter) -> Optional[str]:
    for rank, count in rank_counts.items():
        if count == 2:
            return rank
    return None


def is_high_pair(rank: str) -> bool:
    return RANK_VALUES[rank] >= HIGH_CARD_VALUE


def evaluate_hand(cards: list[dict]) -> str:
    if len(cards) != HAND_SIZE:
        return "Nothing"

    rank_counts = count_ranks(cards)
    counts = sorted(rank_counts.values(), reverse=True)
    values = get_rank_values_sorted(cards)
    flush = is_flush(cards)
    straight = is_straight(values)

    if flush and straight:
        if is_royal(values):
            return "Royal Flush"
        return "Straight Flush"

    if counts[0] == 4:
        return "Four of a Kind"

    if counts == [3, 2]:
        return "Full House"

    if flush:
        return "Flush"

    if straight:
        return "Straight"

    if counts[0] == 3:
        return "Three of a Kind"

    if counts[0] == 2 and counts[1] == 2:
        return "Two Pair"

    if counts[0] == 2:
        pair_rank = find_pair_rank(rank_counts)
        if pair_rank and is_high_pair(pair_rank):
            return "Jacks or Better"

    return "Nothing"


def get_payout_multiplier(combination: str) -> int:
    return PAYOUT_TABLE.get(combination, 0)


def calculate_win_amount(bet: int, combination: str) -> int:
    return bet * get_payout_multiplier(combination)


def get_all_card_indices() -> set[int]:
    return set(range(HAND_SIZE))


def get_indices_for_ranks(cards: list[dict], ranks: set[str]) -> set[int]:
    return {i for i, c in enumerate(cards) if c['rank'] in ranks}


def get_four_of_a_kind_ranks(rank_counts: Counter) -> set[str]:
    return {r for r, c in rank_counts.items() if c == 4}


def get_full_house_ranks(rank_counts: Counter) -> set[str]:
    return {r for r, c in rank_counts.items() if c >= 2}


def get_three_of_a_kind_ranks(rank_counts: Counter) -> set[str]:
    return {r for r, c in rank_counts.items() if c == 3}


def get_pair_ranks(rank_counts: Counter) -> set[str]:
    return {r for r, c in rank_counts.items() if c == 2}


def get_high_pair_ranks(rank_counts: Counter) -> set[str]:
    return {r for r, c in rank_counts.items() if c == 2 and is_high_pair(r)}


def get_winning_card_indices(cards: list[dict], combo: str) -> set[int]:
    if combo == "Nothing":
        return set()

    if combo in ("Royal Flush", "Straight Flush", "Flush", "Straight"):
        return get_all_card_indices()

    rank_counts = count_ranks(cards)

    if combo == "Four of a Kind":
        target = get_four_of_a_kind_ranks(rank_counts)
    elif combo == "Full House":
        target = get_full_house_ranks(rank_counts)
    elif combo == "Three of a Kind":
        target = get_three_of_a_kind_ranks(rank_counts)
    elif combo == "Two Pair":
        target = get_pair_ranks(rank_counts)
    elif combo == "Jacks or Better":
        target = get_high_pair_ranks(rank_counts)
    else:
        target = set()

    return get_indices_for_ranks(cards, target)


def find_triple_rank(rank_counts: Counter) -> Optional[str]:
    for rank, count in rank_counts.items():
        if count == 3:
            return rank
    return None


def find_quad_rank(rank_counts: Counter) -> Optional[str]:
    for rank, count in rank_counts.items():
        if count == 4:
            return rank
    return None


def find_all_pairs(rank_counts: Counter) -> list[str]:
    return [r for r, c in rank_counts.items() if c == 2]


def get_high_card_indices(cards: list[dict]) -> list[int]:
    return [i for i, c in enumerate(cards) if RANK_VALUES[c['rank']] >= HIGH_CARD_VALUE]


def get_dominant_suit(suit_counts: Counter) -> tuple[str, int]:
    most_common = suit_counts.most_common(1)
    if not most_common:
        return ("", 0)
    return most_common[0]


def hint_already_winning(combo: str) -> Optional[str]:
    if combo == "Nothing":
        return None
    multiplier = get_payout_multiplier(combo)
    if multiplier >= PAY_FLUSH:
        name = COMBO_NAMES[combo]
        return f"💡 <b>Совет:</b> Уже есть {name}! Удержите все 5 карт."
    if combo in ("Four of a Kind", "Full House"):
        name = COMBO_NAMES[combo]
        return f"💡 <b>Совет:</b> Отличная рука — {name}! Держите всё."
    return None


def hint_three_of_a_kind(rank_counts: Counter) -> Optional[str]:
    triple = find_triple_rank(rank_counts)
    if triple is None:
        return None
    return f"💡 <b>Совет:</b> Держите тройку <b>{triple}</b> и тяните каре или фулл-хаус."


def hint_two_pairs(rank_counts: Counter) -> Optional[str]:
    pairs = find_all_pairs(rank_counts)
    if len(pairs) != 2:
        return None
    return "💡 <b>Совет:</b> Две пары! Держите обе и тяните фулл-хаус."


def hint_one_pair(rank_counts: Counter) -> Optional[str]:
    pairs = find_all_pairs(rank_counts)
    if len(pairs) != 1:
        return None
    pair_rank = pairs[0]
    if is_high_pair(pair_rank):
        return f"💡 <b>Совет:</b> Пара <b>{pair_rank}</b> — уже выплата 1:1. Держите и улучшайте."
    return f"💡 <b>Совет:</b> Маленькая пара <b>{pair_rank}</b>. Держите — есть шанс на сет."


def hint_flush_draw(suit_counts: Counter) -> Optional[str]:
    suit, count = get_dominant_suit(suit_counts)
    if count != 4:
        return None
    pretty_suit = get_suit_emoji(suit)
    return f"💡 <b>Совет:</b> 4 карты масти {pretty_suit} — держите их, есть шанс на флеш!"


def hint_high_cards(cards: list[dict]) -> Optional[str]:
    highs = get_high_card_indices(cards)
    if not highs:
        return None
    return "💡 <b>Совет:</b> Держите старшие карты (J/Q/K/A) — шанс на пару."


def hint_weak_hand() -> str:
    return "💡 <b>Совет:</b> Слабая рука. Сбросьте все 5 карт и попробуйте удачу!"


def get_smart_hint(cards: list[dict]) -> str:
    current = evaluate_hand(cards)
    rank_counts = count_ranks(cards)
    suit_counts = count_suits(cards)

    hint = hint_already_winning(current)
    if hint:
        return hint

    hint = hint_three_of_a_kind(rank_counts)
    if hint:
        return hint

    hint = hint_two_pairs(rank_counts)
    if hint:
        return hint

    hint = hint_one_pair(rank_counts)
    if hint:
        return hint

    hint = hint_flush_draw(suit_counts)
    if hint:
        return hint

    hint = hint_high_cards(cards)
    if hint:
        return hint

    return hint_weak_hand()


def render_card_visual_row(face: str, is_win: bool, is_held: bool) -> tuple[str, str, str]:
    if is_win:
        return (WIN_SPARKLE, f"<b>{face}</b>", WIN_BADGE)
    if is_held:
        return (HOLD_PIN, f"<b>{face}</b>", HOLD_BADGE)
    return ("· ", f"<i>{face}</i>", DROP_BADGE)


def render_card_row(
    cards: list[dict],
    held_indices: list[int],
    highlight: Optional[set[int]] = None,
) -> str:
    highlight = highlight or set()
    line_top: list[str] = []
    line_mid: list[str] = []
    line_bot: list[str] = []
    for i, c in enumerate(cards):
        is_held = i in held_indices
        is_win = i in highlight
        face = format_card(c)
        top, mid, bot = render_card_visual_row(face, is_win, is_held)
        line_top.append(top)
        line_mid.append(mid)
        line_bot.append(bot)
    number_line = "  ".join(f"<code>{i + 1}</code>" for i in range(HAND_SIZE))
    return (
        "  ".join(line_top) + "\n"
        + "  ".join(line_mid) + "\n"
        + number_line + "\n"
        + "  ".join(line_bot)
    )


def get_card_status_label(i: int, held_indices: list[int], highlight: set[int]) -> tuple[str, str]:
    if i in highlight:
        return (WIN_BADGE, "<b>ВЫИГРЫШНАЯ</b>")
    if i in held_indices:
        return (HOLD_BADGE, "<b>Удержана</b>")
    return (DROP_BADGE, "<i>Будет сброшена</i>")


def render_single_card_line(
    index: int,
    card: dict,
    held_indices: list[int],
    highlight: set[int],
) -> str:
    face = format_card(card)
    badge, label = get_card_status_label(index, held_indices, highlight)
    return f"  {badge}  <code>{index + 1}.</code> <b>{face}</b> — {label}"


def render_card_list(
    cards: list[dict],
    held_indices: list[int],
    highlight: Optional[set[int]] = None,
) -> str:
    highlight = highlight or set()
    lines = []
    for i, c in enumerate(cards):
        lines.append(render_single_card_line(i, c, held_indices, highlight))
    return "\n".join(lines)


def get_potential_combo_text(cards: list[dict]) -> str:
    combo = evaluate_hand(cards)
    if combo == "Nothing":
        return ""
    multiplier = get_payout_multiplier(combo)
    name = COMBO_NAMES[combo]
    return f"\n🎲 <b>Сейчас на руках:</b> {name} (x{multiplier})"


def get_game_header(user_name: str, bet: int) -> str:
    lines = []
    lines.append("🎰 <b>ВИДЕОПОКЕР</b> · <i>Jacks or Better</i> 🎰")
    lines.append(DOUBLE_LINE)
    lines.append(f"👤 <b>Игрок:</b> {user_name}")
    lines.append(f"💰 <b>Ставка:</b> {bet:,} сыр.")
    lines.append(SEPARATOR_LINE)
    return "\n".join(lines)


def get_finale_header(user_name: str, bet: int) -> str:
    lines = []
    lines.append("🎰 <b>ВИДЕОПОКЕР</b> · <i>Финал партии</i> 🎰")
    lines.append(DOUBLE_LINE)
    lines.append(f"👤 <b>Игрок:</b> {user_name}")
    lines.append(f"💰 <b>Ставка:</b> {bet:,} сыр.")
    lines.append(SEPARATOR_LINE)
    return "\n".join(lines)


def get_game_screen(
    cards: list[dict],
    held_indices: list[int],
    user_name: str,
    bet: int,
    status_text: str,
    *,
    highlight: Optional[set[int]] = None,
    show_hint: bool = False,
) -> str:
    if highlight:
        potential = ""
    else:
        potential = get_potential_combo_text(cards) if show_hint else ""
    hint = "\n" + get_smart_hint(cards) if show_hint else ""
    body = render_card_list(cards, held_indices, highlight)
    header = get_game_header(user_name, bet)
    return (
        f"{header}\n"
        f"{body}\n"
        f"{potential}"
        f"{SEPARATOR_LINE}\n"
        f"{status_text}"
        f"{hint}"
    )


def format_payout_line(combo: str, multiplier: int) -> str:
    name = COMBO_NAMES[combo]
    descr = COMBO_DESCRIPTIONS[combo]
    return f"<b>x{multiplier:<3}</b> · {name}\n      <i>{descr}</i>"


def get_payout_table_text() -> str:
    lines = []
    lines.append("💰 <b>ТАБЛИЦА ВЫПЛАТ</b>")
    lines.append(DOUBLE_LINE)
    for combo, multiplier in PAYOUT_TABLE.items():
        lines.append(format_payout_line(combo, multiplier))
    lines.append(DOUBLE_LINE)
    lines.append("ℹ️ Множитель умножается на размер вашей ставки.")
    return "\n".join(lines)


def get_tutorial_intro() -> str:
    lines = []
    lines.append("📖 <b>КАК ИГРАТЬ В ВИДЕОПОКЕР</b>")
    lines.append(DOUBLE_LINE)
    lines.append("🎯 <b>Цель:</b> собрать одну из выигрышных комбинаций.")
    return "\n".join(lines)


def get_tutorial_rules() -> str:
    lines = []
    lines.append("🎮 <b>Правила игры:</b>")
    lines.append("  <b>1.</b> Вы делаете ставку командой <code>/poker 100</code>.")
    lines.append("  <b>2.</b> Получаете 5 случайных карт.")
    lines.append("  <b>3.</b> Решаете, какие оставить (🔒 Hold), нажав на номер.")
    lines.append("  <b>4.</b> Нажимаете <b>«Обменять»</b> — несохранённые карты")
    lines.append("       заменяются новыми.")
    lines.append("  <b>5.</b> Если итоговая рука — выигрышная комбинация,")
    lines.append("       вы получаете выплату по таблице.")
    return "\n".join(lines)


def get_tutorial_tips() -> str:
    lines = []
    lines.append("💡 <b>Подсказки:</b>")
    lines.append("  • Минимальная выплата — за пару валетов и выше.")
    lines.append("  • Не сбрасывайте уже готовые комбинации!")
    lines.append("  • Если есть 4 карты одной масти — стремитесь к флешу.")
    lines.append("  • Если 4 карты подряд — пытайтесь поймать стрит.")
    lines.append("  • Кнопка <b>«Сбросить все»</b> снимает все Hold-метки.")
    return "\n".join(lines)


def get_tutorial_bet_limits() -> str:
    lines = []
    lines.append("💰 <b>Ставки:</b>")
    lines.append(f"  • Минимальная: <b>{MIN_BET:,}</b> сыр.")
    lines.append(f"  • Максимальная: <b>{MAX_BET:,}</b> сыр.")
    return "\n".join(lines)


def get_tutorial_text() -> str:
    parts = []
    parts.append(get_tutorial_intro())
    parts.append("")
    parts.append(get_tutorial_rules())
    parts.append("")
    parts.append(get_tutorial_tips())
    parts.append("")
    parts.append(SEPARATOR_LINE)
    parts.append(get_tutorial_bet_limits())
    parts.append("")
    parts.append("📊 Нажмите кнопку ниже, чтобы увидеть таблицу выплат.")
    return "\n".join(parts)


def make_card_button(game_id: str, index: int, held: bool) -> types.InlineKeyboardButton:
    emoji = HOLD_BADGE if held else DROP_BADGE
    text = f"{emoji} {index + 1}"
    callback = f"poker_hold_{game_id}_{index}"
    return types.InlineKeyboardButton(text=text, callback_data=callback)


def make_hint_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="💡 Подсказка",
        callback_data=f"poker_hint_{game_id}",
    )


def make_reset_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="❌ Сброс всех",
        callback_data=f"poker_reset_{game_id}",
    )


def make_confirm_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="✅ ПОДТВЕРДИТЬ ОБМЕН",
        callback_data=f"poker_confirm_{game_id}",
    )


def make_back_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="↩️ Назад",
        callback_data=f"poker_back_{game_id}",
    )


def make_draw_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="🎰 ОБМЕНЯТЬ КАРТЫ",
        callback_data=f"poker_draw_{game_id}",
    )


def make_help_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="📖 Правила",
        callback_data=f"poker_help_{game_id}",
    )


def make_payouts_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="💰 Выплаты",
        callback_data=f"poker_payouts_{game_id}",
    )


def make_back_to_game_button(game_id: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="↩️ Вернуться к игре",
        callback_data=f"poker_back_{game_id}",
    )


def make_replay_button(bet: int) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text=f"🔁 Сыграть ещё (ставка {bet:,})",
        callback_data=f"poker_replay_{bet}",
    )


def make_static_help_button() -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="📖 Правила игры",
        callback_data="poker_help_static",
    )


def make_static_payouts_button() -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text="💰 Таблица выплат",
        callback_data="poker_payouts_static",
    )


def get_poker_keyboard(
    game_id: str,
    held_indices: list[int],
    show_confirm: bool = False,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    card_buttons = []
    for i in range(HAND_SIZE):
        held = i in held_indices
        card_buttons.append(make_card_button(game_id, i, held))

    builder.row(*card_buttons[:3])
    builder.row(*card_buttons[3:])
    builder.row(make_hint_button(game_id), make_reset_button(game_id))

    if show_confirm:
        builder.row(make_confirm_button(game_id))
        builder.row(make_back_button(game_id))
    else:
        builder.row(make_draw_button(game_id))

    builder.row(make_help_button(game_id), make_payouts_button(game_id))
    return builder.as_markup()


def get_close_keyboard(game_id: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(make_back_to_game_button(game_id))
    return builder.as_markup()


def get_replay_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(make_replay_button(bet))
    builder.row(make_static_help_button(), make_static_payouts_button())
    return builder.as_markup()


def get_tutorial_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(make_static_payouts_button())
    return builder.as_markup()


def build_game_id(chat_id: int, user_id: int, message_id: int) -> str:
    return f"{chat_id}_{user_id}_{message_id}"


def parse_bet_from_args(args: list[str]) -> Optional[int]:
    if len(args) < 2:
        return None
    try:
        return int(args[1])
    except ValueError:
        return None


def is_valid_bet(bet: int) -> bool:
    return MIN_BET <= bet <= MAX_BET


def has_enough_balance(balance: int, bet: int) -> bool:
    return balance - bet >= CREDIT_LIMIT


def get_status_text_for_hold(held_count: int) -> str:
    if held_count == 0:
        return "🔄 Все карты будут сброшены — полная замена руки."
    if held_count == HAND_SIZE:
        return "🔒 Все 5 карт удержаны — замены не будет."
    return f"🔒 Удержано: <b>{held_count}/5</b>. Заменим <b>{HAND_SIZE - held_count}</b> карт(ы)."


def get_hold_answer_text(index: int, is_held_now: bool) -> str:
    if is_held_now:
        return f"🔒 Карта {index + 1} удержана."
    return f"🔄 Карта {index + 1} будет сброшена."


def toggle_held_index(held_indices: list[int], index: int) -> tuple[list[int], bool]:
    new_list = list(held_indices)
    if index in new_list:
        new_list.remove(index)
        is_held_now = False
    else:
        new_list.append(index)
        is_held_now = True
    new_list.sort()
    return new_list, is_held_now


def parse_callback_index(callback_data: str, position: int) -> Optional[int]:
    try:
        return int(callback_data.split("_")[position])
    except (ValueError, IndexError):
        return None


def is_static_callback(callback_data: str) -> bool:
    parts = callback_data.split("_")
    return len(parts) >= 3 and parts[2] == "static"


async def safe_edit_message(message: types.Message, text: str, reply_markup=None) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception as exc:
        logger.debug("edit_text failed: %s", exc)
        return False


async def safe_delete_message(message: types.Message) -> bool:
    try:
        await message.delete()
        return True
    except Exception as exc:
        logger.debug("delete failed: %s", exc)
        return False


async def safe_send_message(message: types.Message, text: str, reply_markup=None) -> Optional[types.Message]:
    try:
        return await message.answer(text, reply_markup=reply_markup)
    except Exception as exc:
        logger.debug("answer failed: %s", exc)
        return None


async def check_user_is_banned(chat_id: int, user_id: int, full_name: str) -> bool:
    data = await get_user_data(chat_id, user_id, full_name)
    return bool(data.get('is_banned'))


async def check_user_has_gonorrhea(chat_id: int, user_id: int) -> bool:
    try:
        from diseases import get_active_diseases
        active = await get_active_diseases(chat_id, user_id)
        return 'gonorrhea' in active
    except ImportError:
        return False


def get_gonorrhea_message() -> str:
    return (
        "🦠 <b>Гонорея</b>: Крупье брезгует раздавать тебе карты.\n"
        "Сначала вылечись — и возвращайся за стол!"
    )


def get_invalid_bet_format_message() -> str:
    return (
        "❗ Ставка должна быть числом.\n"
        f"Пример: <code>/poker {MIN_BET}</code>"
    )


def get_invalid_bet_range_message() -> str:
    return (
        f"❗ Ставка должна быть в диапазоне\n"
        f"<b>{MIN_BET:,}</b> — <b>{MAX_BET:,}</b> сыроежек."
    )


def get_insufficient_balance_message() -> str:
    return (
        f"💳 Ваш кредитный лимит ({CREDIT_LIMIT:,}) исчерпан.\n"
        "Пополните баланс, чтобы продолжить игру."
    )


def get_shuffle_message() -> str:
    return "🎴 <b>Крупье тасует колоду...</b>"


def get_dealing_message() -> str:
    return "🎴 <b>Раздача карт...</b>  🂠 🂠 🂠 🂠 🂠"


def get_changing_cards_message(held_indices: list[int]) -> str:
    visual = []
    for i in range(HAND_SIZE):
        if i in held_indices:
            visual.append(HOLD_BADGE)
        else:
            visual.append(CARD_BACK)
    return "🎴 <b>Крупье меняет карты...</b>\n" + "  ".join(visual)


def get_initial_status_text() -> str:
    return (
        "👆 <b>Ваш ход!</b> Нажмите номера карт, которые хотите\n"
        "оставить (🔒), и нажмите <b>«Обменять карты»</b>."
    )


def get_back_to_game_status() -> str:
    return "🎯 Продолжайте игру — выберите карты для удержания."


def get_reset_status() -> str:
    return "↺ Все метки сняты. Выберите карты заново."


def get_win_header() -> str:
    return "🎉 <b>ПОБЕДА!</b> 🎉"


def get_loss_header() -> str:
    return "💔 <b>Не повезло...</b>"


def format_win_result(combo: str, multiplier: int, win_amount: int) -> str:
    name = COMBO_NAMES.get(combo, "Без выигрыша")
    descr = COMBO_DESCRIPTIONS.get(combo, "")
    lines = []
    lines.append("")
    lines.append(get_win_header())
    lines.append(SEPARATOR_LINE)
    lines.append(f"🏆 Комбинация: <b>{name}</b>")
    lines.append(f"📋 <i>{descr}</i>")
    lines.append(f"✖️ Множитель: <b>x{multiplier}</b>")
    lines.append(f"💰 Выигрыш: <b>+{win_amount:,}</b> сыроежек!")
    if multiplier >= MEGA_WIN_MULTIPLIER:
        lines.append("🎆🎆🎆 <b>МЕГА-ВЫИГРЫШ!</b> 🎆🎆🎆")
    return "\n".join(lines) + "\n"


def format_loss_result(combo: str, bet: int) -> str:
    name = COMBO_NAMES.get(combo, "Без выигрыша")
    descr = COMBO_DESCRIPTIONS.get(combo, "")
    lines = []
    lines.append("")
    lines.append(get_loss_header())
    lines.append(SEPARATOR_LINE)
    lines.append(f"🃏 Итоговая рука: <b>{name}</b>")
    lines.append(f"📋 <i>{descr}</i>")
    lines.append(f"💸 Потеряно: <b>-{bet:,}</b> сыроежек")
    lines.append("🍀 Не сдавайтесь — удача рядом!")
    return "\n".join(lines) + "\n"


def format_game_result(combo: str, multiplier: int, win_amount: int, bet: int) -> str:
    if multiplier > 0:
        return format_win_result(combo, multiplier, win_amount)
    return format_loss_result(combo, bet)


def build_final_text(
    cards: list[dict],
    held_indices: list[int],
    highlight: set[int],
    full_name: str,
    bet: int,
    result_text: str,
    user_id: int,
) -> str:
    header = get_finale_header(full_name, bet)
    body = render_card_list(cards, held_indices, highlight)
    stats = get_stats_block(user_id)
    return f"{header}\n{body}\n{result_text}{stats}"


def get_final_answer_text(win_amount: int) -> str:
    if win_amount > 0:
        return f"🏆 +{win_amount:,} сыр."
    return "💔 Не в этот раз..."


async def play_deal_animation(message: types.Message) -> types.Message:
    deal_msg = await message.answer(get_shuffle_message())
    await asyncio.sleep(0.4)
    await safe_edit_message(deal_msg, get_dealing_message())
    await asyncio.sleep(0.4)
    return deal_msg


async def play_change_cards_animation(message: types.Message, held_indices: list[int]) -> None:
    if len(held_indices) >= HAND_SIZE:
        return
    await safe_edit_message(message, get_changing_cards_message(held_indices))
    await asyncio.sleep(0.5)


async def is_player_match(callback: types.CallbackQuery, state: FSMContext) -> tuple[bool, dict]:
    game = await state.get_data()
    if not game:
        return False, {}
    if callback.from_user.id != game.get('user_id'):
        return False, game
    return True, game


async def verify_active_game(callback: types.CallbackQuery, state: FSMContext) -> Optional[dict]:
    if await state.get_state() != PokerState.playing.state:
        await callback.answer()
        return None
    matches, game = await is_player_match(callback, state)
    if not matches:
        if game:
            await callback.answer("Это не ваша игра!", show_alert=True)
        else:
            await callback.answer()
        return None
    return game


@router.message(Command("poker"))
async def cmd_poker(message: types.Message, state: FSMContext):
    if await state.get_state() == PokerState.playing.state:
        await state.clear()

    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    if await check_user_is_banned(chat_id, user_id, full_name):
        return

    if await check_user_has_gonorrhea(chat_id, user_id):
        return await message.answer(get_gonorrhea_message())

    args = message.text.split()
    bet = parse_bet_from_args(args)

    if bet is None and len(args) < 2:
        return await message.answer(
            get_tutorial_text(),
            reply_markup=get_tutorial_keyboard(),
        )

    if bet is None:
        return await message.answer(get_invalid_bet_format_message())

    if not is_valid_bet(bet):
        return await message.answer(get_invalid_bet_range_message())

    user_data = await get_user_data(chat_id, user_id, full_name)
    balance = user_data.get('balance', 0)
    if not has_enough_balance(balance, bet):
        return await message.answer(get_insufficient_balance_message())

    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "poker", bet)


@router.callback_query(F.data.startswith("cas_conf_poker_"))
async def process_poker_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        bet = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        return await callback.answer("⚠️ Ошибка ставки.", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    message_id = callback.message.message_id
    
    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        return await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        
    try:
        full_name = escape_html(callback.from_user.full_name)
        await get_user_data(chat_id, user_id, full_name)
    
        new_balance = await update_user_balance(
            chat_id,
            user_id,
            -bet,
            min_balance=CREDIT_LIMIT,
            action="VideoPoker Bet",
        )
        if new_balance is None:
            return await callback.answer(
                "💸 Недостаточно средств для ставки!",
                show_alert=True,
            )
    
        await safe_delete_message(callback.message)
    
        game_id = build_game_id(chat_id, user_id, callback.message.message_id)
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
            original_cards=list(cards),
        )
    
        deal_msg = await play_deal_animation(callback.message)
    
        text = get_game_screen(
            cards,
            [],
            full_name,
            bet,
            status_text=get_initial_status_text(),
            show_hint=True,
        )
        keyboard = get_poker_keyboard(game_id, [])
        edited = await safe_edit_message(deal_msg, text, reply_markup=keyboard)
        if not edited:
            await safe_send_message(callback.message, text, reply_markup=keyboard)
    finally:
        release_confirm_lock(chat_id, message_id)


@router.callback_query(F.data.startswith("poker_hold_"))
async def process_poker_hold(callback: types.CallbackQuery, state: FSMContext):
    game = await verify_active_game(callback, state)
    if game is None:
        return

    index = parse_callback_index(callback.data, 4)
    if index is None:
        return await callback.answer()

    new_held, is_held_now = toggle_held_index(game['held_indices'], index)
    await state.update_data(held_indices=new_held)

    status = get_status_text_for_hold(len(new_held))
    text = get_game_screen(
        game['cards'],
        new_held,
        game['full_name'],
        game['bet'],
        status_text=status,
        show_hint=False,
    )
    keyboard = get_poker_keyboard(game['game_id'], new_held)
    await safe_edit_message(callback.message, text, reply_markup=keyboard)
    await callback.answer(get_hold_answer_text(index, is_held_now))


@router.callback_query(F.data.startswith("poker_reset_"))
async def process_poker_reset(callback: types.CallbackQuery, state: FSMContext):
    game = await verify_active_game(callback, state)
    if game is None:
        return

    await state.update_data(held_indices=[])
    text = get_game_screen(
        game['cards'],
        [],
        game['full_name'],
        game['bet'],
        status_text=get_reset_status(),
        show_hint=True,
    )
    keyboard = get_poker_keyboard(game['game_id'], [])
    await safe_edit_message(callback.message, text, reply_markup=keyboard)
    await callback.answer("❌ Все Hold-метки сняты.")


@router.callback_query(F.data.startswith("poker_hint_"))
async def process_poker_hint(callback: types.CallbackQuery, state: FSMContext):
    game = await verify_active_game(callback, state)
    if game is None:
        return

    hint = get_smart_hint(game['cards'])
    text = get_game_screen(
        game['cards'],
        game['held_indices'],
        game['full_name'],
        game['bet'],
        status_text=hint,
        show_hint=True,
    )
    keyboard = get_poker_keyboard(game['game_id'], game['held_indices'])
    await safe_edit_message(callback.message, text, reply_markup=keyboard)
    await callback.answer("💡 Подсказка от крупье!")


@router.callback_query(F.data.startswith("poker_help_"))
async def process_poker_help(callback: types.CallbackQuery, state: FSMContext):
    if is_static_callback(callback.data):
        return await callback.message.answer(get_tutorial_text())

    game = await verify_active_game(callback, state)
    if game is None:
        return

    keyboard = get_close_keyboard(game['game_id'])
    await safe_edit_message(callback.message, get_tutorial_text(), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("poker_payouts_"))
async def process_poker_payouts(callback: types.CallbackQuery, state: FSMContext):
    if is_static_callback(callback.data):
        return await callback.message.answer(get_payout_table_text())

    game = await verify_active_game(callback, state)
    if game is None:
        return

    keyboard = get_close_keyboard(game['game_id'])
    await safe_edit_message(callback.message, get_payout_table_text(), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("poker_back_"))
async def process_poker_back(callback: types.CallbackQuery, state: FSMContext):
    game = await verify_active_game(callback, state)
    if game is None:
        return

    text = get_game_screen(
        game['cards'],
        game['held_indices'],
        game['full_name'],
        game['bet'],
        status_text=get_back_to_game_status(),
        show_hint=True,
    )
    keyboard = get_poker_keyboard(game['game_id'], game['held_indices'])
    await safe_edit_message(callback.message, text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("poker_draw_"))
async def process_poker_draw(callback: types.CallbackQuery, state: FSMContext):
    game = await verify_active_game(callback, state)
    if game is None:
        return

    chat_id = game['chat_id']
    user_id = game['user_id']
    bet = game['bet']
    held_indices = game['held_indices']
    full_name = game['full_name']

    await play_change_cards_animation(callback.message, held_indices)

    final_cards = redraw_cards(game['cards'], held_indices)
    combination = evaluate_hand(final_cards)
    multiplier = get_payout_multiplier(combination)
    highlight = get_winning_card_indices(final_cards, combination)

    win_amount = 0
    if multiplier > 0:
        win_amount = calculate_win_amount(bet, combination)
        await update_user_balance(
            chat_id,
            user_id,
            win_amount,
            action="VideoPoker Win",
        )

    update_stats(user_id, combination, win_amount)

    result_text = format_game_result(combination, multiplier, win_amount, bet)
    final_text = build_final_text(
        final_cards,
        held_indices,
        highlight,
        full_name,
        bet,
        result_text,
        user_id,
    )

    invalidate_user_cache(chat_id, user_id)

    keyboard = get_replay_keyboard(bet)
    edited = await safe_edit_message(callback.message, final_text, reply_markup=keyboard)
    if not edited:
        await safe_send_message(callback.message, final_text, reply_markup=keyboard)

    await state.clear()
    await callback.answer(get_final_answer_text(win_amount), show_alert=False)
    asyncio.create_task(schedule_delete(callback.message, AUTO_DELETE_DELAY))


@router.callback_query(F.data.startswith("poker_replay_"))
async def process_poker_replay(callback: types.CallbackQuery, state: FSMContext):
    bet = parse_callback_index(callback.data, 2)
    if bet is None:
        return await callback.answer()

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get('is_banned'):
        return await callback.answer("⛔ Вы заблокированы.", show_alert=True)

    if not has_enough_balance(data.get('balance', 0), bet):
        return await callback.answer(
            "💳 Недостаточно средств для повтора.",
            show_alert=True,
        )

    await safe_delete_message(callback.message)
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(callback.message, "poker", bet, user_id=user_id)
    await callback.answer("🔁 Готовим новую раздачу...")


@router.callback_query(F.data.startswith("poker_"))
async def process_poker_unknown(callback: types.CallbackQuery):
    await callback.answer(
        "⚠️ Эта игра устарела или завершена.\n"
        "Начните новую: /poker [ставка]",
        show_alert=True,
    )