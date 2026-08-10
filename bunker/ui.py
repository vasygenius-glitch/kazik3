# bunker/ui.py
from __future__ import annotations

from typing import List, Optional, Tuple

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bunker import engine
from bunker.data import CATEGORIES
from bunker.models import (
    BOARD_SOFT_LIMIT, EVENTS_SHOW, MAX_PLAYERS, MIN_PLAYERS,
    Game, Phase, Player, escape_html, shorten,
)

SEP = "━" * 16


class BunkerCB(CallbackData, prefix="bnk"):
    action: str
    game_id: str
    extra: str = ""


def cb(action: str, gid: str, extra: str = "") -> str:
    return BunkerCB(action=action, game_id=gid, extra=extra).pack()


def fmt_timer(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}" if m else f"{s}с"


def deep_link(bot_username: str, game_id: str) -> str:
    return f"https://t.me/{bot_username}?start={game_id}"


# ---------------------------------- ЛОББИ ----------------------------------- #
def format_lobby_text(game: Game) -> str:
    s = game.settings
    lines = [
        "☢️ <b>БУНКЕР · НАБОР В УБЕЖИЩЕ</b>",
        f"👑 {game.host_safe_name} · 👥 {len(game.players)}/{MAX_PLAYERS} "
        f"(мин. {MIN_PLAYERS})",
        SEP,
    ]
    if game.players:
        lines += [f"{p.seat}. <b>{p.safe_name}</b>"
                  f"{' 👑' if p.user_id == game.host_id else ''}{' 🤖' if p.is_bot else ''}"
                  for p in game.ordered_players()]
    else:
        lines.append("<i>Пока никого. Жмите «Вступить».</i>")

    lines += [
        SEP,
        f"⏱ раскрытие {fmt_timer(s.reveal_seconds)} · обсуждение {fmt_timer(s.discussion_seconds)}"
        f" · голосование {fmt_timer(s.voting_seconds)}",
        f"🃏 карт: {s.reveals_first_round} в 1-м раунде, далее {s.reveals_per_round} · "
        f"🙈 скрыть: {'да' if s.allow_no_reveal else 'нет'} · "
        f"✨ спецкарты: {'да' if s.use_special_cards else 'нет'}",
        "",
        "❗️ Нажмите «📩 ЛС бота» — иначе карты не придут.",
    ]
    return "\n".join(lines)


def get_lobby_keyboard(game: Game, bot_username: str, show_bot_buttons: bool) -> InlineKeyboardMarkup:
    gid = game.game_id
    kb = InlineKeyboardBuilder()
    kb.row()
    kb.button(text="✅ Вступить", callback_data=cb("join", gid))
    kb.button(text="🚪 Выйти", callback_data=cb("leave", gid))
    if bot_username:
        kb.button(text="📩 ЛС бота", url=deep_link(bot_username, gid))
    kb.button(text="⚙️ Настройки", callback_data=cb("settings", gid))
    if show_bot_buttons:
        kb.button(text="🤖 +", callback_data=cb("add_bot", gid))
        kb.button(text="🤖 −", callback_data=cb("remove_bot", gid))
    kb.button(text="🚀 НАЧАТЬ", callback_data=cb("start", gid))
    kb.button(text="❌ Отменить", callback_data=cb("cancel", gid))
    kb.adjust(2, 2, 2, 2)
    return kb.as_markup()


# ------------------------------- НАСТРОЙКИ ---------------------------------- #
def format_settings_text(game: Game) -> str:
    return ("⚙️ <b>НАСТРОЙКИ ПАРТИИ</b>\n" + SEP +
            "\nКнопки переключают значения по кругу.\n"
            "<i>Обсуждение — это время спора в чате; раскрытие и голосование "
            "происходят в ЛС бота.</i>")


