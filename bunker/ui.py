# bunker/ui.py
import math
from typing import List, Dict, Optional
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bunker.models import Game, Player, Phase, Scenario

class BunkerCB(CallbackData, prefix="bnk"):
    action: str  # join, leave, start, reveal_menu, reveal_do, vote_menu, vote_do, skip, special, my_cards, refresh
    game_id: str
    extra: str = ""

def render_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Генерирует текстовый прогресс-бар: ▓▓▓▓░░░░░░"""
    if total <= 0:
        return "░" * length
    fraction = min(1.0, max(0.0, current / total))
    filled = int(round(fraction * length))
    return "▓" * filled + "░" * (length - filled)

def format_lobby_text(game: Game) -> str:
    """Форматирует сообщение лобби игры."""
    players_count = len(game.players)
    text = (
        f"☢️ <b>БУНКЕР — ПОДГОТОВКА К ИГРЕ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>Организатор:</b> {game.host_name}\n"
        f"👥 <b>Игроков в лобби:</b> {players_count}\n\n"
    )
    
    if game.players:
        text += "<b>Список участников:</b>\n"
        for idx, (uid, p) in enumerate(game.players.items(), 1):
            text += f"{idx}. 👤 <b>{p.name}</b>\n"
    else:
        text += "<i>Нажмите кнопку ниже, чтобы войти в лобби!</i>\n"
        
    text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <i>Минимум для старта: 2 игрока.</i>\n"
        f"При старте всем участникам отправятся их тайные карты в ЛС!"
    )
    return text

def get_lobby_keyboard(game_id: str, is_host: bool) -> InlineKeyboardMarkup:
    """Клавиатура лобби."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Вступить", callback_data=BunkerCB(action="join", game_id=game_id).pack())
    builder.button(text="➖ Покинуть", callback_data=BunkerCB(action="leave", game_id=game_id).pack())
    builder.button(text="🃏 Мои карты в ЛС", callback_data=BunkerCB(action="my_cards", game_id=game_id).pack())
    
    if is_host:
        builder.button(text="🚀 НАЧАТЬ ИГРУ", callback_data=BunkerCB(action="start", game_id=game_id).pack())
        
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def format_stage_text(game: Game, bot_username: str = "") -> str:
    """Главный текстовый виджет живой сцены в чате."""
    sc = game.scenario
    alive_players = [p for p in game.players.values() if p.alive]
    kicked_players = [p for p in game.players.values() if not p.alive]
    
    phase_titles = {
        Phase.INTRO: "📢 Вступительный инструктаж",
        Phase.REVEAL: f"🃏 Раунд {game.current_round}/{game.total_rounds} · Раскрытие карт",
        Phase.DISCUSSION: f"⏳ Раунд {game.current_round}/{game.total_rounds} · Обсуждение",
        Phase.DEFENSE: f"🛡 Раунд {game.current_round}/{game.total_rounds} · Защитное слово",
        Phase.VOTING: f"🗳 Раунд {game.current_round}/{game.total_rounds} · Голосование",
        Phase.TIEBREAK: f"⚖️ Переголосование при ничьей",
        Phase.KICK: f"💀 Изгнание из бункера",
        Phase.EPILOGUE: f"📖 Финал и Эпилог",
        Phase.FINISHED: f"🏁 Игра завершена"
    }

    current_phase_title = phase_titles.get(game.phase, f"Фаза {game.phase.name}")

    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{sc.icon} <b>{sc.title.upper()}</b> · {sc.bunker_name}\n"
        f"📌 <b>Статус:</b> {current_phase_title}\n"
        f"🚪 <b>Мест в бункере:</b> {game.capacity} из {len(game.players)}\n"
        f"⏱ <b>Время фазы:</b> {game.timer_seconds} сек.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    text += "<b>👥 СОСТАВ ГРУППЫ:</b>\n"

    for p in game.players.values():
        status_icon = "⬜" if p.alive else "💀 (изгнан)"
        if p.alive and game.phase == Phase.VOTING:
            voted_str = " ✅" if p.voted_for else " ⏳"
        else:
            voted_str = ""

        text += f"\n<b>{status_icon} {p.name}</b>{voted_str}\n"

        # Раскрытые карты
        revealed_items = []
        for cat_id, card in p.cards.items():
            if card.revealed:
                revealed_items.append(f"  └ {card.icon} <b>{card.category_name}:</b> {card.value}")

        if revealed_items:
            text += "\n".join(revealed_items) + "\n"
        else:
            text += "  └ <i>Все карты скрыты</i> 🔒\n"

    # Если есть логи последнего действия
    if game.logs:
        text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n<b>📜 События:</b>\n"
        for log_entry in game.logs[-3:]:
            text += f"• {log_entry}\n"

    return text

def get_stage_keyboard(game: Game, bot_username: str) -> InlineKeyboardMarkup:
    """Создаёт контекстную клавиатуру для текущей фазы игры."""
    builder = InlineKeyboardBuilder()
    gid = game.game_id

    builder.button(text="🃏 Мои карты в ЛС", url=f"https://t.me/{bot_username}?start={gid}")

    if game.phase == Phase.REVEAL:
        builder.button(text="🔓 Раскрыть карту", callback_data=BunkerCB(action="reveal_menu", game_id=gid).pack())
    elif game.phase == Phase.DISCUSSION:
        skips_count = sum(1 for p in game.players.values() if p.alive and p.has_skipped)
        alive_count = sum(1 for p in game.players.values() if p.alive)
        builder.button(
            text=f"💬 Пропустить ({skips_count}/{alive_count})",
            callback_data=BunkerCB(action="skip", game_id=gid).pack()
        )
    elif game.phase in [Phase.VOTING, Phase.TIEBREAK]:
        votes_count = len(game.votes)
        alive_count = sum(1 for p in game.players.values() if p.alive)
        builder.button(
            text=f"🗳 Проголосовать ({votes_count}/{alive_count})",
            callback_data=BunkerCB(action="vote_menu", game_id=gid).pack()
        )

    builder.button(text="🔄 Обновить сцену", callback_data=BunkerCB(action="refresh", game_id=gid).pack())
    builder.adjust(1, 1, 1)
    return builder.as_markup()
