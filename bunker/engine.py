# bunker/engine.py
"""Чистая игровая логика. Telegram API здесь не вызывается."""
from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Tuple

from bunker.data import CATEGORIES, HEALTHY_VALUE, SCENARIOS, calculate_bunker_capacity
from bunker.deck import deal_hands, deal_special_cards, random_value_for
from bunker.models import (
    DISCUSSION_CHOICES, FIRST_REVEAL_CHOICES, MAX_PLAYERS, MIN_PLAYERS,
    REVEAL_CHOICES, ROUND_REVEAL_CHOICES, VOTING_CHOICES,
    Game, Phase, Player, escape_html, shorten,
)

active_games: Dict[str, Game] = {}
GAME_TTL_SECONDS = 6 * 3600

BOT_NAMES = [
    "🤖 Ева", "🤖 Валли", "🤖 Т-800", "🤖 Джарвис", "🤖 Бэндер", "🤖 Марвин",
    "🤖 HAL-9000", "🤖 R2-D2", "🤖 C-3PO", "🤖 Оптимус", "🤖 Альтрон", "🤖 Аэлита",
]
CATEGORY_NAMES = {cid: (name, icon) for cid, name, icon in CATEGORIES}


# ------------------------------- жизненный цикл ---------------------------- #
def create_new_game(game_id: str, chat_id: int, host_id: int, host_name: str) -> Game:
    cleanup_stale_games()
    game = Game(game_id=game_id, chat_id=chat_id, host_id=host_id, host_name=host_name)
    active_games[game_id] = game
    return game


def new_game_id(chat_id: int) -> str:
    base = f"b{abs(chat_id) % 100000}{int(time.time()) % 10000}"
    gid, n = base, 0
    while gid in active_games:
        n += 1
        gid = f"{base}x{n}"
    return gid


def get_game(game_id: str) -> Optional[Game]:
    return active_games.get(game_id)


def get_game_by_chat(chat_id: int) -> Optional[Game]:
    cands = [g for g in active_games.values()
             if g.chat_id == chat_id and g.phase is not Phase.FINISHED]
    return max(cands, key=lambda g: g.created_at, default=None)


def find_player_game(user_id: int) -> Optional[Game]:
    cands = [g for g in active_games.values()
             if user_id in g.players and g.phase is not Phase.FINISHED]
    return max(cands, key=lambda g: g.updated_at, default=None)


def drop_game(game_id: str) -> None:
    active_games.pop(game_id, None)


def cleanup_stale_games(now: Optional[float] = None) -> List[Game]:
    now = now or time.time()
    stale = [g for g in list(active_games.values())
             if g.phase is Phase.FINISHED or (now - g.updated_at) > GAME_TTL_SECONDS]
    for g in stale:
        active_games.pop(g.game_id, None)
    return stale


# ------------------------------------ лобби -------------------------------- #
def add_player(game: Game, user_id: int, name: str, username: str = "",
               is_bot: bool = False) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Игра уже началась — присоединиться нельзя."
    if user_id in game.players:
        return False, "Вы уже в лобби."
    if len(game.players) >= MAX_PLAYERS:
        return False, f"Лобби заполнено (максимум {MAX_PLAYERS})."

    clean = (name or "").strip()[:32] or f"Игрок {len(game.players) + 1}"
    game.players[user_id] = Player(user_id=user_id, name=clean, username=username or "",
                                   seat=len(game.players) + 1, is_bot=is_bot)
    game.touch()
    return True, f"{clean}, вы в лобби!"


def remove_player(game: Game, user_id: int) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Выйти можно только до старта."
    if game.players.pop(user_id, None) is None:
        return False, "Вас нет в лобби."
    for idx, p in enumerate(game.ordered_players(), 1):
        p.seat = idx
    if user_id == game.host_id and game.players:
        new_host = game.ordered_players()[0]
        game.host_id, game.host_name = new_host.user_id, new_host.name
    game.touch()
    return True, "Вы покинули лобби."


