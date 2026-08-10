# bunker/deck.py
from __future__ import annotations

import random
from dataclasses import replace
from typing import Dict, List, Sequence, TypeVar

from bunker.data import (
    BAGGAGE, BIOLOGY, CATEGORIES, FACTS_1, FACTS_2, GENDER_AGE,
    HEALTH_CONDITIONS, HOBBIES, PHOBIAS, PROFESSIONS, SPECIAL_CARDS_POOL, TRAITS,
)
from bunker.models import Card, SpecialCard

T = TypeVar("T")

_POOLS: Dict[str, Sequence[str]] = {
    "gender_age": GENDER_AGE,
    "health": HEALTH_CONDITIONS,
    "profession": PROFESSIONS,
    "trait": TRAITS,
    "hobby": HOBBIES,
    "baggage": BAGGAGE,
    "fact1": FACTS_1,
    "fact2": FACTS_2,
    "phobia": PHOBIAS,
    "biology": BIOLOGY,
}


def _draw(pool: Sequence[T], count: int) -> List[T]:
    """Тянет count элементов без повторов, пока хватает пула (потом — по кругу)."""
    if count <= 0:
        return []
    items = list(pool) or []
    if not items:
        raise ValueError("Пустой пул карт")
    out: List[T] = []
    while len(out) < count:
        need = min(len(items), count - len(out))
        out.extend(random.sample(items, need))
    return out


def deal_hands(player_count: int) -> List[Dict[str, Card]]:
    """
    Раздаёт руки сразу всем игрокам: внутри одной категории значения
    не повторяются, пока хватает пула (раньше могло быть 4 «Хирурга»).
    """
    if player_count <= 0:
        return []
    hands: List[Dict[str, Card]] = [{} for _ in range(player_count)]
    for cat_id, cat_name, icon in CATEGORIES:
        values = _draw(_POOLS.get(cat_id) or ["Неизвестно"], player_count)
        random.shuffle(values)
        for hand, value in zip(hands, values):
            hand[cat_id] = Card(
                category_id=cat_id,
                category_name=cat_name,
                value=value,
                icon=icon,
                revealed=False,
            )
    return hands


def deal_special_cards(count: int) -> List[SpecialCard]:
    """Копии (replace), иначе used=True «протекал» бы в глобальный пул."""
    return [replace(sc, used=False) for sc in _draw(SPECIAL_CARDS_POOL, count)]


# --- обратная совместимость со старым API ---------------------------------- #
def generate_player_cards() -> Dict[str, Card]:
    return deal_hands(1)[0]


def generate_special_card() -> SpecialCard:
    return deal_special_cards(1)[0]
