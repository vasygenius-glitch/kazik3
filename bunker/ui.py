# bunker/ui.py
from __future__ import annotations

from typing import List, Optional

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bunker import engine
from bunker.models import (
    BOARD_SOFT_LIMIT, MAX_PLAYERS, MIN_PLAYERS, Game, Phase, Player,
    escape_html, shorten,
)


class BunkerCB(CallbackData, prefix="bnk"):
    action: str
    game_id: str
    extra: str = ""


def fmt_timer(seconds: int) -> str:
    if seconds <= 0:
        return "время вышло"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}" if m else f"{s} сек"


def deep_link(bot_username: str, game_id: str) -> str:
    return f"https://t.me/{bot_username}?start={game_id}"


# --------------------------------------------------------------------------- #
#                                  ЛОББИ                                      #
# --------------------------------------------------------------------------- #
def format_lobby_text(game: Game) -> str:
    s = game.settings
    lines = [
        "☢️ <b>БУНКЕР · НАБОР В УБЕЖИЩЕ</b>",
        "━" * 18,
        f"👑 Организатор: <b>{game.host_safe_name}</b>",
        f"👥 Игроков: <b>{len(game.players)}</b> / {MAX_PLAYERS} "
        f"(минимум для старта — {MIN_PLAYERS})",
        "",
    ]
    if game.players:
        for p in game.ordered_players():
            crown = " 👑" if p.user_id == game.host_id else ""
            bot_tag = " 🤖" if p.is_bot else ""
            lines.append(f"{p.seat}. <b>{p.safe_name}</b>{crown}{bot_tag}")
    else:
        lines.append("<i>Пока никого. Нажмите «Вступить»!</i>")

    lines += [
        "",
        "⚙️ <b>Настройки партии:</b>",
        f"• 🔓 Раскрытие: {fmt_timer(s.reveal_seconds)} "
        f"({s.reveals_first_round} карт(ы) в 1-м раунде, далее {s.reveals_per_round})",
        f"• 💬 Обсуждение: {fmt_timer(s.discussion_seconds)}",
        f"• 🗳 Голосование: {fmt_timer(s.voting_seconds)}",
        f"• 🙈 «Ничего не открывать»: {'разрешено' if s.allow_no_reveal else 'запрещено'}",
        "",
        "❗️ <b>Важно:</b> нажмите «📩 Открыть ЛС», иначе бот не сможет прислать вам карты.",
    ]
    return "\n".join(lines)


