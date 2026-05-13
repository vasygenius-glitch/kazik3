import pytest
import secrets

def test_roulette_odds():
    rand = secrets.SystemRandom()
    wins = 0
    losses = 0
    for _ in range(10000):
        guess = rand.randint(1, 36)

        is_win = rand.randint(1, 100) <= 35
        while True:
            result_number = rand.randint(1, 36)
            diff = abs(result_number - guess)
            if is_win and diff <= 4:
                break
            elif not is_win and diff > 4:
                break

        diff = abs(result_number - guess)
        if diff <= 4:
            wins += 1
        else:
            losses += 1

    win_rate = wins / 10000.0
    loss_rate = losses / 10000.0

    assert 0.33 <= win_rate <= 0.37
    assert 0.63 <= loss_rate <= 0.67
