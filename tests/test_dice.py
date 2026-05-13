import pytest
import secrets

def test_dice_odds():
    rand = secrets.SystemRandom()
    wins = 0
    losses = 0
    for _ in range(10000):
        is_win = rand.randint(1, 100) <= 35
        while True:
            player_roll = rand.randint(1, 6)
            bot_roll = rand.randint(1, 6)
            if is_win and player_roll > bot_roll:
                break
            elif not is_win and player_roll < bot_roll:
                break
        if player_roll > bot_roll:
            wins += 1
        elif player_roll < bot_roll:
            losses += 1

    win_rate = wins / 10000.0
    loss_rate = losses / 10000.0

    assert 0.33 <= win_rate <= 0.37
    assert 0.63 <= loss_rate <= 0.67
