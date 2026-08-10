# bunker/ui.py
from __future__ import annotations

from typing import Dict, List, Optional

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bunker.data import CATEGORIES
from bunker.models import (
    MIN_PLAYERS, TELEGRAM_TEXT_LIMIT, Game, Phase, escape_html,
)

SEP = "━" * 18
CATEGORY_ORDER: Dict[str, int] = {cat[0]: i for i, cat in enumerate(CATEGORIES)}
COMPACT_PLAYERS_THRESHOLD = 8   # с этого числа игроков рисуем сжатую сцену


class BunkerCB(CallbackData, prefix="bnk"):
    # ВАЖНО: pack() должен уложиться в 64 байта -> game_id держим коротким (<=10 симв.)
    action: str
    game_id: str
    extra: str = ""


def clamp_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> str:
    """Защита от MESSAGE_TOO_LONG: обрезаем по границе строки."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 20]
    cut = cut[: cut.rfind("\n") + 1] or cut
    return cut + "\n…<i>(сокращено)</i>"


def render_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Текстовый прогресс-бар: ▓▓▓▓░░░░░░"""
    if total <= 0 or length <= 0:
        return "░" * max(length, 0)
    fraction = min(1.0, max(0.0, current / total))
    filled = min(length, int(fraction * length + 0.5))
    return "▓" * filled + "░" * (length - filled)


# --------------------------------------------------------------------------- #
#                                   лобби                                     #
# --------------------------------------------------------------------------- #
def format_lobby_text(game: Game) -> str:
    players = list(game.players.values())
    text = [
        "☢️ <b>БУНКЕР — ПОДГОТОВКА К ИГРЕ</b>",
        SEP,
        f"👑 <b>Организатор:</b> {game.host_safe_name}",
        f"👥 <b>Игроков в лобби:</b> {len(players)}",
        "",
    ]
    if players:
        text.append("<b>Список участников:</b>")
        text += [f"{i}. 👤 <b>{p.safe_name}</b>" for i, p in enumerate(players, 1)]
    else:
        text.append("<i>Нажмите кнопку ниже, чтобы войти в лобби!</i>")

    text += [
        "",
        SEP,
        f"📌 <i>Минимум для старта: {MIN_PLAYERS} игрока.</i>",
        "При старте всем участникам придут тайные карты в ЛС.",
    ]
    return clamp_text("\n".join(text))