def get_settings_keyboard(game: Game) -> InlineKeyboardMarkup:
    s, gid = game.settings, game.game_id
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🔓 Раскрытие: {fmt_timer(s.reveal_seconds)}", callback_data=cb("set", gid, "reveal"))
    kb.button(text=f"💬 Обсуждение: {fmt_timer(s.discussion_seconds)}", callback_data=cb("set", gid, "disc"))
    kb.button(text=f"🗳 Голосование: {fmt_timer(s.voting_seconds)}", callback_data=cb("set", gid, "vote"))
    kb.button(text=f"🃏 1-й раунд: {s.reveals_first_round}", callback_data=cb("set", gid, "first"))
    kb.button(text=f"🃏 Далее: {s.reveals_per_round}", callback_data=cb("set", gid, "per"))
    kb.button(text=f"🙈 Скрыть: {'да' if s.allow_no_reveal else 'нет'}", callback_data=cb("set", gid, "nore"))
    kb.button(text=f"✨ Спецкарты: {'да' if s.use_special_cards else 'нет'}", callback_data=cb("set", gid, "spec"))
    kb.button(text=f"👁 Голоса: {'открытые' if s.open_votes else 'тайные'}", callback_data=cb("set", gid, "open"))
    kb.button(text=f"🔔 Пинги фаз: {'да' if s.phase_pings else 'нет'}", callback_data=cb("set", gid, "ping"))
    kb.button(text="⬅️ В лобби", callback_data=cb("lobby", gid))
    kb.adjust(1, 1, 1, 2, 2, 2, 1)
    return kb.as_markup()


# ------------------------- ПУБЛИЧНОЕ ТАБЛО (в чате) ------------------------- #
def _status_marks(game: Game, p: Player) -> str:
    marks = []
    if not p.alive:
        return " 💀"
    if p.shielded:
        marks.append("🛡")
    if p.vote_weight > 1:
        marks.append("⚖️")
    if game.phase is Phase.REVEAL and engine.player_reveal_done(game, p):
        marks.append("🙈" if p.no_reveal_choice else "✔️")
    if game.phase is Phase.DISCUSSION and p.has_skipped:
        marks.append("⏭")
    if game.phase.is_voting and p.user_id in game.votes:
        marks.append("✅")
    return (" " + "".join(marks)) if marks else ""


def _hint(game: Game) -> str:
    alive = game.alive_players()
    n = len(alive) or 1
    if game.phase is Phase.INTRO:
        return "📜 Личные дела ушли в ЛС бота. Изучайте карты."
    if game.phase is Phase.REVEAL:
        done = sum(1 for p in alive if engine.player_reveal_done(game, p))
        extra = " Можно ничего не открывать." if game.settings.allow_no_reveal else ""
        return (f"🔓 Откройте {engine.reveals_allowed(game)} карт(ы) в ЛС бота.{extra} "
                f"Определились: <b>{done}/{n}</b>")
    if game.phase is Phase.DISCUSSION:
        ready = sum(1 for p in alive if p.has_skipped)
        return f"💬 Спорьте в чате! Готовы голосовать: <b>{ready}/{n}</b> (кнопка «⏭ Готов»)"
    if game.phase is Phase.VOTING:
        return f"🗳 Голосование в ЛС бота. Проголосовали: <b>{len(game.votes)}/{n}</b>"
    if game.phase is Phase.TIEBREAK:
        names = ", ".join(f"<b>{game.players[t].safe_name}</b>"
                          for t in game.tie_candidates if t in game.players)
        return f"⚖️ Переголосование: {names} · <b>{len(game.votes)}/{n}</b>"
    return "🏁 Партия завершена."