def add_test_bot(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Ботов можно добавлять только в лобби."
    taken = {p.name for p in game.players.values()}
    free = [n for n in BOT_NAMES if n not in taken]
    name = free[0] if free else f"🤖 Бот #{len(game.players) + 1}"
    uid = 900_000_000 + random.randint(1, 9_999_999)
    while uid in game.players:
        uid += 1
    return add_player(game, uid, name, "", is_bot=True)


def remove_test_bot(game: Game) -> Tuple[bool, str]:
    bots = [p for p in game.ordered_players() if p.is_bot]
    if not bots:
        return False, "Тестовых ботов нет."
    return remove_player(game, bots[-1].user_id)


# --------------------------------- настройки -------------------------------- #
SETTINGS: Dict[str, tuple] = {
    "reveal": ("reveal_seconds",      "🔓 Раскрытие",      REVEAL_CHOICES),
    "disc":   ("discussion_seconds",  "💬 Обсуждение",     DISCUSSION_CHOICES),
    "vote":   ("voting_seconds",      "🗳 Голосование",    VOTING_CHOICES),
    "first":  ("reveals_first_round", "🃏 1-й раунд",      FIRST_REVEAL_CHOICES),
    "per":    ("reveals_per_round",   "🃏 Далее",          ROUND_REVEAL_CHOICES),
    "nore":   ("allow_no_reveal",     "🙈 Можно скрыть",   None),
    "spec":   ("use_special_cards",   "✨ Спецкарты",      None),
    "open":   ("open_votes",          "👁 Открытые голоса", None),
    "ping":   ("phase_pings",         "🔔 Пинги фаз",      None),
}


def cycle_setting(game: Game, key: str) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Настройки меняются только до старта."
    item = SETTINGS.get(key)
    if not item:
        return False, "Неизвестная настройка."
    attr, label, choices = item
    if choices is None:
        setattr(game.settings, attr, not getattr(game.settings, attr))
        game.touch()
        return True, f"{label}: {'да' if getattr(game.settings, attr) else 'нет'}"
    cur = getattr(game.settings, attr)
    idx = choices.index(cur) if cur in choices else -1
    val = choices[(idx + 1) % len(choices)]
    setattr(game.settings, attr, val)
    game.touch()
    return True, f"{label}: {val}"


# ------------------------------ фазы и таймеры ------------------------------ #
def phase_duration(game: Game, phase: Phase) -> int:
    s = game.settings
    return {
        Phase.INTRO: s.intro_seconds,
        Phase.REVEAL: s.reveal_seconds,
        Phase.DISCUSSION: s.discussion_seconds,
        Phase.VOTING: s.voting_seconds,
        Phase.TIEBREAK: s.tiebreak_seconds,
    }.get(phase, 0)


def set_phase(game: Game, phase: Phase, timer: Optional[int] = None) -> None:
    game.phase = phase
    dur = phase_duration(game, phase) if timer is None else int(timer)
    game.timer_seconds = max(0, dur)
    game.phase_deadline = time.time() + game.timer_seconds if game.timer_seconds else 0.0
    game.phase_started_at = time.time()
    game.board_signature = ""          # форсируем перерисовку табло
    game.touch()


def seconds_left(game: Game) -> int:
    if game.is_paused:
        return max(0, game.paused_seconds_left)
    return max(0, int(round(game.phase_deadline - time.time()))) if game.phase_deadline else 0


def phase_expired(game: Game) -> bool:
    if game.is_paused:
        return False
    return bool(game.phase_deadline) and time.time() >= game.phase_deadline


def toggle_pause(game: Game) -> Tuple[bool, str]:
    if not game.phase.in_game:
        return False, "Пауза возможна только во время игры."
    if game.is_paused:
        game.phase_deadline = time.time() + game.paused_seconds_left
        game.is_paused = False
        game.push_event("▶️ <b>Организатор снял игру с паузы</b>")
        return True, "▶️ Игра снята с паузы."
    else:
        game.paused_seconds_left = seconds_left(game)
        game.is_paused = True
        game.push_event("⏸ <b>Организатор поставил игру на паузу</b>")
        return True, "⏸ Игра поставлена на паузу."


def force_next_phase(game: Game) -> Tuple[bool, str]:
    if not game.phase.in_game:
        return False, "Переход возможен только во время игры."
    if game.is_paused:
        game.is_paused = False
    game.phase_deadline = time.time() - 1
    game.push_event("⏩ <b>Организатор досрочно переключил фазу</b>")
    return True, "⏩ Переход к следующей фазе."


def phase_complete(game: Game) -> bool:
    """Фазу можно закрыть досрочно — все определились."""
    if game.phase is Phase.REVEAL:
        return check_reveal_complete(game)
    if game.phase is Phase.DISCUSSION:
        return discussion_complete(game)
    if game.phase.is_voting:
        return check_voting_complete(game)
    return False


# ----------------------------------- старт ---------------------------------- #
def start_game_engine(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Игра уже запущена."
    count = len(game.players)
    if count < MIN_PLAYERS:
        return False, f"Нужно минимум {MIN_PLAYERS} игрока."
    if not SCENARIOS:
        return False, "Не найдено ни одного сценария (data.py)."

    hands = deal_hands(count)
    specials = deal_special_cards(count) if game.settings.use_special_cards else [None] * count
    if len(hands) < count:
        return False, "Ошибка раздачи карт."

    game.scenario = random.choice(SCENARIOS)
    game.capacity = max(1, min(count - 1, calculate_bunker_capacity(count)))
    game.total_rounds = max(1, count - game.capacity)
    game.current_round = 1
    game.consecutive_no_reveals = 0
    game.clear_events()

    for idx, (p, hand, sc) in enumerate(zip(game.ordered_players(), hands, specials), 1):
        p.seat, p.cards, p.special_card, p.alive = idx, hand, sc, True
        p.reset_round_state()

    game.reset_round_state()
    set_phase(game, Phase.INTRO)
    return True, "Игра началась!"


def cancel_game(game: Game) -> None:
    set_phase(game, Phase.FINISHED, timer=0)


def finish_game(game: Game) -> None:
    set_phase(game, Phase.FINISHED, timer=0)


# ------------------------------ раскрытие карт ------------------------------ #
def reveals_allowed(game: Game) -> int:
    s = game.settings
    return s.reveals_first_round if game.current_round == 1 else s.reveals_per_round


def player_reveal_done(game: Game, player: Player) -> bool:
    if not player.alive or player.no_reveal_choice or not player.hidden_cards():
        return True
    return player.reveals_this_round >= reveals_allowed(game)


def check_reveal_complete(game: Game) -> bool:
    alive = game.alive_players()
    return bool(alive) and all(player_reveal_done(game, p) for p in alive)


def reveal_player_card(game: Game, user_id: int, cat_id: str) -> Tuple[bool, str, str]:
    """-> (ok, текст для ЛС, событие для табло)"""
    if game.phase is not Phase.REVEAL:
        return False, "Сейчас не фаза раскрытия.", ""
    p = game.players.get(user_id)
    if p is None or not p.alive:
        return False, "Вы не раскрываете карты.", ""
    limit = reveals_allowed(game)
    if p.reveals_this_round >= limit:
        return False, f"В этом раунде вы уже раскрыли {limit}.", ""
    card = p.cards.get(cat_id)
    if card is None:
        return False, "Карта не найдена.", ""
    if card.revealed:
        return False, "Эта карта уже раскрыта.", ""

    card.revealed = True
    p.reveals_this_round += 1
    p.no_reveal_choice = False
    event = (f"🔓 <b>{p.safe_name}</b> → {card.icon} "
             f"{escape_html(shorten(card.value, 42))}")
    left = max(0, limit - p.reveals_this_round)
    tail = f" Осталось: {left}." if left else " Ход сделан."
    return True, f"Открыто: {card.icon} {card.category_name}.{tail}", event


def declare_no_reveal(game: Game, user_id: int) -> Tuple[bool, str, str]:
    if game.phase is not Phase.REVEAL:
        return False, "Сейчас не фаза раскрытия.", ""
    p = game.players.get(user_id)
    if not p or not p.alive:
        return False, "Вы не участвуете в раскрытии.", ""
    if not game.settings.allow_no_reveal:
        return False, "Организатор запретил скрывать карты.", ""
    if p.reveals_this_round:
        return False, "Вы уже раскрыли карту в этом раунде.", ""
    if p.no_reveal_choice:
        return False, "Вы уже сделали этот выбор.", ""

    p.no_reveal_choice = True
    return True, "Хорошо, вы ничего не открываете.", f"🙈 <b>{p.safe_name}</b> ничего не открыл(а)"


def auto_close_reveal(game: Game) -> int:
    late = 0
    for p in game.alive_players():
        if not player_reveal_done(game, p):
            p.no_reveal_choice = True
            late += 1
    return late


def reveal_all_cards(player: Player) -> None:
    for c in player.cards.values():
        c.revealed = True


# -------------------------------- обсуждение -------------------------------- #
def register_skip(game: Game, user_id: int) -> Tuple[bool, str]:
    if game.phase is not Phase.DISCUSSION:
        return False, "Сейчас нет обсуждения."
    p = game.players.get(user_id)
    if not p or not p.alive:
        return False, "Вы не участвуете в обсуждении."
    if p.has_skipped:
        return False, "Вы уже готовы."
    p.has_skipped = True
    game.touch()
    alive = game.alive_players()
    return True, f"Готовы: {sum(1 for x in alive if x.has_skipped)}/{len(alive)}"


def discussion_complete(game: Game) -> bool:
    alive = game.alive_players()
    return bool(alive) and all(p.has_skipped for p in alive)


# -------------------------------- голосование ------------------------------- #
def allowed_targets(game: Game, voter_id: int) -> List[int]:
    voter = game.players.get(voter_id)
    if not voter or not voter.alive or not game.phase.is_voting:
        return []
    targets = [p.user_id for p in game.alive_players()
               if p.user_id != voter_id and not p.shielded]
    if game.phase is Phase.TIEBREAK and game.tie_candidates:
        allow = set(game.tie_candidates)
        return [t for t in targets if t in allow]
    targets.append(0)                     # «никого не изгонять»
    return targets


def cast_vote(game: Game, voter_id: int, target_id: int) -> Tuple[bool, str, str]:
    if not game.phase.is_voting:
        return False, "Сейчас не голосование.", ""
    voter = game.players.get(voter_id)
    if not voter or not voter.alive:
        return False, "Вы не голосуете.", ""
    if voter_id in game.votes:
        return False, "Вы уже проголосовали.", ""
    if target_id not in allowed_targets(game, voter_id):
        return False, "Такую цель выбрать нельзя.", ""

    voter.voted_for = target_id
    game.votes[voter_id] = target_id
    game.touch()

    name = "«Никого не изгонять»" if target_id == 0 else game.players[target_id].name
    event = ""
    if game.settings.open_votes:
        event = f"🗳 <b>{voter.safe_name}</b> → {escape_html(shorten(name, 24))}"
    return True, f"Голос за {name} принят.", event


def check_voting_complete(game: Game) -> bool:
    alive = {p.user_id for p in game.alive_players()}
    return bool(alive) and alive.issubset(game.votes.keys())


def tally_votes(game: Game) -> Dict[int, float]:
    tally: Dict[int, float] = {}
    for voter_id, target_id in game.votes.items():
        voter = game.players.get(voter_id)
        if not voter or not voter.alive:
            continue
        w = max(0.0, voter.vote_weight)
        if target_id == 0:
            tally[0] = tally.get(0, 0.0) + w
            continue
        t = game.players.get(target_id)
        if not t or not t.alive or t.shielded:
            continue
        tally[target_id] = tally.get(target_id, 0.0) + w
    return tally


def process_voting_results(game: Game) -> Tuple[Optional[int], bool, str]:
    """-> (кого изгнать | None, ничья?, комментарий)"""
    tally = tally_votes(game)
    if not tally:
        pool = [p.user_id for p in game.alive_players() if not p.shielded]
        if not pool:
            return None, False, "⛔ Изгонять некого — раунд без изгнаний."
        return random.choice(pool), False, "⚠️ Никто не голосовал — решил жребий."

    top = max(tally.values())
    ties = sorted(t for t, v in tally.items() if v == top)

    if 0 in ties and len(ties) == 1:
        return None, False, "⛔ Большинство: «никого не изгонять»."
    ties = [t for t in ties if t != 0] or [0]
    if ties == [0]:
        return None, False, "⛔ Большинство: «никого не изгонять»."

    if len(ties) > 1:
        if game.phase is Phase.TIEBREAK or game.tie_attempts >= 1:
            return random.choice(ties), False, "⚖️ Повторная ничья — решил жребий."
        game.tie_candidates = ties
        game.tie_attempts += 1
        names = ", ".join(f"<b>{game.players[t].safe_name}</b>" for t in ties if t in game.players)
        return None, True, f"⚖️ Ничья: {names}"
    return ties[0], False, ""


def start_tiebreak(game: Game) -> None:
    game.votes.clear()
    for p in game.players.values():
        p.voted_for = None
    set_phase(game, Phase.TIEBREAK)


def kick_player_from_game(game: Game, kicked_id: int) -> str:
    p = game.players.get(kicked_id)
    if not p or not p.alive:
        return ""
    p.alive = False
    p.shielded = False
    reveal_all_cards(p)
    lines = [f"💀 Изгнан(а): <b>{p.safe_name}</b> — карты вскрыты:"]
    for c in p.cards.values():
        lines.append(f"   {c.icon} <b>{escape_html(c.category_name)}:</b> "
                     f"{escape_html(shorten(c.value, 70))}")
    if p.special_card:
        used = "использована" if p.special_card.used else "не использована"
        lines.append(f"   ✨ {p.special_card.icon} {escape_html(p.special_card.name)} ({used})")
    return "\n".join(lines)


def advance_round(game: Game) -> bool:
    """True — начинается новый раунд, False — пора в эпилог."""
    revealed = sum(p.reveals_this_round for p in game.alive_players())
    game.consecutive_no_reveals = game.consecutive_no_reveals + 1 if revealed == 0 else 0

    game.reset_round_state()
    game.clear_events()

    if (game.alive_count <= game.capacity
            or game.current_round >= game.total_rounds
            or game.consecutive_no_reveals >= 3
            or game.alive_count <= 1):
        set_phase(game, Phase.EPILOGUE, timer=0)
        return False

    game.current_round += 1
    set_phase(game, Phase.REVEAL)
    return True


# ------------------------------- спецкарты ---------------------------------- #
SPECIAL_TARGET = {"inspect": "player", "force_reveal": "category"}


def special_target_kind(card_id: str) -> Optional[str]:
    return SPECIAL_TARGET.get(card_id)


def can_use_special(game: Game, player: Player) -> bool:
    return bool(game.settings.use_special_cards and player.alive and player.special_card
                and not player.special_card.used
                and game.phase in (Phase.REVEAL, Phase.DISCUSSION, Phase.VOTING, Phase.TIEBREAK))


def use_special_card(game: Game, user_id: int, arg: str = "") -> Tuple[bool, str, str]:
    """-> (ok, приватный текст, публичное событие)"""
    p = game.players.get(user_id)
    if not p:
        return False, "Вы не в игре.", ""
    if not can_use_special(game, p):
        return False, "Сейчас спецкарту использовать нельзя.", ""
    sc = p.special_card
    kind = special_target_kind(sc.id)
    if kind and not arg:
        return False, "Нужно выбрать цель.", ""

    if sc.id == "immunity":
        p.shielded = True
        priv, event = "🛡 В этом раунде вас нельзя изгнать.", f"🛡 <b>{p.safe_name}</b> под защитой"

    elif sc.id == "double_vote":
        if user_id in game.votes:
            return False, "Вы уже проголосовали.", ""
        p.vote_weight = 2.0
        priv, event = "⚖️ Ваш голос весит 2.", f"⚖️ <b>{p.safe_name}</b> усилил(а) голос"

    elif sc.id == "heal":
        card = p.cards.get("health")
        if not card:
            return False, "Карты «Здоровье» нет.", ""
        card.value = HEALTHY_VALUE
        priv = "🩹 Здоровье восстановлено."
        event = (f"🩹 <b>{p.safe_name}</b> теперь здоров(а)" if card.revealed
                 else f"🩹 <b>{p.safe_name}</b> применил(а) аптечку")

    elif sc.id == "reroll":
        hidden = p.hidden_cards()
        if not hidden:
            return False, "Все ваши карты уже раскрыты.", ""
        card = random.choice(hidden)
        in_play = {c.value for pl in game.players.values()
                   for cid, c in pl.cards.items() if cid == card.category_id}
        card.value = random_value_for(card.category_id, in_play)
        priv = f"🔁 Новая карта «{card.category_name}»: {card.value}"
        event = f"🔁 <b>{p.safe_name}</b> сменил(а) одну закрытую карту"

    elif sc.id == "inspect":
        try:
            target = game.players[int(arg)]
        except (ValueError, KeyError):
            return False, "Игрок не найден.", ""
        hidden = target.hidden_cards()
        if not hidden or target.user_id == user_id or not target.alive:
            return False, "У этого игрока нечего смотреть.", ""
        card = random.choice(hidden)
        priv = (f"🔍 Досмотр <b>{target.safe_name}</b>:\n"
                f"{card.icon} <b>{escape_html(card.category_name)}:</b> {escape_html(card.value)}")
        event = f"🔍 <b>{p.safe_name}</b> досмотрел(а) <b>{target.safe_name}</b>"

    elif sc.id == "force_reveal":
        cat_id = arg
        if cat_id not in CATEGORY_NAMES:
            return False, "Категория не найдена.", ""
        opened = []
        for t in game.alive_players():
            card = t.cards.get(cat_id)
            if card and not card.revealed:
                card.revealed = True
                opened.append(t.safe_name)
        if not opened:
            return False, "Эта категория уже открыта у всех.", ""
        name, icon = CATEGORY_NAMES[cat_id]
        priv = f"🔓 Открыто у {len(opened)} игрок(ов): {name}."
        event = f"🔓 <b>{p.safe_name}</b> вскрыл(а) всем {icon} {escape_html(name)}"

    else:
        return False, "Эта спецкарта не поддерживается.", ""

    sc.used = True
    game.touch()
    return True, priv, event


def force_reveal_categories(game: Game) -> List[str]:
    """Категории, где есть хотя бы одна закрытая карта у живых."""
    out = []
    for cid, _, _ in CATEGORIES:
        if any((c := t.cards.get(cid)) and not c.revealed for t in game.alive_players()):
            out.append(cid)
    return out


# ----------------------------- ходы тестовых ботов -------------------------- #
def process_bot_actions(game: Game, max_actions: int = 1) -> List[str]:
    """Боты ходят по одному действию за тик — события выглядят живее."""
    events: List[str] = []
    bots = [p for p in game.alive_players() if p.is_bot]
    if not bots:
        return events
    random.shuffle(bots)

    for b in bots:
        if len(events) >= max_actions:
            break
        if game.phase is Phase.REVEAL:
            if player_reveal_done(game, b):
                continue
            hidden = b.hidden_cards()
            if not hidden:
                continue
            ok, _, ev = reveal_player_card(game, b.user_id, random.choice(hidden).category_id)
            if ok:
                events.append(ev)
        elif game.phase is Phase.DISCUSSION:
            if not b.has_skipped:
                register_skip(game, b.user_id)
                events.append("")
        elif game.phase.is_voting:
            if b.user_id in game.votes:
                continue
            targets = [t for t in allowed_targets(game, b.user_id) if t != 0] \
                or allowed_targets(game, b.user_id)
            if targets:
                ok, _, ev = cast_vote(game, b.user_id, random.choice(targets))
                if ok:
                    events.append(ev)
    return [e for e in events if e]


# ---------------------------------- эпилог ---------------------------------- #
KEY_ROLES = (
    ("медицина", 15, ("хирург", "врач", "медиц", "фельдшер")),
    ("техника", 15, ("инженер", "сварщик", "механик", "сантехник", "электрик")),
    ("продовольствие", 10, ("агроном", "фермер", "повар", "охотник")),
)
SEVERE_HEALTH = ("диабет", "сердц", "астма", "порок", "туберкул", "рак", "вич", "диализ")


def _values(survivors: List[Player], cat_id: str) -> List[str]:
    return [p.cards[cat_id].value for p in survivors if cat_id in p.cards]


def _scenario_weights(game: Game, survivors: List[Player]) -> Tuple[int, List[str], List[str]]:
    delta, pros, cons = 0, [], []
    if not game.scenario:
        return delta, pros, cons
    for key, mod in (game.scenario.weights or {}).items():
        cat_id, _, needle = key.partition(":")
        if not needle:
            continue
        if any(needle.lower() in v.lower() for v in _values(survivors, cat_id)):
            delta += mod * 3
            (pros if mod > 0 else cons).append(escape_html(needle))
    return delta, pros, cons


def calculate_epilogue(game: Game) -> str:
    sc = game.scenario
    if sc is None:
        return "📖 Эпилог недоступен: сценарий не выбран."

    survivors = game.alive_players()
    for p in game.players.values():
        reveal_all_cards(p)

    head = f"📖 <b>ЭПИЛОГ · {escape_html(sc.title)}</b>"
    if not survivors:
        return f"{head}\n💀 Бункер остался пустым — выживших нет."

    score, strong, weak = 50, [], []
    profs = " | ".join(_values(survivors, "profession")).lower()
    for label, bonus, keys in KEY_ROLES:
        if any(k in profs for k in keys):
            score += bonus
            strong.append(label)
        elif label != "продовольствие":
            score -= bonus
            weak.append(f"нет {label}")

    sick = sum(1 for h in _values(survivors, "health")
               if any(k in h.lower() for k in SEVERE_HEALTH))
    if sick:
        score -= sick * 8
        weak.append(f"тяжелобольных: {sick}")

    d, pros, cons = _scenario_weights(game, survivors)
    score += d
    strong += pros
    weak += cons

    if len(survivors) > game.capacity:
        over = len(survivors) - game.capacity
        score -= over * 10
        weak.append(f"перенаселение (+{over})")

    score = max(5, min(99, score))
    lines = [
        head,
        f"🏚 {escape_html(sc.bunker_name)} · {sc.duration_years} год(а) под землёй",
        "",
        "🚪 <b>Выжившие:</b>",
    ]
    for p in survivors:
        prof = p.cards["profession"].value if "profession" in p.cards else "без профессии"
        lines.append(f"• <b>{p.safe_name}</b> — {escape_html(shorten(prof, 46))}")
    if game.dead_players():
        lines.append("💀 <b>Изгнаны:</b> " + ", ".join(p.safe_name for p in game.dead_players()))
    lines += [
        "",
        f"📊 <b>Шанс выживания:</b> {score}%",
        f"✅ {', '.join(strong) if strong else 'сильных сторон нет'}",
        f"⚠️ {', '.join(weak) if weak else 'слабых сторон нет'}",
        "",
        (f"🎉 <b>УСПЕХ!</b> Группа пережила «{escape_html(sc.title)}»."
         if score >= 70 else "💀 <b>ТРАГЕДИЯ.</b> Двери так и не открылись."),
    ]
    return "\n".join(lines)
