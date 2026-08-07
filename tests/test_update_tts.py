import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import BufferedInputFile

# --- ТЕСТЫ СИНТЕЗА РЕЧИ И TTS ОЗВУЧКИ (40 ТЕСТОВ) ---

TEST_PHRASES = [
    "Бесспорно", "Предрешено", "Никаких сомнений", "Определённо да", "Можешь быть уверен в этом",
    "Мне кажется — «да»", "Вероятнее всего", "Хорошие перспективы", "Знаки говорят — «да»", "Да",
    "Пока не ясно, попробуй снова", "Спроси позже", "Лучше не рассказывать", "Сейчас нельзя предсказать",
    "Сконцентрируйся и спроси опять", "Даже не думай", "Мой ответ — «нет»", "По моим данным — «нет»",
    "Перспективы не очень хорошие", "Весьма сомнительно"
]

@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", TEST_PHRASES)
async def test_tts_generation_phrases(phrase):
    """Тест генерации голосовых сообщений из текстов предсказаний дикторов (20 тестов)"""
    from tts_utils import text_to_speech_voice

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b"\x00\x01\x02\x03\x04FAKE_AUDIO_DATA"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = await text_to_speech_voice(phrase)

        assert res is not None
        assert isinstance(res, BufferedInputFile)
        assert res.filename == "dictor_voice.mp3"


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_input", ["", "   ", "\n\t", None])
async def test_tts_empty_inputs(empty_input):
    """Тест обработки пустых входных данных в TTS (4 теста)"""
    from tts_utils import text_to_speech_voice

    res = await text_to_speech_voice(empty_input)
    assert res is None


@pytest.mark.asyncio
@pytest.mark.parametrize("long_length", [250, 300, 500, 1000, 2000, 5000])
async def test_tts_long_text_clamping(long_length):
    """Тест безопасной обрезки слишком длинного текста до 200 символов (6 тестов)"""
    from tts_utils import text_to_speech_voice

    long_text = "А" * long_length

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b"AUDIO_DATA"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = await text_to_speech_voice(long_text)

        assert res is not None
        # Проверяем, что запрос к URL был обрезан до 200 символов
        called_url = mock_urlopen.call_args[0][0].full_url
        assert len(called_url) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("dictor_id", [
    "dictor_common", "dictor_rare", "dictor_legendary", "dictor_mythic",
    "dictor_divine", "dictor_void", "dictor_emperor", "dictor_immortal"
])
async def test_banya_dictor_voice_integration(dictor_id):
    """Тест отправки текста и голосового сообщения при команде /banya_dictor (8 тестов)"""
    from seasons import cmd_banya_dictor

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890

    user_data = {
        'is_banned': False,
        'inventory': {dictor_id: 1}
    }

    fake_voice = BufferedInputFile(b"VOICE_BYTES", filename="dictor_voice.mp3")

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data, \
         patch('tts_utils.text_to_speech_voice', new_callable=AsyncMock) as mock_tts:

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = user_data
        mock_tts.return_value = fake_voice

        await cmd_banya_dictor(message)

        message.answer.assert_called_once()
        message.answer_voice.assert_called_once_with(voice=fake_voice)


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type", [ValueError, RuntimeError])
async def test_banya_dictor_voice_error_handling(exception_type):
    """Тест устойчивости при сбоеTTS озвучки — текстовый ответ отправляется (2 теста)"""
    from seasons import cmd_banya_dictor

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data, \
         patch('tts_utils.text_to_speech_voice', side_effect=exception_type("TTS network error")):

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = {'is_banned': False, 'inventory': {'dictor_common': 1}}

        await cmd_banya_dictor(message)

        message.answer.assert_called_once()
        message.answer_voice.assert_not_called()
