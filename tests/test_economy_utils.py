import unittest
import sys
from unittest.mock import patch, MagicMock

# Мокаем firebase_admin и firestore_async для локальных тестов
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()

from economy_utils import calculate_transfer_tax, calculate_progressive_tax

class TestEconomyUtils(unittest.TestCase):

    def test_calculate_transfer_tax_standard(self):
        # Тестирование стандартного поведения (без герпеса)
        # base_tax 10, balance 0 -> progressive_tax = 10
        tax = calculate_transfer_tax(balance=0, base_tax=10, negotiation_skill=0, pet_id=None, active_diseases=[])
        self.assertEqual(tax, 10)

    def test_calculate_transfer_tax_with_herpes(self):
        # Тестирование поведения с болезнью герпес
        # progressive_tax = 10, но герпес делает его минимум 30
        tax = calculate_transfer_tax(balance=0, base_tax=10, negotiation_skill=0, pet_id=None, active_diseases=['herpes'])
        self.assertEqual(tax, 30)

        # Если базовый налог каким-то чудом > 30 (даже если кап 20, проверим логику max)
        tax2 = calculate_transfer_tax(balance=50000000, base_tax=40, negotiation_skill=0, pet_id=None, active_diseases=['herpes'])
        self.assertTrue(tax2 >= 30)

    def test_calculate_transfer_tax_with_pet_and_skill(self):
        # Тестируем, что аргументы neg_lvl и pet_id пробрасываются в progressive_tax
        # balance 0, base_tax 10, dog снижает на 5% -> progressive_tax = 5
        tax = calculate_transfer_tax(balance=0, base_tax=10, negotiation_skill=0, pet_id='dog', active_diseases=[])
        self.assertEqual(tax, 5)

        # skill negotiation=2 -> progressive_tax = 10 - 2 = 8
        tax2 = calculate_transfer_tax(balance=0, base_tax=10, negotiation_skill=2, pet_id=None, active_diseases=[])
        self.assertEqual(tax2, 8)

if __name__ == '__main__':
    unittest.main()
