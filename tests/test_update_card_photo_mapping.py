import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

# --- 100 ТЕСТОВ ПРИВЯЗКИ И ПРОВЕРКИ 200 ФОТОКАРТОЧЕК МОРСКИХ СВИНОК ---

@pytest.mark.parametrize("card_num", range(1, 101))
def test_find_card_photo_mapping_first_100(card_num):
    """Тест сопоставления первых 100 карточек коллекции с реальными фото в assets/cards/guinea_pigs/ (100 тестов)"""
    from cards_system import find_card_photo

    card_id = f"meme_{card_num}"
    photo_path = find_card_photo(card_id)

    assert photo_path is not None
    assert os.path.exists(photo_path)
    assert photo_path.endswith(".jpg")
    assert "guinea_pigs" in photo_path


@pytest.mark.parametrize("card_num", range(101, 201))
def test_find_card_photo_mapping_second_100(card_num):
    """Тест сопоставления карточек с 101 по 200 коллекции с реальными фото в assets/cards/guinea_pigs/ (100 тестов)"""
    from cards_system import find_card_photo

    card_id = f"meme_{card_num}"
    photo_path = find_card_photo(card_id)

    assert photo_path is not None
    assert os.path.exists(photo_path)
    assert photo_path.endswith(".jpg")
    assert "guinea_pigs" in photo_path
