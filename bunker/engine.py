# bunker/engine.py
"""Чистая игровая логика. Никаких вызовов Telegram API здесь нет."""
from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Tuple

from bunker.data import SCENARIOS, calculate_bunker_capacity
from bunker.deck import deal_hands, deal_special_cards
from bunker.models import (
    MAX_PLAYERS, MIN_PLAYERS, Game, Phase, Player, escape_html, shorten,
)

# Хранилище активных игр в памяти: {game_id: Game}
active_games: Dict[str, Game] = {}

GAME_TTL_SECONDS = 6 * 3600

BOT_NAMES = [
    "🤖 Ева", "🤖 Валли", "🤖 Т-800", "🤖 Джарвис", "🤖 Бэндер", "🤖 Марвин",
    "🤖 HAL-9000", "🤖 R2-D2", "🤖 C-3PO", "🤖 Оптимус", "🤖 Альтрон", "🤖 Аэлита",
]


# --------------------------------------------------------------------------- #
#                          жизненный цикл игры                                #
# --------------------------------------------------------------------------- #
def create_new_game(game_id: str, chat_id: int, host_id: int, host_name: str) -> Game:
    cleanup_stale_games()
    game = Game(
        game_id=game_id,
        chat_id=chat_id,
        host_id=host_id,
        host_name=host_name,
        phase=Phase.LOBBY,
        created_at=time.time(),
    )
    active_games[game_id] = game
    return game


def get_game(game_id: str) -> Optional[Game]:
    return active_games.get(game_id)


def get_game_by_chat(chat_id: int) -> Optional[Game]:
    candidates = [
        g for g in active_games.values()
        if g.chat_id == chat_id and g.phase is not Phase.FINISHED
    ]
    return max(candidates, key=lambda g: g.created_at, default=None)


def find_player_game(user_id: int) -> Optional[Game]:
    """Ищет активную игру, в которой участвует пользователь (для ЛС)."""
    candidates = [
        g for g in active_games.values()
        if user_id in g.players and g.phase is not Phase.FINISHED
    ]
    return max(candidates, key=lambda g: g.updated_at, default=None)


def drop_game(game_id: str) -> None:
    active_games.pop(game_id, None)


def cleanup_stale_games(now: Optional[float] = None) -> List[Game]:
    now = now or time.time()
    stale = [
        g for g in list(active_games.values())
        if g.phase is Phase.FINISHED or (now - g.updated_at) > GAME_TTL_SECONDS
    ]
    for g in stale:
        active_games.pop(g.game_id, None)
    return stale


# --------------------------------------------------------------------------- #
#                                  лобби                                     #
# --------------------------------------------------------------------------- #
def add_player(game: Game, user_id: int, name: str, username: str = "",
               is_bot: bool = False) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Игра уже началась — присоединиться нельзя."
    if user_id in game.players:
        return False, "Вы уже в лобби."
    if len(game.players) >= MAX_PLAYERS:
        return False, f"Лобби заполнено (максимум {MAX_PLAYERS} игроков)."

    clean_name = (name or "").strip()[:32] or f"Игрок {len(game.players) + 1}"
    game.players[user_id] = Player(
        user_id=user_id,
        name=clean_name,
        username=username or "",
        seat=len(game.players) + 1,
        is_bot=is_bot,
    )
    game.touch()
    return True, f"{clean_name}, вы в лобби!"


def remove_player(game: Game, user_id: int) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Выйти можно только до старта игры."
    player = game.players.pop(user_id, None)
    if player is None:
        return False, "Вас нет в лобби."

    for idx, p in enumerate(game.ordered_players(), 1):
        p.seat = idx

    if user_id == game.host_id and game.players:
        new_host = game.ordered_players()[0]
        game.host_id = new_host.user_id
        game.host_name = new_host.name
        game.log(f"👑 Новый организатор: <b>{new_host.safe_name}</b>")

    game.touch()
    return True, "Вы покинули лобби."