def get_lobby_keyboard(game_id: str, is_host: bool, is_creator: bool = False, bot_username: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Вступить", callback_data=BunkerCB(action="join", game_id=game_id).pack())
    b.button(text="➖ Покинуть", callback_data=BunkerCB(action="leave", game_id=game_id).pack())

    row_adjustments = [2]

    # Кнопки управления тестовыми ИИ-ботами (доступны только Создателю бота)
    if is_creator:
        b.button(text="🤖 + Бот", callback_data=BunkerCB(action="add_bot", game_id=game_id).pack())
        b.button(text="🤖 - Бот", callback_data=BunkerCB(action="remove_bot", game_id=game_id).pack())
        row_adjustments.append(2)

    # если username бота неизвестен — не создаём битый URL, шлём callback
    if bot_username:
        b.button(text="🃏 Мои карты в ЛС", url=f"https://t.me/{bot_username}?start={game_id}")
    else:
        b.button(text="🃏 Мои карты в ЛС",
                 callback_data=BunkerCB(action="my_cards", game_id=game_id).pack())

    row_adjustments.append(1)

    if is_host:
        b.button(text="🚀 НАЧАТЬ ИГРУ", callback_data=BunkerCB(action="start", game_id=game_id).pack())
        row_adjustments.append(1)

    b.adjust(*row_adjustments)
    return b.as_markup()


# --------------------------------------------------------------------------- #
#                                   сцена                                     #
# --------------------------------------------------------------------------- #
def _phase_title(game: Game) -> str:
    r = f"{game.current_round}/{game.total_rounds}"
    titles = {
        Phase.LOBBY: "🕓 Ожидание игроков",
        Phase.DEALING: "🎴 Раздача карт",
        Phase.INTRO: "📢 Вступительный инструктаж",
        Phase.REVEAL: f"🃏 Раунд {r} · Раскрытие карт",
        Phase.DISCUSSION: f"⏳ Раунд {r} · Обсуждение",
        Phase.DEFENSE: f"🛡 Раунд {r} · Защитное слово",
        Phase.VOTING: f"🗳 Раунд {r} · Голосование",
        Phase.TIEBREAK: "⚖️ Переголосование при ничьей",
        Phase.KICK: "💀 Изгнание из бункера",
        Phase.FINAL_SPEECH: "🎤 Последнее слово",
        Phase.EPILOGUE: "📖 Финал и эпилог",
        Phase.FINISHED: "🏁 Игра завершена",
    }
    return titles.get(game.phase, f"Фаза {game.phase.name}")


def _sorted_cards(player) -> List:
    return sorted(
        player.revealed_cards(),
        key=lambda c: CATEGORY_ORDER.get(c.category_id, 99),
    )


def format_stage_text(game: Game, bot_username: str = "") -> str:
    """Главный текстовый виджет игровой сцены. Безопасен для любой фазы."""
    sc = game.scenario
    header = f"{sc.icon} <b>{escape_html(sc.title.upper())}</b> · {escape_html(sc.bunker_name)}" \
        if sc else "☢️ <b>БУНКЕР</b>"

    alive = game.alive_count
    compact = len(game.players) >= COMPACT_PLAYERS_THRESHOLD

    lines = [
        SEP,
        header,
        f"📌 <b>Статус:</b> {_phase_title(game)}",
        f"🚪 <b>Мест в бункере:</b> {game.capacity} · <b>в игре:</b> {alive}/{len(game.players)}",
    ]

    if game.phase is Phase.REVEAL:
        lines.append("🔓 <i>Раскрывайте карты и доказывайте в чате, почему именно вы должны выжить!</i>")
    elif game.phase is Phase.DISCUSSION:
        lines.append("🎤 <b>ОБСУЖДЕНИЕ И ЗАЩИТА:</b>\n<i>Объясните в чате, почему вы крутой и необходимый специалист для выживания в бункере!</i>")
    elif game.phase.is_voting:
        lines.append("🗳 <i>Голосуйте за кандидата на изгнание или выберите «Никого не изгонять»!</i>")

    if game.timer_seconds:
        lines.append(
            f"⏱ <b>Время фазы:</b> {game.timer_seconds} сек. "
            f"{render_progress_bar(game.current_round, max(game.total_rounds, 1))}"
        )
    lines += [SEP, "", "<b>👥 СОСТАВ ГРУППЫ:</b>"]

    voted_ids = set(game.votes)
    for p in sorted(game.players.values(), key=lambda x: x.seat):
        status = "⬜" if p.alive else "💀"
        mark = ""
        if p.alive and game.phase.is_voting:
            mark = " ✅" if p.user_id in voted_ids else " ⏳"
        elif p.alive and game.phase is Phase.DISCUSSION and p.has_skipped:
            mark = " 💬"
        suffix = "" if p.alive else " <i>(изгнан)</i>"

        lines.append(f"\n<b>{status} {p.safe_name}</b>{suffix}{mark}")

        revealed = _sorted_cards(p)
        if not revealed:
            lines.append("  └ <i>Все карты скрыты</i> 🔒")
        elif compact:
            lines.append("  └ " + " · ".join(
                f"{c.icon} {escape_html(c.value)}" for c in revealed
            ))
        else:
            lines += [
                f"  └ {c.icon} <b>{escape_html(c.category_name)}:</b> {escape_html(c.value)}"
                for c in revealed
            ]

    if game.logs:
        lines += ["", SEP, "<b>📜 События:</b>"]
        lines += [f"• {entry}" for entry in game.logs[-3:]]

    return clamp_text("\n".join(lines))


def get_stage_keyboard(game: Game, bot_username: str = "") -> InlineKeyboardMarkup:
    """Контекстная клавиатура текущей фазы."""
    b = InlineKeyboardBuilder()
    gid = game.game_id
    rows: List[int] = []

    if bot_username:
        b.button(text="🃏 Мои карты в ЛС", url=f"https://t.me/{bot_username}?start={gid}")
    else:
        b.button(text="🃏 Мои карты", callback_data=BunkerCB(action="my_cards", game_id=gid).pack())
    rows.append(1)

    if game.phase is Phase.REVEAL:
        b.button(text="🔓 Раскрыть карту",
                 callback_data=BunkerCB(action="reveal_menu", game_id=gid).pack())
        rows.append(1)
    elif game.phase is Phase.DISCUSSION:
        skips = sum(1 for p in game.alive_players() if p.has_skipped)
        b.button(text=f"💬 Пропустить ({skips}/{game.alive_count})",
                 callback_data=BunkerCB(action="skip", game_id=gid).pack())
        rows.append(1)
    elif game.phase.is_voting:
        alive_ids = {p.user_id for p in game.alive_players()}
        votes = len(alive_ids & set(game.votes))
        b.button(text=f"🗳 Проголосовать ({votes}/{len(alive_ids)})",
                 callback_data=BunkerCB(action="vote_menu", game_id=gid).pack())
        rows.append(1)

    if game.phase not in (Phase.EPILOGUE, Phase.FINISHED):
        b.button(text="✨ Спецкарта", callback_data=BunkerCB(action="special", game_id=gid).pack())
        b.button(text="🔄 Обновить", callback_data=BunkerCB(action="refresh", game_id=gid).pack())
        rows.append(2)

    b.adjust(*rows)
    return b.as_markup()


# --------------------------------------------------------------------------- #
#                        подменю (их не хватало вовсе)                        #
# --------------------------------------------------------------------------- #
def get_reveal_keyboard(game: Game, user_id: int) -> Optional[InlineKeyboardMarkup]:
    """Меню выбора карты для раскрытия. None — если нечего раскрывать."""
    player = game.players.get(user_id)
    if not player:
        return None
    hidden = sorted(player.hidden_cards(), key=lambda c: CATEGORY_ORDER.get(c.category_id, 99))
    if not hidden:
        return None

    b = InlineKeyboardBuilder()
    for card in hidden:
        b.button(
            text=f"{card.icon} {card.category_name}",
            callback_data=BunkerCB(action="reveal_do", game_id=game.game_id,
                                   extra=card.category_id).pack(),
        )
    b.button(text="⬅️ Назад", callback_data=BunkerCB(action="refresh", game_id=game.game_id).pack())
    b.adjust(2)
    return b.as_markup()


def get_vote_keyboard(game: Game, voter_id: int, targets: List[int]) -> Optional[InlineKeyboardMarkup]:
    """Меню голосования. targets — из engine.allowed_targets()."""
    if not targets:
        return None
    b = InlineKeyboardBuilder()
    for tid in targets:
        if tid == 0:
            b.button(
                text="⛔ Никого не изгонять",
                callback_data=BunkerCB(action="vote_do", game_id=game.game_id, extra="0").pack(),
            )
        else:
            target = game.players.get(tid)
            if target:
                b.button(
                    text=f"🗳 {target.name}",
                    callback_data=BunkerCB(action="vote_do", game_id=game.game_id, extra=str(tid)).pack(),
                )
    b.button(text="⬅️ Назад", callback_data=BunkerCB(action="refresh", game_id=game.game_id).pack())
    b.adjust(1)
    return b.as_markup()
