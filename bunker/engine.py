# bunker/engine.py
from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Tuple

from bunker.data import SCENARIOS
from bunker.deck import deal_hands, deal_special_cards
from bunker.models import (
    MAX_PLAYERS, MIN_PLAYERS, Game, Phase, Player, escape_html,
)

# Хранилище активных игр в памяти: {game_id: Game}
active_games: Dict[str, Game] = {}

GAME_TTL_SECONDS = 6 * 3600          # игру без активности 6 часов считаем брошенной
REVEALS_PER_ROUND = {1: 2}           # в первом раунде вскрывают 2 карты, далее — 1
DEFAULT_REVEALS = 1

PHASE_TIMERS: Dict[Phase, int] = {
    Phase.INTRO: 45,
    Phase.REVEAL: 90,
    Phase.DISCUSSION: 120,
    Phase.DEFENSE: 60,
    Phase.VOTING: 60,
    Phase.TIEBREAK: 45,
    Phase.KICK: 10,
    Phase.EPILOGUE: 0,
    Phase.FINISHED: 0,
}


# --------------------------------------------------------------------------- #
#                            жизненный цикл игры                              #
# --------------------------------------------------------------------------- #
def create_new_game(game_id: str, chat_id: int, host_id: int, host_name: str) -> Game:
    """Создаёт новую игру в режиме лобби (и подчищает мусор)."""
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
    """Возвращает незавершённую игру чата (самую свежую)."""
    candidates = [
        g for g in active_games.values()
        if g.chat_id == chat_id and g.phase is not Phase.FINISHED
    ]
    return max(candidates, key=lambda g: g.created_at, default=None)


def drop_game(game_id: str) -> None:
    active_games.pop(game_id, None)


def cleanup_stale_games(now: Optional[float] = None) -> int:
    """Удаляет завершённые и заброшенные игры — иначе active_games течёт."""
    now = now or time.time()
    stale = [
        gid for gid, g in active_games.items()
        if g.phase is Phase.FINISHED or (now - g.updated_at) > GAME_TTL_SECONDS
    ]
    for gid in stale:
        del active_games[gid]
    return len(stale)


# --------------------------------------------------------------------------- #
#                                   лобби                                     #
# --------------------------------------------------------------------------- #
BOT_NAMES = [
    "🤖 Бот Ева", "🤖 Бот Валли", "🤖 Бот Т-800", "🤖 Бот Джарвис",
    "🤖 Бот Бэндер", "🤖 Бот Марвин", "🤖 Бот HAL-9000", "🤖 Бот R2-D2",
    "🤖 Бот C-3PO", "🤖 Бот Оптимус", "🤖 Бот Альтрон", "🤖 Бот Аэлита"
]

def add_player(game: Game, user_id: int, name: str, username: str = "", is_bot: bool = False) -> Tuple[bool, str]:
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

