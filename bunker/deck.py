# bunker/deck.py
import random
from typing import Dict, List
from bunker.models import Card, SpecialCard
from bunker.data import (
    CATEGORIES, PROFEESIONS, HEALTH_CONDITIONS, GENDER_AGE,
    TRAITS, HOBBIES, BAGGAGE, FACTS_1, FACTS_2, PHOBIAS, BIOLOGY,
    SPECIAL_CARDS_POOL
)

def generate_player_cards() -> Dict[str, Card]:
    """Генерирует набор из 10 базовых характеристик для одного игрока."""
    cards = {}
    
    pools = {
        "gender_age": GENDER_AGE,
        "health": HEALTH_CONDITIONS,
        "profession": PROFEESIONS,
        "trait": TRAITS,
        "hobby": HOBBIES,
        "baggage": BAGGAGE,
        "fact1": FACTS_1,
        "fact2": FACTS_2,
        "phobia": PHOBIAS,
        "biology": BIOLOGY,
    }
    
    for cat_id, cat_name, icon in CATEGORIES:
        pool = pools.get(cat_id, ["Неизвестно"])
        val = random.choice(pool)
        cards[cat_id] = Card(
            category_id=cat_id,
            category_name=cat_name,
            value=val,
            icon=icon,
            revealed=False
        )
        
    return cards

def generate_special_card() -> SpecialCard:
    """Выдаёт 1 случайную спецкарту."""
    sc = random.choice(SPECIAL_CARDS_POOL)
    return SpecialCard(
        id=sc.id,
        name=sc.name,
        icon=sc.icon,
        description=sc.description,
        used=False
    )
