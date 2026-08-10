# tests/test_feedback.py
"""Тесты модуля обратной связи /предложение"""
import pytest
from feedback import cmd_feedback
from aiogram.types import Message, User, Chat


@pytest.mark.asyncio
async def test_feedback_empty_prompt():
    """Проверка подсказки при пустом тексте команды."""
    class DummyMessage:
        def __init__(self):
            self.text = "/предложение"
            self.from_user = User(id=100, is_bot=False, first_name="TestUser", username="testuser")
            self.chat = Chat(id=100, type="private")
            self.replies = []

        async def answer(self, text, parse_mode=None):
            self.replies.append(text)
            return self

    msg = DummyMessage()
    await cmd_feedback(msg, command=None, bot=None)
    assert len(msg.replies) == 1
    assert "Напишите свои предложения" in msg.replies[0]
    assert "Шуточные предложения будут наказываться" in msg.replies[0]


@pytest.mark.asyncio
async def test_feedback_with_text():
    """Проверка отправки предложения с текстом."""
    class DummyBot:
        def __init__(self):
            self.sent_messages = []

        async def send_message(self, chat_id, text, parse_mode=None):
            self.sent_messages.append((chat_id, text))
            return True

    class DummyMessage:
        def __init__(self):
            self.text = "/предложение Добавьте больше катастроф"
            self.from_user = User(id=100, is_bot=False, first_name="TestUser", username="testuser")
            self.chat = Chat(id=-100, type="group", title="Test Group")
            self.replies = []

        async def answer(self, text, parse_mode=None):
            self.replies.append(text)
            return self

    msg = DummyMessage()
    bot = DummyBot()
    await cmd_feedback(msg, command=None, bot=bot)
    assert len(msg.replies) == 1
    assert "Спасибо! Ваше предложение отправлено" in msg.replies[0]
    assert len(bot.sent_messages) > 0
    chat_id, sent_text = bot.sent_messages[0]
    assert "НОВОЕ ПРЕДЛОЖЕНИЕ" in sent_text
    assert "Добавьте больше катастроф" in sent_text
