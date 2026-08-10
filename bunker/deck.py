# bunker/deck.py
"""Раздача карт. Значения внутри категории не повторяются у игроков."""
from __future__ import annotations

import random
from dataclasses import replace
from typing import Dict, List, Optional

from bunker.data import CATEGORIES, CATEGORY_POOLS, SPECIAL_CARDS_POOL
from bunker.models import Card, SpecialCard


def _unique_sample(pool: List[str], n: int) -> List[str]:
    values = list(dict.fromkeys(pool))
    if not values:
        return ["данные утеряны"] * n
    random.shuffle(values)
    out = values[:n]
    while len(out) < n:                     # игроков больше, чем карт в категории
        extra = values[:]
        random.shuffle(extra)
        out.extend(extra[: n - len(out)])
    return out


def deal_hands(num_players: int) -> List[Dict[str, Card]]:
    hands: List[Dict[str, Card]] = [{} for _ in range(num_players)]
    for cat_id, cat_name, icon in CATEGORIES:
        for hand, value in zip(hands, _unique_sample(CATEGORY_POOLS.get(cat_id, []), num_players)):
            hand[cat_id] = Card(cat_id, cat_name, value, icon)
    return hands


def deal_special_cards(num_players: int) -> List[Optional[SpecialCard]]:
    if not SPECIAL_CARDS_POOL:
        return [None] * num_players
    out: List[Optional[SpecialCard]] = []
    pool: List[SpecialCard] = []
    for _ in range(num_players):
        if not pool:
            pool = [replace(c) for c in SPECIAL_CARDS_POOL]
            random.shuffle(pool)
        out.append(pool.pop())
    return out


def random_value_for(cat_id: str, exclude: set[str]) -> str:
    pool = [v for v in CATEGORY_POOLS.get(cat_id, []) if v not in exclude]
    if not pool:
        pool = CATEGORY_POOLS.get(cat_id, ["данные утеряны"])
    return random.choice(pool)