def get_lobby_keyboard(game: Game, is_host: bool, is_creator: bool,
                       bot_username: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    gid = game.game_id
    kb.button(text="✅ Вступить", callback_data=BunkerCB(action="join", game_id=gid).pack())
    kb.button(text="🚪 Выйти", callback_data=BunkerCB(action="leave", game_id=gid).pack())
    if bot_username:
        kb.button(text="📩 Открыть ЛС", url=deep_link(bot_username, gid))
    if is_host:
        kb.button(text="⚙️ Настройки", callback_data=BunkerCB(action="settings", game_id=gid).pack())
    if is_creator:
        kb.button(text="🤖 + бот", callback_data=BunkerCB(action="add_bot", game_id=gid).pack())
        kb.button(text="🤖 − бот", callback_data=BunkerCB(action="remove_bot", game_id=gid).pack())
    if is_host:
        kb.button(text="🚀 НАЧАТЬ ИГРУ", callback_data=BunkerCB(action="start", game_id=gid).pack())
        kb.button(text="❌ Отменить", callback_data=BunkerCB(action="cancel", game_id=gid).pack())
    kb.adjust(2, 1, 2, 1, 1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                             МЕНЮ НАСТРОЕК                                   #
# --------------------------------------------------------------------------- #
def format_settings_text(game: Game) -> str:
    s = game.settings
    return (
        "⚙️ <b>НАСТРОЙКИ ПАРТИИ</b>\n"
        "━" * 18 + "\n"
        "Нажимайте на кнопки — значения переключаются по кругу.\n\n"
        f"🔓 Раскрытие карт: <b>{fmt_timer(s.reveal_seconds)}</b>\n"
        f"💬 Обсуждение: <b>{fmt_timer(s.discussion_seconds)}</b>\n"
        f"🗳 Голосование: <b>{fmt_timer(s.voting_seconds)}</b>\n"
        f"🃏 Карт в 1-м раунде: <b>{s.reveals_first_round}</b>\n"
        f"🃏 Карт в остальных раундах: <b>{s.reveals_per_round}</b>\n"
        f"🙈 Можно ничего не открывать: <b>{'да' if s.allow_no_reveal else 'нет'}</b>\n"
        f"🖼 Картинка личного дела в ЛС: <b>{'да' if s.show_card_images else 'нет'}</b>"
    )


def get_settings_keyboard(game: Game) -> InlineKeyboardMarkup:
    s = game.settings
    gid = game.game_id
    kb = InlineKeyboardBuilder()

    def add(label: str, key: str):
        kb.button(text=label, callback_data=BunkerCB(action="set", game_id=gid, extra=key).pack())

    add(f"🔓 Раскрытие: {fmt_timer(s.reveal_seconds)}", "reveal")
    add(f"💬 Обсуждение: {fmt_timer(s.discussion_seconds)}", "disc")
    add(f"🗳 Голосование: {fmt_timer(s.voting_seconds)}", "vote")
    add(f"🃏 1-й раунд: {s.reveals_first_round}", "first")
    add(f"🃏 Раунд: {s.reveals_per_round}", "per")
    add(f"🙈 Скрывать: {'да' if s.allow_no_reveal else 'нет'}", "nore")
    add(f"🖼 Картинка: {'да' if s.show_card_images else 'нет'}", "img")
    kb.button(text="⬅️ Назад в лобби", callback_data=BunkerCB(action="lobby", game_id=gid).pack())
    kb.adjust(1, 1, 1, 2, 2, 1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                       ПУБЛИЧНОЕ ТАБЛО (в чате)                              #
# --------------------------------------------------------------------------- #
def _phase_hint(game: Game) -> str:
    alive = game.alive_players()
    n = len(alive)
    s = game.settings
    if game.phase is Phase.INTRO:
        return "📜 Читайте брифинг. Личные дела отправлены в ЛС бота."
    if game.phase is Phase.REVEAL:
        done = sum(1 for p in alive if engine.player_reveal_done(game, p))
        limit = engine.reveals_allowed(game)
        extra = " Можно ничего не открывать." if s.allow_no_reveal else ""
        return (f"🔓 Откройте <b>{limit}</b> карт(ы) в ЛС бота.{extra}\n"
                f"Определились: <b>{done}/{n}</b>")
    if game.phase is Phase.DISCUSSION:
        ready = sum(1 for p in alive if p.has_skipped)
        return (f"💬 <b>Обсуждение</b> — спорьте, доказывайте, торгуйтесь прямо в чате!\n"
                f"Готовы к голосованию: <b>{ready}/{n}</b> (кнопка «⏭ Я готов»)")
    if game.phase is Phase.VOTING:
        return (f"🗳 Голосование идёт в <b>ЛС бота</b> (тайно).\n"
                f"Проголосовали: <b>{len(game.votes)}/{n}</b>")
    if game.phase is Phase.TIEBREAK:
        names = ", ".join(f"<b>{game.players[t].safe_name}</b>"
                          for t in game.tie_candidates if t in game.players)
        return f"⚖️ Переголосование между: {names}\nПроголосовали: <b>{len(game.votes)}/{n}</b>"
    if game.phase.is_over:
        return "🏁 Партия завершена."
    return ""


def _board_body(game: Game, compact: bool) -> str:
    sc = game.scenario
    left_bucket = (engine.seconds_left(game) // 10) * 10   # бакет 10с — меньше правок сообщения
    header = [
        f"☢️ <b>БУНКЕР</b> · {escape_html(sc.title) if sc else '—'}",
        f"🏚 {escape_html(sc.bunker_name) if sc else '—'} · "
        f"мест: <b>{game.capacity}</b> · выживших: <b>{game.alive_count}</b>",
        f"🔁 Раунд <b>{game.current_round}/{game.total_rounds}</b> · "
        f"Фаза: <b>{game.phase.title}</b>"
        + (f" · ⏳ <b>{fmt_timer(left_bucket)}</b>" if game.timer_seconds else ""),
        "━" * 18,
        "👥 <b>УЧАСТНИКИ И ИХ ДАННЫЕ</b>",
    ]

    body: List[str] = []
    for p in game.ordered_players():
        revealed = p.revealed_cards()
        hidden = p.hidden_cards()
        total = len(p.cards) or 10
        tag = "👤" if p.alive else "💀"
        bot_tag = " 🤖" if p.is_bot else ""
        status = "" if p.alive else " <i>изгнан</i>"
        body.append(
            f"\n{tag} <b>#{p.seat} {p.safe_name}</b>{bot_tag}{status} "
            f"— открыто {len(revealed)}/{total}"
        )
        if compact:
            if revealed:
                body.append("   " + " · ".join(
                    f"{c.icon} {escape_html(shorten(c.value, 20))}" for c in revealed[:3]
                ))
            if hidden:
                body.append("   🔒 " + " ".join(c.icon for c in hidden))
        else:
            for c in revealed:
                body.append(f"   {c.icon} <b>{escape_html(c.category_name)}:</b> "
                            f"{escape_html(shorten(c.value, 60))}")
            if hidden:
                body.append("   🔒 <i>закрыто:</i> " + " ".join(c.icon for c in hidden))

    hint = _phase_hint(game)
    tail = ["", "━" * 18, hint] if hint else []
    return "\n".join(header + body + tail)


def format_board_text(game: Game) -> str:
    """Табло: все игроки и все их характеристики (закрытые — под 🔒)."""
    full = _board_body(game, compact=False)
    if len(full) <= BOARD_SOFT_LIMIT:
        return full
    return _board_body(game, compact=True)


def get_board_keyboard(game: Game, bot_username: str = "") -> Optional[InlineKeyboardMarkup]:
    if game.phase.is_over:
        return None
    gid = game.game_id
    kb = InlineKeyboardBuilder()

    if game.phase is Phase.REVEAL:
        kb.button(text="🔓 Раскрыть карту (в ЛС)",
                  callback_data=BunkerCB(action="reveal_menu", game_id=gid).pack())
    elif game.phase is Phase.DISCUSSION:
        kb.button(text="⏭ Я готов(а) голосовать",
                  callback_data=BunkerCB(action="skip", game_id=gid).pack())
    elif game.phase.is_voting:
        kb.button(text="🗳 Голосовать (в ЛС)",
                  callback_data=BunkerCB(action="vote_menu", game_id=gid).pack())

    kb.button(text="🃏 Мои карты", callback_data=BunkerCB(action="my_cards", game_id=gid).pack())
    kb.button(text="🔄 Обновить", callback_data=BunkerCB(action="refresh", game_id=gid).pack())
    if bot_username:
        kb.button(text="📩 ЛС бота", url=deep_link(bot_username, gid))
    kb.adjust(1, 2, 1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                        ЛИЧНЫЕ МЕНЮ (только в ЛС)                            #
# --------------------------------------------------------------------------- #
def format_dossier_text(game: Game, player: Player) -> str:
    sc = game.scenario
    lines = [
        "☢️ <b>ВАШЕ ЛИЧНОЕ ДЕЛО</b> <i>(видно только вам)</i>",
        "━" * 18,
        f"👤 {player.safe_name} · место #{player.seat}",
    ]
    if sc:
        lines.append(f"{sc.icon} Катастрофа: <b>{escape_html(sc.title)}</b>")
        lines.append(f"🏚 Бункер: <b>{escape_html(sc.bunker_name)}</b> "
                     f"({escape_html(sc.bunker_size)}), мест: {game.capacity}")
    lines += ["", "<b>ХАРАКТЕРИСТИКИ:</b>"]
    for card in player.cards.values():
        mark = "🔓 <i>(раскрыта чату)</i>" if card.revealed else "🔒 <i>(в секрете)</i>"
        lines.append(f"• {card.icon} <b>{escape_html(card.category_name)}:</b> "
                     f"{escape_html(card.value)} {mark}")

    if player.special_card:
        s = player.special_card
        used = " <i>(использована)</i>" if s.used else ""
        lines += ["", f"✨ <b>СПЕЦКАРТА:</b> {s.icon} <b>{escape_html(s.name)}</b>{used}\n"
                      f"<i>{escape_html(s.description)}</i>"]

    lines += [
        "",
        "🎭 <b>Совет:</b> отыгрывайте свои карты в чате — паникёр паникует, "
        "душнила поправляет всех, лидер командует.",
    ]
    return "\n".join(lines)


def get_dossier_keyboard(game: Game, player: Player) -> Optional[InlineKeyboardMarkup]:
    gid = game.game_id
    kb = InlineKeyboardBuilder()
    if game.phase is Phase.REVEAL and player.alive:
        kb.button(text="🔓 Выбрать карту для раскрытия",
                  callback_data=BunkerCB(action="reveal_menu", game_id=gid).pack())
    elif game.phase.is_voting and player.alive:
        kb.button(text="🗳 Голосовать",
                  callback_data=BunkerCB(action="vote_menu", game_id=gid).pack())
    kb.button(text="🔄 Обновить дело",
              callback_data=BunkerCB(action="my_cards", game_id=gid).pack())
    kb.adjust(1)
    return kb.as_markup()


def format_reveal_prompt(game: Game, player: Player) -> str:
    limit = engine.reveals_allowed(game)
    left = max(0, limit - player.reveals_this_round)
    lines = [
        f"🔓 <b>РАУНД {game.current_round} · РАСКРЫТИЕ КАРТ</b>",
        f"⏳ Время: {fmt_timer(engine.seconds_left(game))}",
        f"Нужно раскрыть карт: <b>{left}</b> из {limit}.",
        "",
        "Выберите, что показать всему чату:",
    ]
    if game.settings.allow_no_reveal:
        lines.append("<i>Можно ничего не открывать — но тогда вы под подозрением.</i>")
    return "\n".join(lines)


def get_reveal_keyboard(game: Game, user_id: int) -> Optional[InlineKeyboardMarkup]:
    player = game.players.get(user_id)
    if not player or not player.alive or game.phase is not Phase.REVEAL:
        return None
    hidden = player.hidden_cards()
    limit = engine.reveals_allowed(game)
    kb = InlineKeyboardBuilder()

    if player.reveals_this_round < limit:
        for card in hidden:
            kb.button(
                text=f"{card.icon} {card.category_name}: {shorten(card.value, 24)}",
                callback_data=BunkerCB(action="reveal_do", game_id=game.game_id,
                                       extra=card.category_id).pack(),
            )
        if game.settings.allow_no_reveal and player.reveals_this_round == 0:
            kb.button(text="🙈 Ничего не открывать",
                      callback_data=BunkerCB(action="reveal_none", game_id=game.game_id).pack())

    kb.button(text="🃏 Моё личное дело",
              callback_data=BunkerCB(action="my_cards", game_id=game.game_id).pack())
    kb.adjust(1)
    return kb.as_markup()


def format_vote_prompt(game: Game) -> str:
    title = "⚖️ ПЕРЕГОЛОСОВАНИЕ" if game.phase is Phase.TIEBREAK else "🗳 ГОЛОСОВАНИЕ"
    return (f"<b>{title} · РАУНД {game.current_round}</b>\n"
            f"⏳ Время: {fmt_timer(engine.seconds_left(game))}\n\n"
            f"Кого выгоняем из бункера? Голос тайный.")


def get_vote_keyboard(game: Game, voter_id: int) -> Optional[InlineKeyboardMarkup]:
    targets = engine.allowed_targets(game, voter_id)
    if not targets or voter_id in game.votes:
        return None
    kb = InlineKeyboardBuilder()
    for tid in targets:
        if tid == 0:
            kb.button(text="🚫 Никого не изгонять",
                      callback_data=BunkerCB(action="vote_do", game_id=game.game_id,
                                             extra="0").pack())
            continue
        p = game.players.get(tid)
        if not p:
            continue
        opened = len(p.revealed_cards())
        kb.button(text=f"#{p.seat} {shorten(p.name, 20)} (открыто {opened})",
                  callback_data=BunkerCB(action="vote_do", game_id=game.game_id,
                                         extra=str(tid)).pack())
    kb.adjust(1)
    return kb.as_markup()


def format_intro_text(game: Game) -> str:
    sc = game.scenario
    if not sc:
        return "📜 Брифинг недоступен."
    rooms = ", ".join(escape_html(r) for r in sc.bunker_rooms) or "—"
    problems = "\n".join(f"• {escape_html(p)}" for p in sc.problems) or "• нет данных"
    return (
        f"{sc.icon} <b>{escape_html(sc.title)}</b> · <i>{escape_html(sc.rarity)}</i>\n"
        "━" * 18 + "\n"
        f"{escape_html(sc.intro_text)}\n\n"
        f"🏚 <b>{escape_html(sc.bunker_name)}</b> ({escape_html(sc.bunker_size)})\n"
        f"🚪 Отсеки: {rooms}\n"
        f"📦 Запасы: {escape_html(sc.supplies)}\n"
        f"⏱ Срок изоляции: <b>{sc.duration_years} год(а)</b>\n"
        f"🎟 Мест в бункере: <b>{game.capacity}</b> из {len(game.players)}\n\n"
        f"⚠️ <b>Проблемы:</b>\n{problems}\n\n"
        f"📩 Личные дела отправлены в ЛС бота — <b>в чат они не попадают</b>."
    )


# Alias compatibility
format_stage_text = lambda game, bot_username="": format_board_text(game)
get_stage_keyboard = get_board_keyboard