def add_test_bot(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Добавлять ботов можно только в лобби."
    if len(game.players) >= MAX_PLAYERS:
        return False, f"Лобби заполнено (максимум {MAX_PLAYERS} игроков)."

    existing_names = {p.name for p in game.players.values()}
    available_names = [n for n in BOT_NAMES if n not in existing_names]
    bot_name = available_names[0] if available_names else f"🤖 Бот #{len(game.players) + 1}"

    bot_uid = 990000 + len(game.players) + random.randint(1, 9999)
    while bot_uid in game.players:
        bot_uid += 1

    return add_player(game, bot_uid, bot_name, "bot", is_bot=True)

def remove_test_bot(game: Game) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Удалять ботов можно только до старта игры."

    bot_players = [p for p in game.players.values() if p.is_bot]
    if not bot_players:
        return False, "В лобби нет тестовых ботов."

    last_bot = bot_players[-1]
    return remove_player(game, last_bot.user_id)

def process_bot_actions(game: Game) -> List[str]:
    """Автоматически выполняет действия за тестовых ИИ-ботов в текущей фазе."""
    logs = []
    alive_bots = [p for p in game.alive_players() if p.is_bot]
    if not alive_bots:
        return logs

    if game.phase is Phase.REVEAL:
        limit = reveals_allowed(game)
        for bot in alive_bots:
            if bot.reveals_this_round < limit:
                hidden = bot.hidden_cards()
                if hidden:
                    card_to_rev = random.choice(hidden)
                    ok, msg = reveal_player_card(game, bot.user_id, card_to_rev.category_id)
                    if ok:
                        logs.append(msg)

    elif game.phase is Phase.DISCUSSION:
        for bot in alive_bots:
            if not bot.has_skipped:
                register_skip(game, bot.user_id)

    elif game.phase.is_voting:
        for bot in alive_bots:
            if bot.user_id not in game.votes:
                targets = allowed_targets(game, bot.user_id)
                if targets:
                    target_id = random.choice(targets)
                    ok, msg = cast_vote(game, bot.user_id, target_id)
                    if ok:
                        logs.append(msg)

    return logs


def remove_player(game: Game, user_id: int) -> Tuple[bool, str]:
    if game.phase is not Phase.LOBBY:
        return False, "Выйти можно только до старта игры."
    player = game.players.pop(user_id, None)
    if player is None:
        return False, "Вас нет в лобби."

    # переназначаем места, чтобы не было дыр в нумерации
    for idx, p in enumerate(game.players.values(), 1):
        p.seat = idx

    # если ушёл организатор — передаём права следующему
    if user_id == game.host_id and game.players:
        new_host = next(iter(game.players.values()))
        game.host_id = new_host.user_id
        game.host_name = new_host.name
        game.log(f"👑 Новый организатор: <b>{new_host.safe_name}</b>")

    game.touch()
    return True, "Вы покинули лобби."


# --------------------------------------------------------------------------- #
#                                  старт                                      #
# --------------------------------------------------------------------------- #
def set_phase(game: Game, phase: Phase, timer: Optional[int] = None) -> None:
    game.phase = phase
    game.timer_seconds = PHASE_TIMERS.get(phase, 60) if timer is None else timer
    game.phase_deadline = time.time() + game.timer_seconds if game.timer_seconds else 0.0
    game.touch()


from bunker.data import (
    CATEGORIES, PROFESSIONS, HEALTH_CONDITIONS, GENDER_AGE,
    TRAITS, HOBBIES, BAGGAGE, FACTS_1, FACTS_2, PHOBIAS, BIOLOGY,
    SPECIAL_CARDS_POOL, SCENARIOS, calculate_bunker_capacity
)

def start_game_engine(game: Game) -> Tuple[bool, str]:
    """Запускает партию, раздаёт карты и вычисляет вместимость бункера."""
    if game.phase is not Phase.LOBBY:
        return False, "Игра уже запущена."

    count = len(game.players)
    if count < MIN_PLAYERS:
        return False, f"Нужно минимум {MIN_PLAYERS} игрока для старта."
    if not SCENARIOS:
        return False, "Не найдено ни одного сценария (проверьте data.py)."

    game.scenario = random.choice(SCENARIOS)
    game.capacity = calculate_bunker_capacity(count)
    game.total_rounds = max(1, count - game.capacity)
    game.current_round = 1

    hands = deal_hands(count)
    specials = deal_special_cards(count)

    for idx, (player, hand, special) in enumerate(
        zip(game.players.values(), hands, specials), 1
    ):
        player.seat = idx
        player.cards = hand
        player.special_card = special
        player.is_rat = special.id == "rat"
        player.alive = True
        player.reset_round_state()

    game.reset_round_state()
    set_phase(game, Phase.INTRO)
    game.log(
        f"{game.scenario.icon} Сценарий: <b>{escape_html(game.scenario.title)}</b>. "
        f"Мест в бункере: {game.capacity} из {count}."
    )
    return True, "Игра началась!"


# --------------------------------------------------------------------------- #
#                            раскрытие карт                                   #
# --------------------------------------------------------------------------- #
def reveals_allowed(game: Game) -> int:
    return REVEALS_PER_ROUND.get(game.current_round, DEFAULT_REVEALS)


def reveal_player_card(game: Game, user_id: int, cat_id: str) -> Tuple[bool, str]:
    """Раскрывает указанную карту игрока (с проверкой фазы и лимита)."""
    if game.phase is not Phase.REVEAL:
        return False, "Сейчас не фаза раскрытия карт."

    player = game.players.get(user_id)
    if player is None:
        return False, "Вы не участвуете в этой игре."
    if not player.alive:
        return False, "Изгнанные игроки не раскрывают карты."

    limit = reveals_allowed(game)
    if player.reveals_this_round >= limit:
        return False, f"В этом раунде вы уже раскрыли карт: {limit}."

    card = player.cards.get(cat_id)
    if card is None:
        return False, "Карта не найдена."
    if card.revealed:
        return False, "Эта карта уже раскрыта."

    card.revealed = True
    player.reveals_this_round += 1
    game.log(
        f"👤 <b>{player.safe_name}</b> раскрыл {card.icon} "
        f"<b>{escape_html(card.category_name)}</b>: {escape_html(card.value)}"
    )
    return True, f"Карта «{card.category_name}» раскрыта!"


def check_reveal_complete(game: Game) -> bool:
    limit = reveals_allowed(game)
    return all(
        p.reveals_this_round >= limit or not p.hidden_cards()
        for p in game.alive_players()
    )


def register_skip(game: Game, user_id: int) -> Tuple[bool, str, bool]:
    """Голос за досрочное завершение обсуждения. -> (ok, текст, все_пропустили)"""
    if game.phase is not Phase.DISCUSSION:
        return False, "Сейчас нет обсуждения.", False
    player = game.players.get(user_id)
    if not player or not player.alive:
        return False, "Вы не участвуете в обсуждении.", False
    if player.has_skipped:
        return False, "Вы уже пропустили обсуждение.", False

    player.has_skipped = True
    alive = game.alive_players()
    done = all(p.has_skipped for p in alive)
    game.touch()
    return True, "Ваш голос за пропуск учтён.", done


# --------------------------------------------------------------------------- #
#                              голосование                                    #
# --------------------------------------------------------------------------- #
def allowed_targets(game: Game, voter_id: int) -> List[int]:
    """Кого можно выбрать: живые, кроме себя; + 0 (Пропустить изгнание)."""
    targets = [p.user_id for p in game.alive_players() if p.user_id != voter_id]
    if game.phase is Phase.TIEBREAK and game.tie_candidates:
        allowed = set(game.tie_candidates)
        targets = [t for t in targets if t in allowed]
    else:
        targets.append(0)  # 0 = Никого не изгонять
    return targets


def cast_vote(game: Game, voter_id: int, target_id: int) -> Tuple[bool, str]:
    """Регистрирует голос игрока."""
    if not game.phase.is_voting:
        return False, "Сейчас не фаза голосования."

    voter = game.players.get(voter_id)
    if not voter or not voter.alive:
        return False, "Вы не участвуете в голосовании."
    if voter_id in game.votes:
        return False, "Вы уже проголосовали."
    if voter_id == target_id:
        return False, "Голосовать за себя нельзя."

    if target_id != 0:
        target = game.players.get(target_id)
        if not target or not target.alive:
            return False, "Нельзя проголосовать за этого игрока."
        if target_id not in allowed_targets(game, voter_id):
            return False, "В переголосовании можно выбирать только спорных кандидатов."
        target_name = target.name
    else:
        target_name = "«Никого не изгонять»"

    voter.voted_for = target_id
    game.votes[voter_id] = target_id
    game.log(f"🗳 <b>{voter.safe_name}</b> проголосовал.")
    return True, f"Ваш голос за {target_name} принят!"


def check_voting_complete(game: Game) -> bool:
    """Учитываем только голоса ЖИВЫХ игроков (мёртвые/старые голоса не считаются)."""
    alive_ids = {p.user_id for p in game.alive_players()}
    voted = alive_ids & set(game.votes)
    return len(voted) >= len(alive_ids) and bool(alive_ids)


def tally_votes(game: Game) -> Dict[int, float]:
    """Подсчёт с учётом веса голоса и «Брони» (shielded)."""
    tally: Dict[int, float] = {}
    for voter_id, target_id in game.votes.items():
        voter = game.players.get(voter_id)
        if not voter or not voter.alive:
            continue
        if target_id == 0:
            tally[0] = tally.get(0, 0.0) + max(0.0, voter.vote_weight)
            continue
        target = game.players.get(target_id)
        if not target or not target.alive or target.shielded:
            continue
        tally[target_id] = tally.get(target_id, 0.0) + max(0.0, voter.vote_weight)
    return tally


def process_voting_results(game: Game) -> Tuple[Optional[int], bool]:
    """
    Итоги голосования -> (kicked_user_id, is_tie).
    Повторная ничья решается жребием, чтобы игра не зациклилась.
    """
    tally = tally_votes(game)

    if not tally:
        pool = [p.user_id for p in game.alive_players() if not p.shielded]
        if not pool:
            return None, False
        kicked_id = random.choice(pool)
        game.log("⚠️ Голосов нет — изгнанник определён жребием.")
        return kicked_id, False

    top_votes = max(tally.values())
    ties = sorted(tid for tid, v in tally.items() if v == top_votes)

    if 0 in ties:
        game.log("⛔ Большинство проголосовало «Никого не изгонять»! Раунд завершился без изгнаний.")
        return None, False

    if len(ties) > 1:
        if game.phase is Phase.TIEBREAK or game.tie_attempts >= 1:
            kicked_id = random.choice(ties)
            game.log("⚖️ Повторная ничья — решает жребий.")
            return kicked_id, False
        game.tie_candidates = ties
        game.tie_attempts += 1
        return None, True

    return ties[0], False


def kick_player_from_game(game: Game, kicked_id: int) -> str:
    """Изгоняет игрока из бункера."""
    player = game.players.get(kicked_id)
    if not player or not player.alive:
        return ""
    player.alive = False
    player.shielded = False
    game.log(f"💀 Игрок <b>{player.safe_name}</b> изгнан голосованием!")
    return f"💀 Игрок {player.name} изгнан из бункера!"


def advance_round(game: Game) -> bool:
    """
    Переход к следующему раунду. True — игра продолжается, False — пора в эпилог.
    """
    game.reset_round_state()
    if game.alive_count <= game.capacity or game.current_round >= game.total_rounds:
        set_phase(game, Phase.EPILOGUE)
        return False
    game.current_round += 1
    set_phase(game, Phase.REVEAL)
    return True


def finish_game(game: Game) -> None:
    set_phase(game, Phase.FINISHED, timer=0)


# --------------------------------------------------------------------------- #
#                                 эпилог                                      #
# --------------------------------------------------------------------------- #
KEY_ROLES = (
    ("медицина", 15, ("хирург", "врач", "медиц")),
    ("техника", 15, ("инженер", "сварщик", "механик", "сантехник")),
    ("продовольствие", 10, ("агроном", "фермер", "повар", "охотник")),
)
SEVERE_HEALTH = ("диабет", "сердц", "астма", "порок")


def _survivor_values(survivors: List[Player], cat_id: str) -> List[str]:
    return [p.cards[cat_id].value for p in survivors if cat_id in p.cards]


def _apply_scenario_weights(game: Game, survivors: List[Player]) -> Tuple[int, List[str], List[str]]:
    """Наконец-то используем Scenario.weights: 'категория:подстрока' -> модификатор."""
    delta, pros, cons = 0, [], []
    for key, mod in (game.scenario.weights or {}).items():
        cat_id, _, needle = key.partition(":")
        if not needle:
            continue
        needle_l = needle.lower()
        matched = any(needle_l in v.lower() for v in _survivor_values(survivors, cat_id))
        if not matched:
            continue
        delta += mod * 3
        (pros if mod > 0 else cons).append(f"{escape_html(needle)} ({mod:+d})")
    return delta, pros, cons


def calculate_epilogue(game: Game) -> str:
    """Генерирует эпилог и оценивает шанс выживания группы."""
    sc = game.scenario
    if sc is None:
        return "📖 Эпилог недоступен: сценарий не был выбран."

    survivors = game.alive_players()
    if not survivors:
        return (
            f"📖 <b>ЭПИЛОГ · {escape_html(sc.title)}</b>\n"
            f"💀 Бункер «{escape_html(sc.bunker_name)}» остался пустым — выживших нет."
        )

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

    sick = sum(
        1 for h in _survivor_values(survivors, "health")
        if any(k in h.lower() for k in SEVERE_HEALTH)
    )
    if sick:
        score -= sick * 8
        weaknesses.append(f"тяжелобольных в группе: {sick}")

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
        f"📖 <b>ФИНАЛЬНЫЙ ЭПИЛОГ · {sc.duration_years} ЛЕТ ПОД ЗЕМЛЁЙ</b>",
        "━" * 18,
        f"{sc.icon} <b>{escape_html(sc.title)}</b> · {escape_html(sc.bunker_name)}",
        "",
        "🚪 <b>Выжившие:</b>",
    ]
    for p in survivors:
        prof = p.cards["profession"].value if "profession" in p.cards else "без профессии"
        lines.append(f"• 👤 <b>{p.safe_name}</b> — {escape_html(prof)}")

    lines += [
        "",
        f"📊 <b>Шанс выживания группы:</b> {score}%",
        f"✅ <b>Сильные стороны:</b> {', '.join(strengths) if strengths else 'минимальные'}",
        f"⚠️ <b>Слабые стороны:</b> {', '.join(weaknesses) if weaknesses else 'не выявлены'}",
        "━" * 18,
    ]

    if score >= 70:
        lines.append(f"🎉 <b>УСПЕХ!</b> Бункер пережил «{escape_html(sc.title)}» и открыл двери в новый мир!")
    else:
        lines.append("💀 <b>ТРАГЕДИЯ!</b> Группа не смогла дожить до открытия дверей.")

    rats = [p for p in survivors if p.is_rat]
    if rats and score < 70:
        names = ", ".join(p.safe_name for p in rats)
        lines.append(f"\n🐀 <b>Крыса победила:</b> {names} (+50% личных очков).")

    return "\n".join(lines)
