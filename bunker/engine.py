# bunker/engine.py
import random
import time
from typing import Dict, List, Tuple, Optional
from bunker.models import Game, Player, Phase, Scenario
from bunker.data import SCENARIOS
from bunker.deck import generate_player_cards, generate_special_card

# Хранилище активных игр в памяти: {game_id: Game}
active_games: Dict[str, Game] = {}

def create_new_game(game_id: str, chat_id: int, host_id: int, host_name: str) -> Game:
    """Создаёт новую игру в режиме лобби."""
    game = Game(
        game_id=game_id,
        chat_id=chat_id,
        host_id=host_id,
        host_name=host_name,
        phase=Phase.LOBBY,
        created_at=time.time()
    )
    active_games[game_id] = game
    return game

def get_game(game_id: str) -> Optional[Game]:
    """Возвращает активную игру по game_id."""
    return active_games.get(game_id)

def get_game_by_chat(chat_id: int) -> Optional[Game]:
    """Возвращает активную игру для конкретного чата."""
    for g in active_games.values():
        if g.chat_id == chat_id and g.phase != Phase.FINISHED:
            return g
    return None

def start_game_engine(game: Game) -> bool:
    """Запускает партию, распределяет карты и вычисляет вместимость бункера."""
    if len(game.players) < 2:
        return False
        
    game.scenario = random.choice(SCENARIOS)
    count = len(game.players)
    
    # Расчёт мест в бункере: примерно половина участников
    game.capacity = max(1, count // 2)
    game.total_rounds = count - game.capacity
    game.current_round = 1
    
    # Выдача карт игрокам
    for idx, player in enumerate(game.players.values(), 1):
        player.seat = idx
        player.cards = generate_player_cards()
        player.special_card = generate_special_card()
        player.alive = True
        
    game.phase = Phase.INTRO
    game.timer_seconds = 45
    game.logs.append(f"Выбран сценарий: {game.scenario.title}. Мест в бункере: {game.capacity}.")
    return True

def reveal_player_card(game: Game, user_id: int, cat_id: str) -> Tuple[bool, str]:
    """Раскрывает указанную карту игрока."""
    player = game.players.get(user_id)
    if not player or not player.alive:
        return False, "Вы не можете производить действия."

    card = player.cards.get(cat_id)
    if not card:
        return False, "Карта не найдена."
        
    if card.revealed:
        return False, "Эта карта уже раскрыта."

    card.revealed = True
    game.logs.append(f"👤 {player.name} раскрыл карту {card.icon} <b>{card.category_name}</b>: {card.value}")
    return True, f"Карта {card.category_name} успешно раскрыта!"

def cast_vote(game: Game, voter_id: int, target_id: int) -> Tuple[bool, str]:
    """Регистрирует голос игрока."""
    if game.phase not in [Phase.VOTING, Phase.TIEBREAK]:
        return False, "Сейчас не фаза голосования."

    voter = game.players.get(voter_id)
    target = game.players.get(target_id)

    if not voter or not voter.alive:
        return False, "Вы не участвуете в голосовании."

    if not target or not target.alive:
        return False, "Нельзя проголосовать за этого игрока."

    voter.voted_for = target_id
    game.votes[voter_id] = target_id
    game.logs.append(f"🗳 {voter.name} проголосовал.")
    return True, f"Ваш голос за {target.name} принят!"

def check_voting_complete(game: Game) -> bool:
    """Проверяет, все ли живые игроки проголосовали."""
    alive_players = [p for p in game.players.values() if p.alive]
    return len(game.votes) >= len(alive_players)

def process_voting_results(game: Game) -> Tuple[Optional[int], bool]:
    """
    Подсчитывает итоги голосования.
    Возвращает (kicked_user_id, is_tie).
    """
    tally: Dict[int, float] = {}
    for voter_id, target_id in game.votes.items():
        voter = game.players.get(voter_id)
        weight = voter.vote_weight if voter else 1.0
        tally[target_id] = tally.get(target_id, 0.0) + weight

    if not tally:
        # Если никто не проголосовал — выбираем случайного
        alive_ids = [p.user_id for p in game.players.values() if p.alive]
        kicked_id = random.choice(alive_ids)
        return kicked_id, False

    sorted_tally = sorted(tally.items(), key=lambda x: x[1], reverse=True)
    top_target, top_votes = sorted_tally[0]

    # Проверка на ничью
    ties = [tid for tid, vcount in sorted_tally if vcount == top_votes]

    if len(ties) > 1:
        game.tie_candidates = ties
        return None, True  # Ничья
        
    return top_target, False

def kick_player_from_game(game: Game, kicked_id: int) -> str:
    """Изгоняет игрока из бункера."""
    player = game.players.get(kicked_id)
    if player:
        player.alive = False
        game.logs.append(f"💀 Игрок <b>{player.name}</b> был изгнан голосованием из бункера!")
        return f"💀 Игрок {player.name} изгнан из бункера!"
    return ""

def calculate_epilogue(game: Game) -> str:
    """Генерирует связный эпилог и подсчитывает процент выживаемости бункера."""
    sc = game.scenario
    survivors = [p for p in game.players.values() if p.alive]
    
    score = 60  # Базовый балл выживания
    
    strengths = []
    weaknesses = []

    # Анализ профессий выживших
    professions = [p.cards.get("profession").value if p.cards.get("profession") else "" for p in survivors]
    healths = [p.cards.get("health").value if p.cards.get("health") else "" for p in survivors]

    # Проверка ключевых ролей
    has_medic = any("Хирург" in pr or "Врач" in pr for pr in professions)
    has_engineer = any("Инженер" in pr or "Сварщик" in pr or "Механик" in pr for pr in professions)
    has_agronomy = any("Агроном" in pr or "Фермер" in pr for pr in professions)

    if has_medic:
        score += 15
        strengths.append("Медицинское обеспечение (есть квалифицированный врач)")
    else:
        score -= 15
        weaknesses.append("Отсутствие врача (любая эпидемия губительна)")

    if has_engineer:
        score += 15
        strengths.append("Техническое обслуживание оборудования")
    else:
        score -= 15
        weaknesses.append("Отсутствие инженера (оборудование ломается)")

    if has_agronomy:
        score += 10
        strengths.append("Продовольственная независимость")

    # Учёт тяжелых болезней
    sick_count = sum(1 for h in healths if "диабет" in h.lower() or "сердца" in h.lower() or "астма" in h.lower())
    if sick_count > 0:
        score -= (sick_count * 8)
        weaknesses.append(f"Наличие тяжелобольных в изолированном пространстве ({sick_count} чел.)")

    score = max(5, min(100, score))

    text = (
        f"📖 <b>ФИНАЛЬНЫЙ ЭПИЛОГ · {sc.duration_years} ЛЕТ СТИХИИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚪 <b>Выжившие в бункере:</b>\n"
    )
    for p in survivors:
        prof = p.cards['profession'].value if 'profession' in p.cards else 'Без профессии'
        text += f"• 👤 <b>{p.name}</b> ({prof})\n"

    text += (
        f"\n📊 <b>Шанс выживания группы:</b> {score}%\n\n"
        f"✅ <b>Сильные стороны:</b> {', '.join(strengths) if strengths else 'Минимальные'}\n"
        f"⚠️ <b>Слабые стороны:</b> {', '.join(weaknesses) if weaknesses else 'Не выявлены'}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if score >= 70:
        text += f"🎉 <b>УСПЕХ!</b> Бункер успешно пережил катастрофу «{sc.title}» и открыл двери в новый мир!"
    else:
        text += f"💀 <b>ТРАГЕДИЯ!</b> Группа столкнулась с неустранимыми проблемами в бункере и не смогла дожить до открытия."

    return text
