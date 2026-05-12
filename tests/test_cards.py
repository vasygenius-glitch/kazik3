import unittest
from cards import calculate_score, format_cards, get_random_card, RANKS, SUITS

class TestCards(unittest.TestCase):

    def test_calculate_score_no_aces(self):
        # Обычные карты без перебора
        cards = [{'rank': '10', 'suit': '♠'}, {'rank': '5', 'suit': '♥'}]
        self.assertEqual(calculate_score(cards), 15)

        cards = [{'rank': 'K', 'suit': '♦'}, {'rank': 'Q', 'suit': '♣'}, {'rank': '2', 'suit': '♠'}]
        self.assertEqual(calculate_score(cards), 22) # Просто перебор без тузов

    def test_calculate_score_with_aces(self):
        # Один туз, нет перебора (A = 11)
        cards = [{'rank': 'A', 'suit': '♠'}, {'rank': '9', 'suit': '♥'}]
        self.assertEqual(calculate_score(cards), 20)

        # Два туза, перебор с одним 11 (11 + 1 = 12)
        cards = [{'rank': 'A', 'suit': '♠'}, {'rank': 'A', 'suit': '♥'}]
        self.assertEqual(calculate_score(cards), 12)

        # Туз, который должен стать 1 из-за других карт (10 + 5 + 1 = 16)
        cards = [{'rank': '10', 'suit': '♠'}, {'rank': '5', 'suit': '♥'}, {'rank': 'A', 'suit': '♦'}]
        self.assertEqual(calculate_score(cards), 16)

        # Много тузов (11 + 1 + 1 + 1 = 14)
        cards = [{'rank': 'A', 'suit': '♠'}, {'rank': 'A', 'suit': '♥'}, {'rank': 'A', 'suit': '♦'}, {'rank': 'A', 'suit': '♣'}]
        self.assertEqual(calculate_score(cards), 14)

    def test_format_cards(self):
        cards = [{'rank': '10', 'suit': '♠'}, {'rank': 'A', 'suit': '♥'}]
        self.assertEqual(format_cards(cards), "10♠ A♥")

        cards = []
        self.assertEqual(format_cards(cards), "")

    def test_get_random_card(self):
        card = get_random_card()

        # Проверяем структуру
        self.assertIsInstance(card, dict)
        self.assertIn('rank', card)
        self.assertIn('suit', card)

        # Проверяем значения
        self.assertIn(card['rank'], RANKS)
        self.assertIn(card['suit'], SUITS)

if __name__ == '__main__':
    unittest.main()