def add_test_bot(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Добавлять ботов можно только в лобби."
    if len(game.players) >= MAX_PLAYERS:
        return False, f"Лобби заполнено (максимум {MAX_PLAYERS} игроков)."

    existing = {p.name for p in game.players.values()}
    free = [n for n in BOT_NAMES if n not in existing]
    bot_name = free[0] if free else f"🤖 Бот #{len(game.players) + 1}"

    bot_uid = 900_000_000 + random.randint(1, 9_999_999)
    while bot_uid in game.players:
        bot_uid += 1
    return add_player(game, bot_uid, bot_name, "", is_bot=True)


def remove_test_bot(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Удалять ботов можно только до старта игры."
    bots = [p for p in game.ordered_players() if p.is_bot]
    if not bots:
        return False, "В лобби нет тестовых ботов."
    return remove_player(game, bots[-1].user_id)


# --------------------------------------------------------------------------- #
#                             настройки игры                                  #
# --------------------------------------------------------------------------- #
SETTINGS_MAP = {
    "reveal": ("reveal_seconds", "Время раскрытия"),
    "disc": ("discussion_seconds", "Время обсуждения"),
    "vote": ("voting_seconds", "Время голосования"),
    "first": ("reveals_first_round", "Карт в 1-м раунде"),
    "per": ("reveals_per_round", "Карт в раунде"),
    "nore": ("allow_no_reveal", "Можно ничего не открывать"),
    "img": ("show_card_images", "Картинка личного дела"),
}


def cycle_setting(game: Game, key: str) -> Tuple[bool, str]:
    """Переключает значение настройки по кругу."""
    from bunker.models import (
        DISCUSSION_CHOICES, FIRST_REVEAL_CHOICES, REVEAL_CHOICES,
        ROUND_REVEAL_CHOICES, VOTING_CHOICES,
    )
    if game.phase is not Phase.LOBBY:
        return False, "Настройки можно менять только до старта игры."

    choices_map = {
        "reveal": REVEAL_CHOICES,
        "disc": DISCUSSION_CHOICES,
        "vote": VOTING_CHOICES,
        "first": FIRST_REVEAL_CHOICES,
        "per": ROUND_REVEAL_CHOICES,
    }
    if key in ("nore", "img"):
        attr = SETTINGS_MAP[key][0]
        setattr(game.settings, attr, not getattr(game.settings, attr))
        game.touch()
        state = "включено" if getattr(game.settings, attr) else "выключено"
        return True, f"{SETTINGS_MAP[key][1]}: {state}"

    if key not in choices_map:
        return False, "Неизвестная настройка."

    attr = SETTINGS_MAP[key][0]
    choices = choices_map[key]
    current = getattr(game.settings, attr)
    try:
        idx = choices.index(current)
    except ValueError:
        idx = -1
    new_value = choices[(idx + 1) % len(choices)]
    setattr(game.settings, attr, new_value)
    game.touch()
    return True, f"{SETTINGS_MAP[key][1]}: {new_value}"


# --------------------------------------------------------------------------- #
#                           фазы и таймеры                                    #
# --------------------------------------------------------------------------- #
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
    duration = phase_duration(game, phase) if timer is None else timer
    game.timer_seconds = max(0, int(duration))
    game.phase_deadline = time.time() + game.timer_seconds if game.timer_seconds else 0.0
    game.touch()


def seconds_left(game: Game) -> int:
    if not game.phase_deadline:
        return 0
    return max(0, int(round(game.phase_deadline - time.time())))


def phase_expired(game: Game) -> bool:
    return bool(game.phase_deadline) and time.time() >= game.phase_deadline


# --------------------------------------------------------------------------- #
#                                  старт                                      #
# --------------------------------------------------------------------------- #
def start_game_engine(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Игра уже запущена."

    count = len(game.players)
    if count < MIN_PLAYERS:
        return False, f"Нужно минимум {MIN_PLAYERS} игрока для старта."
    if not SCENARIOS:
        return False, "Не найдено ни одного сценария (проверьте data.py)."

    hands = deal_hands(count)
    specials = deal_special_cards(count)
    if len(hands) < count or len(specials) < count:
        return False, "Ошибка раздачи карт: колода вернула меньше рук, чем игроков."

    game.scenario = random.choice(SCENARIOS)
    game.capacity = max(1, calculate_bunker_capacity(count))
    game.total_rounds = max(1, count - game.capacity)
    game.current_round = 1
    game.consecutive_no_reveals = 0

    for idx, (player, hand, special) in enumerate(
        zip(game.ordered_players(), hands, specials), 1
    ):
        player.seat = idx
        player.cards = hand
        player.special_card = special
        player.is_rat = bool(special and special.id == "rat")
        player.alive = True
        player.reset_round_state()

    game.reset_round_state()
    set_phase(game, Phase.INTRO)
    game.log(
        f"{game.scenario.icon} Сценарий: <b>{escape_html(game.scenario.title)}</b>. "
        f"Мест в бункере: {game.capacity} из {count}."
    )
    return True, "Игра началась!"


def cancel_game(game: Game) -> None:
    set_phase(game, Phase.FINISHED, timer=0)
    game.log("🚫 Игра отменена организатором.")


def finish_game(game: Game) -> None:
    set_phase(game, Phase.FINISHED, timer=0)


# --------------------------------------------------------------------------- #
#                           раскрытие карт                                    #
# --------------------------------------------------------------------------- #
def reveals_allowed(game: Game) -> int:
    s = game.settings
    return s.reveals_first_round if game.current_round == 1 else s.reveals_per_round


def player_reveal_done(game: Game, player: Player) -> bool:
    if not player.alive:
        return True
    if player.no_reveal_choice:
        return True
    if not player.hidden_cards():
        return True
    return player.reveals_this_round >= reveals_allowed(game)


def check_reveal_complete(game: Game) -> bool:
    alive = game.alive_players()
    return bool(alive) and all(player_reveal_done(game, p) for p in alive)


def reveal_player_card(game: Game, user_id: int, cat_id: str) -> Tuple[bool, str, str]:
    """-> (ok, приватный текст, публичный текст для чата)"""
    if game.phase is not Phase.REVEAL:
        return False, "Сейчас не фаза раскрытия карт.", ""

    player = game.players.get(user_id)
    if player is None:
        return False, "Вы не участвуете в этой игре.", ""
    if not player.alive:
        return False, "Изгнанные игроки не раскрывают карты.", ""

    limit = reveals_allowed(game)
    if player.reveals_this_round >= limit:
        return False, f"В этом раунде вы уже раскрыли карт: {limit}.", ""

    card = player.cards.get(cat_id)
    if card is None:
        return False, "Карта не найдена.", ""
    if card.revealed:
        return False, "Эта карта уже раскрыта.", ""

    card.revealed = True
    player.reveals_this_round += 1
    player.no_reveal_choice = False

    public = (
        f"🔓 <b>{player.safe_name}</b> раскрывает {card.icon} "
        f"<b>{escape_html(card.category_name)}</b>: {escape_html(shorten(card.value, 70))}"
    )
    game.log(public)
    left = max(0, limit - player.reveals_this_round)
    private = f"Карта «{card.category_name}» раскрыта! Осталось раскрыть: {left}."
    return True, private, public


def declare_no_reveal(game: Game, user_id: int) -> Tuple[bool, str, str]:
    """Игрок решает ничего не открывать в этом раунде."""
    if game.phase is not Phase.REVEAL:
        return False, "Сейчас не фаза раскрытия карт.", ""
    player = game.players.get(user_id)
    if not player or not player.alive:
        return False, "Вы не участвуете в раскрытии.", ""
    if not game.settings.allow_no_reveal:
        return False, "Организатор запретил скрывать карты — нужно раскрыть карту.", ""
    if player.no_reveal_choice:
        return False, "Вы уже решили ничего не открывать.", ""

    player.no_reveal_choice = True
    public = f"🙈 <b>{player.safe_name}</b> решил(а) ничего не раскрывать в этом раунде."
    game.log(public)
    return True, "Хорошо, в этом раунде вы ничего не раскрываете.", public


def auto_close_reveal(game: Game) -> List[str]:
    """По истечении таймера все, кто не выбрал — считаются «ничего не открыл»."""
    msgs: List[str] = []
    for p in game.alive_players():
        if not player_reveal_done(game, p):
            p.no_reveal_choice = True
            msgs.append(f"⌛ <b>{p.safe_name}</b> не успел(а) раскрыть карту.")
    return msgs


def reveal_all_cards(player: Player) -> None:
    for card in player.cards.values():
        card.revealed = True


# --------------------------------------------------------------------------- #
#                              обсуждение                                     #
# --------------------------------------------------------------------------- #
def register_skip(game: Game, user_id: int) -> Tuple[bool, str, bool]:
    if game.phase is not Phase.DISCUSSION:
        return False, "Сейчас нет обсуждения.", False
    player = game.players.get(user_id)
    if not player or not player.alive:
        return False, "Вы не участвуете в обсуждении.", False
    if player.has_skipped:
        return False, "Вы уже готовы к голосованию.", False

    player.has_skipped = True
    game.touch()
    alive = game.alive_players()
    done = all(p.has_skipped for p in alive)
    ready = sum(1 for p in alive if p.has_skipped)
    return True, f"Вы готовы к голосованию ({ready}/{len(alive)}).", done


def discussion_complete(game: Game) -> bool:
    alive = game.alive_players()
    return bool(alive) and all(p.has_skipped for p in alive)


# --------------------------------------------------------------------------- #
#                              голосование                                    #
# --------------------------------------------------------------------------- #
def allowed_targets(game: Game, voter_id: int) -> List[int]:
    """Живые, кроме себя; в обычном голосовании + 0 («никого не изгонять»)."""
    voter = game.players.get(voter_id)
    if not voter or not voter.alive or not game.phase.is_voting:
        return []
    targets = [p.user_id for p in game.alive_players()
               if p.user_id != voter_id and not p.shielded]
    if game.phase is Phase.TIEBREAK and game.tie_candidates:
        allowed = set(game.tie_candidates)
        targets = [t for t in targets if t in allowed]
    else:
        targets.append(0)
    return targets


def cast_vote(game: Game, voter_id: int, target_id: int) -> Tuple[bool, str, str]:
    """-> (ok, приватный текст, публичный текст)"""
    if not game.phase.is_voting:
        return False, "Сейчас не фаза голосования.", ""

    voter = game.players.get(voter_id)
    if not voter or not voter.alive:
        return False, "Вы не участвуете в голосовании.", ""
    if voter_id in game.votes:
        return False, "Вы уже проголосовали.", ""
    if voter_id == target_id:
        return False, "Голосовать за себя нельзя.", ""

    targets = allowed_targets(game, voter_id)
    if target_id not in targets:
        return False, "Этого игрока нельзя выбрать в текущем голосовании.", ""

    target_name = "«Никого не изгонять»"
    if target_id != 0:
        target_name = game.players[target_id].name

    voter.voted_for = target_id
    game.votes[voter_id] = target_id
    alive = len(game.alive_players())
    public = f"🗳 <b>{voter.safe_name}</b> проголосовал(а) ({len(game.votes)}/{alive})."
    game.log(public)
    return True, f"Ваш голос за {target_name} принят!", public


def check_voting_complete(game: Game) -> bool:
    alive_ids = {p.user_id for p in game.alive_players()}
    return bool(alive_ids) and alive_ids.issubset(set(game.votes))


def tally_votes(game: Game) -> Dict[int, float]:
    tally: Dict[int, float] = {}
    for voter_id, target_id in game.votes.items():
        voter = game.players.get(voter_id)
        if not voter or not voter.alive:
            continue
        weight = max(0.0, voter.vote_weight)
        if target_id == 0:
            tally[0] = tally.get(0, 0.0) + weight
            continue
        target = game.players.get(target_id)
        if not target or not target.alive or target.shielded:
            continue
        tally[target_id] = tally.get(target_id, 0.0) + weight
    return tally


def process_voting_results(game: Game) -> Tuple[Optional[int], bool, str]:
    """-> (kicked_id | None, ничья?, комментарий для чата)"""
    tally = tally_votes(game)

    if not tally:
        pool = [p.user_id for p in game.alive_players() if not p.shielded]
        if not pool:
            return None, False, "⛔ Голосов нет и изгонять некого — раунд без изгнаний."
        kicked_id = random.choice(pool)
        return kicked_id, False, "⚠️ Никто не проголосовал — изгнанник определён жребием."

    top = max(tally.values())
    ties = sorted(tid for tid, v in tally.items() if v == top)

    if 0 in ties:
        return None, False, "⛔ Большинство выбрало «Никого не изгонять» — раунд без изгнаний."

    if len(ties) > 1:
        if game.phase is Phase.TIEBREAK or game.tie_attempts >= 1:
            return random.choice(ties), False, "⚖️ Повторная ничья — решает жребий."
        game.tie_candidates = ties
        game.tie_attempts += 1
        names = ", ".join(f"<b>{game.players[t].safe_name}</b>" for t in ties if t in game.players)
        return None, True, f"⚖️ Ничья между {names}! Переголосование."

    return ties[0], False, ""


def kick_player_from_game(game: Game, kicked_id: int) -> str:
    player = game.players.get(kicked_id)
    if not player or not player.alive:
        return ""
    player.alive = False
    player.shielded = False
    reveal_all_cards(player)

    lines = [f"💀 <b>{player.safe_name}</b> изгнан(а) из бункера! Его карты раскрыты:"]
    for card in player.cards.values():
        lines.append(f"   {card.icon} <b>{escape_html(card.category_name)}:</b> "
                     f"{escape_html(shorten(card.value, 70))}")
    if player.special_card:
        sc = player.special_card
        lines.append(f"   ✨ Спецкарта: {sc.icon} {escape_html(sc.name)}")
    text = "\n".join(lines)
    game.log(f"💀 <b>{player.safe_name}</b> изгнан(а) голосованием.")
    return text


def advance_round(game: Game) -> bool:
    """True — игра продолжается (новый раунд), False — пора в эпилог."""
    reveals_in_round = sum(p.reveals_this_round for p in game.alive_players())
    if reveals_in_round == 0:
        game.consecutive_no_reveals += 1
    else:
        game.consecutive_no_reveals = 0

    game.reset_round_state()

    if game.consecutive_no_reveals >= 3:
        game.log("⚠️ Три раунда подряд никто не раскрыл ни одной карты — игра остановлена.")
        set_phase(game, Phase.EPILOGUE, timer=0)
        return False

    if game.alive_count <= game.capacity or game.current_round >= game.total_rounds:
        set_phase(game, Phase.EPILOGUE, timer=0)
        return False

    game.current_round += 1
    set_phase(game, Phase.REVEAL)
    return True


# --------------------------------------------------------------------------- #
#                         авто-ходы тестовых ботов                            #
# --------------------------------------------------------------------------- #
def process_bot_actions(game: Game) -> List[str]:
    """Выполняет ходы за ботов в текущей фазе. -> список публичных сообщений."""
    logs: List[str] = []
    alive_bots = [p for p in game.alive_players() if p.is_bot]
    if not alive_bots:
        return logs

    if game.phase is Phase.REVEAL:
        limit = reveals_allowed(game)
        for b in alive_bots:
            while b.reveals_this_round < limit and b.hidden_cards():
                card = random.choice(b.hidden_cards())
                ok, _, public = reveal_player_card(game, b.user_id, card.category_id)
                if not ok:
                    break
                if public:
                    logs.append(public)

    elif game.phase is Phase.DISCUSSION:
        for b in alive_bots:
            if not b.has_skipped:
                register_skip(game, b.user_id)

    elif game.phase.is_voting:
        for b in alive_bots:
            if b.user_id in game.votes:
                continue
            targets = [t for t in allowed_targets(game, b.user_id) if t != 0]
            if not targets:
                targets = allowed_targets(game, b.user_id)
            if targets:
                ok, _, public = cast_vote(game, b.user_id, random.choice(targets))
                if ok and public:
                    logs.append(public)
    return logs


# --------------------------------------------------------------------------- #
#                                 эпилог                                      #
# --------------------------------------------------------------------------- #
KEY_ROLES = (
    ("медицина", 15, ("хирург", "врач", "медиц", "фельдшер")),
    ("техника", 15, ("инженер", "сварщик", "механик", "сантехник", "электрик")),
    ("продовольствие", 10, ("агроном", "фермер", "повар", "охотник")),
)
SEVERE_HEALTH = ("диабет", "сердц", "астма", "порок", "туберкул", "рак", "вич", "диализ")


def _survivor_values(survivors: List[Player], cat_id: str) -> List[str]:
    return [p.cards[cat_id].value for p in survivors if cat_id in p.cards]


def _apply_scenario_weights(game: Game, survivors: List[Player]) -> Tuple[int, List[str], List[str]]:
    delta, pros, cons = 0, [], []
    if not game.scenario:
        return delta, pros, cons
    for key, mod in (game.scenario.weights or {}).items():
        cat_id, _, needle = key.partition(":")
        if not needle:
            continue
        needle_l = needle.lower()
        if not any(needle_l in v.lower() for v in _survivor_values(survivors, cat_id)):
            continue
        delta += mod * 3
        (pros if mod > 0 else cons).append(f"{escape_html(needle)} ({mod:+d})")
    return delta, pros, cons


def calculate_epilogue(game: Game) -> str:
    sc = game.scenario
    if sc is None:
        return "📖 Эпилог недоступен: сценарий не был выбран."

    survivors = game.alive_players()
    for p in game.players.values():
        reveal_all_cards(p)

    if not survivors:
        return (f"📖 <b>ЭПИЛОГ · {escape_html(sc.title)}</b>\n"
                f"💀 Бункер «{escape_html(sc.bunker_name)}» остался пустым — выживших нет.")

    score = 50
    strengths: List[str] = []
    weaknesses: List[str] = []

    professions = " | ".join(_survivor_values(survivors, "profession")).lower()
    for label, bonus, keywords in KEY_ROLES:
        if any(k in professions for k in keywords):
            score += bonus
            strengths.append(f"есть специалист: {label}")
        elif label != "продовольствие":
            score -= bonus
            weaknesses.append(f"нет специалиста: {label}")

    sick = sum(1 for h in _survivor_values(survivors, "health")
               if any(k in h.lower() for k in SEVERE_HEALTH))
    if sick:
        score -= sick * 8
        weaknesses.append(f"тяжелобольных: {sick}")

    w_delta, w_pros, w_cons = _apply_scenario_weights(game, survivors)
    score += w_delta
    strengths.extend(w_pros)
    weaknesses.extend(w_cons)

    if len(survivors) > game.capacity:
        over = len(survivors) - game.capacity
        score -= over * 10
        weaknesses.append(f"перенаселение бункера (+{over} чел.)")

    score = max(5, min(99, score))

    lines = [
        f"📖 <b>ФИНАЛЬНЫЙ ЭПИЛОГ · {sc.duration_years} ГОД(А) ПОД ЗЕМЛЁЙ</b>",
        "━" * 18,
        f"{sc.icon} <b>{escape_html(sc.title)}</b> · {escape_html(sc.bunker_name)}",
        "",
        "🚪 <b>Выжившие:</b>",
    ]
    for p in survivors:
        prof = p.cards["profession"].value if "profession" in p.cards else "без профессии"
        lines.append(f"• 👤 <b>{p.safe_name}</b> — {escape_html(shorten(prof, 50))}")

    if game.dead_players():
        lines.append("")
        lines.append("💀 <b>Изгнаны:</b> " + ", ".join(p.safe_name for p in game.dead_players()))

    lines += [
        "",
        f"📊 <b>Шанс выживания группы:</b> {score}%",
        f"✅ <b>Сильные стороны:</b> {', '.join(strengths) if strengths else 'минимальные'}",
        f"⚠️ <b>Слабые стороны:</b> {', '.join(weaknesses) if weaknesses else 'не выявлены'}",
        "━" * 18,
    ]

    if score >= 70:
        lines.append(f"🎉 <b>УСПЕХ!</b> Бункер пережил «{escape_html(sc.title)}»!")
    else:
        lines.append("💀 <b>ТРАГЕДИЯ!</b> Группа не дожила до открытия дверей.")

    rats = [p for p in survivors if p.is_rat]
    if rats and score < 70:
        lines.append("\n🐀 <b>Крыса победила:</b> " + ", ".join(p.safe_name for p in rats))

    return "\n".join(lines)
