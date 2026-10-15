"""Карты в компактном виде: 'As', 'Td', '9h' (ранг + масть)."""
import secrets
from collections import Counter

RANKS = "23456789TJQKA"
SUITS = "shdc"
rng = secrets.SystemRandom()


def draw() -> str:
    """Карта из «бесконечной колоды» (как в старом /bj)."""
    return rng.choice(RANKS) + rng.choice(SUITS)


def deck() -> list:
    cards = [r + s for r in RANKS for s in SUITS]
    rng.shuffle(cards)
    return cards


def bj_value(card: str) -> int:
    r = card[0]
    if r == "A":
        return 11
    if r in "TJQK":
        return 10
    return int(r)


def bj_score(cards: list) -> tuple[int, bool]:
    """(очки, мягкая ли рука)."""
    total = sum(bj_value(c) for c in cards)
    aces = sum(1 for c in cards if c[0] == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def is_blackjack(cards: list) -> bool:
    return len(cards) == 2 and bj_score(cards)[0] == 21


def bac_value(card: str) -> int:
    r = card[0]
    if r == "A":
        return 1
    if r in "TJQK":
        return 0
    return int(r)


def bac_score(cards: list) -> int:
    return sum(bac_value(c) for c in cards) % 10


POKER_PAYTABLE = [
    ("royal", "Роял-флеш", 250), ("sflush", "Стрит-флеш", 50), ("four", "Каре", 25),
    ("full", "Фулл-хаус", 9), ("flush", "Флеш", 5), ("straight", "Стрит", 4),
    ("three", "Сет", 3), ("twopair", "Две пары", 2), ("jacks", "Пара от валетов", 1),
]
POKER_PAY = {k: (name, mult) for k, name, mult in POKER_PAYTABLE}


def poker_rank(hand: list) -> str | None:
    values = sorted((RANKS.index(c[0]) + 2 for c in hand), reverse=True)
    counts = Counter(values)
    shape = sorted(counts.values(), reverse=True)
    flush = len({c[1] for c in hand}) == 1
    uniq = sorted(set(values))
    straight = len(uniq) == 5 and (uniq[-1] - uniq[0] == 4 or uniq == [2, 3, 4, 5, 14])
    if straight and flush:
        return "royal" if uniq[0] == 10 else "sflush"
    if shape[0] == 4:
        return "four"
    if shape == [3, 2]:
        return "full"
    if flush:
        return "flush"
    if straight:
        return "straight"
    if shape[0] == 3:
        return "three"
    if shape == [2, 2, 1]:
        return "twopair"
    if shape[0] == 2 and any(v >= 11 for v, n in counts.items() if n == 2):
        return "jacks"
    return None