def _render_board(game: Game, level: int) -> str:
    sc = game.scenario
    left = engine.seconds_left(game)
    if game.is_paused:
        timer = " · ⏸ <b>ПАУЗА</b>"
    else:
        bucket = -(-left // 10) * 10          # округление вверх до 10 с
        timer = f" · ⏳ ~{fmt_timer(bucket)}" if game.timer_seconds and left else ""
    out = [
        f"☢️ <b>БУНКЕР</b> · {escape_html(sc.title) if sc else '—'}",
        f"🏚 {escape_html(sc.bunker_name) if sc else '—'} · 🎟 мест {game.capacity} · "
        f"👥 живых {game.alive_count}/{len(game.players)}",
        f"🔁 раунд <b>{game.current_round}/{game.total_rounds}</b> · "
        f"<b>{game.phase.title}</b>{timer}",
        SEP,
    ]
    for p in game.ordered_players():
        rev, hid = p.revealed_cards(), p.hidden_cards()
        total = len(p.cards) or len(CATEGORIES)
        head = (f"{'👤' if p.alive else '💀'} <b>#{p.seat} {p.safe_name}</b>"
                f"{' 🤖' if p.is_bot else ''}{_status_marks(game, p)} "
                f"— {len(rev)}/{total}")
        if level >= 2:
            out.append(head)
            continue
        if level == 1:
            shown = " · ".join(f"{c.icon}{escape_html(shorten(c.value, 16))}" for c in rev[:3])
            more = f" +{len(rev) - 3}" if len(rev) > 3 else ""
            lock = f" · 🔒{len(hid)}" if hid else ""
            out.append(head + (f"\n   {shown}{more}{lock}" if rev or hid else ""))
            continue
        out.append("")
        out.append(head)
        for c in rev:
            out.append(f"   {c.icon} <b>{escape_html(c.category_name)}:</b> "
                       f"{escape_html(shorten(c.value, 56))}")
        if hid:
            out.append("   🔒 " + " ".join(c.icon for c in hid))

    if game.events:
        out += ["", SEP, *game.events[-EVENTS_SHOW:]]
    out += [SEP, _hint(game)]
    return "\n".join(out)


def format_board_text(game: Game) -> str:
    for level in (0, 1, 2):
        text = _render_board(game, level)
        if len(text) <= BOARD_SOFT_LIMIT or level == 2:
            return text[:BOARD_SOFT_LIMIT]
    return ""


def get_board_keyboard(game: Game, bot_username: str = "") -> Optional[InlineKeyboardMarkup]:
    if game.phase.is_over:
        return None
    gid = game.game_id
    kb = InlineKeyboardBuilder()
    if game.phase is Phase.REVEAL:
        kb.button(text="🔓 Открыть карту", callback_data=cb("reveal_menu", gid))
    elif game.phase is Phase.DISCUSSION:
        kb.button(text="⏭ Готов голосовать", callback_data=cb("skip", gid))
    elif game.phase.is_voting:
        kb.button(text="🗳 Голосовать", callback_data=cb("vote_menu", gid))
    else:
        kb.button(text="🃏 Личное дело", callback_data=cb("my_cards", gid))

    pause_btn = "▶️ Снять" if game.is_paused else "⏸ Пауза"
    kb.button(text=pause_btn, callback_data=cb("pause", gid))
    kb.button(text="⏩ След. фаза", callback_data=cb("next_phase", gid))

    kb.button(text="🃏 Моё дело", callback_data=cb("my_cards", gid))
    kb.button(text="🔄", callback_data=cb("refresh", gid))
    if bot_username:
        kb.button(text="📩 ЛС", url=deep_link(bot_username, gid))
    kb.adjust(1, 2, 3)
    return kb.as_markup()


# --------------------------- ЛИЧНЫЕ МЕНЮ (ЛС) ------------------------------- #
def format_dossier_text(game: Game, player: Player) -> str:
    sc = game.scenario
    lines = ["☢️ <b>ЛИЧНОЕ ДЕЛО</b> <i>(видите только вы)</i>",
             f"👤 {player.safe_name} · место #{player.seat}"]
    if sc:
        lines.append(f"{sc.icon} {escape_html(sc.title)} · 🏚 {escape_html(sc.bunker_name)} "
                     f"· 🎟 мест {game.capacity}")
    lines.append(SEP)
    for c in player.cards.values():
        mark = "🔓" if c.revealed else "🔒"
        lines.append(f"{mark} {c.icon} <b>{escape_html(c.category_name)}:</b> {escape_html(c.value)}")
    if player.special_card:
        s = player.special_card
        lines += [SEP, f"✨ <b>{s.icon} {escape_html(s.name)}</b>"
                       f"{' <i>(использована)</i>' if s.used else ''}",
                  f"<i>{escape_html(s.description)}</i>"]
    lines += [SEP, "🔒 — в секрете, 🔓 — уже видно всему чату."]
    return "\n".join(lines)


def get_dossier_keyboard(game: Game, player: Player) -> InlineKeyboardMarkup:
    gid = game.game_id
    kb = InlineKeyboardBuilder()
    if game.phase is Phase.REVEAL and player.alive:
        kb.button(text="🔓 Открыть карту", callback_data=cb("reveal_menu", gid))
    elif game.phase.is_voting and player.alive:
        kb.button(text="🗳 Голосовать", callback_data=cb("vote_menu", gid))
    if engine.can_use_special(game, player):
        kb.button(text="✨ Спецкарта", callback_data=cb("spec", gid))
    kb.button(text="🔄 Обновить", callback_data=cb("my_cards", gid))
    kb.adjust(1)
    return kb.as_markup()


def format_reveal_prompt(game: Game, player: Player) -> str:
    limit = engine.reveals_allowed(game)
    left = max(0, limit - player.reveals_this_round)
    if engine.player_reveal_done(game, player):
        return (f"✅ <b>Раунд {game.current_round}:</b> выбор сделан.\n"
                f"<i>Ждём остальных… ⏳ {fmt_timer(engine.seconds_left(game))}</i>")
    lines = [f"🔓 <b>РАУНД {game.current_round} · РАСКРЫТИЕ</b>",
             f"⏳ {fmt_timer(engine.seconds_left(game))} · открыть карт: <b>{left}</b> из {limit}",
             "Что показать чату?"]
    if game.settings.allow_no_reveal:
        lines.append("<i>Можно ничего не открывать — но это подозрительно.</i>")
    return "\n".join(lines)


def get_reveal_keyboard(game: Game, player: Player) -> Optional[InlineKeyboardMarkup]:
    if game.phase is not Phase.REVEAL or not player.alive:
        return None
    gid = game.game_id
    kb = InlineKeyboardBuilder()
    if not engine.player_reveal_done(game, player):
        for c in player.hidden_cards():
            kb.button(text=f"{c.icon} {c.category_name}: {shorten(c.value, 22)}",
                      callback_data=cb("reveal_do", gid, c.category_id))
        if game.settings.allow_no_reveal and player.reveals_this_round == 0:
            kb.button(text="🙈 Ничего не открывать", callback_data=cb("reveal_none", gid))
    if engine.can_use_special(game, player):
        kb.button(text="✨ Спецкарта", callback_data=cb("spec", gid))
    kb.button(text="🃏 Моё дело", callback_data=cb("my_cards", gid))
    kb.adjust(1)
    return kb.as_markup()


def format_vote_prompt(game: Game, player: Player) -> str:
    title = "⚖️ ПЕРЕГОЛОСОВАНИЕ" if game.phase is Phase.TIEBREAK else "🗳 ГОЛОСОВАНИЕ"
    if player.user_id in game.votes:
        return (f"✅ Голос принят.\n<i>Ждём остальных… "
                f"⏳ {fmt_timer(engine.seconds_left(game))}</i>")
    kind = "открытое" if game.settings.open_votes else "тайное"
    return (f"<b>{title} · РАУНД {game.current_round}</b>\n"
            f"⏳ {fmt_timer(engine.seconds_left(game))} · голос {kind}\n"
            f"Кого выгоняем из бункера?")


def get_vote_keyboard(game: Game, player: Player) -> Optional[InlineKeyboardMarkup]:
    if not game.phase.is_voting or not player.alive:
        return None
    gid = game.game_id
    kb = InlineKeyboardBuilder()
    if player.user_id not in game.votes:
        for tid in engine.allowed_targets(game, player.user_id):
            if tid == 0:
                kb.button(text="🚫 Никого не изгонять", callback_data=cb("vote_do", gid, "0"))
                continue
            t = game.players.get(tid)
            if t:
                kb.button(text=f"#{t.seat} {shorten(t.name, 18)} · открыто {len(t.revealed_cards())}",
                          callback_data=cb("vote_do", gid, str(tid)))
    if engine.can_use_special(game, player):
        kb.button(text="✨ Спецкарта", callback_data=cb("spec", gid))
    kb.button(text="🃏 Моё дело", callback_data=cb("my_cards", gid))
    kb.adjust(1)
    return kb.as_markup()


def format_special_prompt(game: Game, player: Player) -> str:
    s = player.special_card
    if not s:
        return "У вас нет спецкарты."
    kind = engine.special_target_kind(s.id)
    tail = {"player": "Выберите игрока:", "category": "Выберите категорию:"}.get(
        kind, "Применить сейчас?")
    return (f"✨ <b>{s.icon} {escape_html(s.name)}</b>\n"
            f"<i>{escape_html(s.description)}</i>\n\n{tail}")


def get_special_keyboard(game: Game, player: Player) -> Optional[InlineKeyboardMarkup]:
    if not engine.can_use_special(game, player):
        return None
    s, gid = player.special_card, game.game_id
    kind = engine.special_target_kind(s.id)
    kb = InlineKeyboardBuilder()
    if kind == "player":
        for t in game.alive_players():
            if t.user_id != player.user_id and t.hidden_cards():
                kb.button(text=f"#{t.seat} {shorten(t.name, 18)}",
                          callback_data=cb("spec_go", gid, str(t.user_id)))
    elif kind == "category":
        names = {cid: (n, i) for cid, n, i in CATEGORIES}
        for cid in engine.force_reveal_categories(game):
            n, i = names[cid]
            kb.button(text=f"{i} {n}", callback_data=cb("spec_go", gid, cid))
    else:
        kb.button(text="✅ Применить", callback_data=cb("spec_go", gid))
    kb.button(text="⬅️ Назад", callback_data=cb("prompt", gid))
    kb.adjust(1)
    return kb.as_markup()


def format_intro_text(game: Game) -> str:
    sc = game.scenario
    if not sc:
        return "📜 Брифинг недоступен."
    rooms = ", ".join(escape_html(r) for r in sc.bunker_rooms) or "—"
    problems = " · ".join(escape_html(p) for p in sc.problems) or "нет данных"
    return (f"{sc.icon} <b>{escape_html(sc.title)}</b> · <i>{escape_html(sc.rarity)}</i>\n"
            f"{escape_html(sc.intro_text)}\n"
            f"🏚 <b>{escape_html(sc.bunker_name)}</b> ({escape_html(sc.bunker_size)}) · {rooms}\n"
            f"📦 {escape_html(sc.supplies)} · ⏱ {sc.duration_years} год(а)\n"
            f"⚠️ {problems}")


def prompt_for(game: Game, player: Player) -> Tuple[Optional[str], Optional[InlineKeyboardMarkup]]:
    """Что показать игроку в ЛС в текущей фазе (None — не беспокоить)."""
    if player.is_bot or not player.alive:
        return None, None
    if game.phase is Phase.REVEAL:
        return format_reveal_prompt(game, player), get_reveal_keyboard(game, player)
    if game.phase.is_voting:
        return format_vote_prompt(game, player), get_vote_keyboard(game, player)
    return None, None


# Alias compatibility for tests / legacy handlers
format_stage_text = lambda game, bot_username="": format_board_text(game)
get_stage_keyboard = get_board_keyboard
