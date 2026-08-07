import io
import urllib.parse
import urllib.request
import asyncio
from aiogram.types import BufferedInputFile

async def text_to_speech_voice(text: str, lang: str = 'ru') -> BufferedInputFile | None:
    """
    Генерирует голосовое аудиосообщение из текста.
    Сначала пытается использовать библиотеку gTTS, при отсутствии — фоллбэк на Google TTS API.
    """
    if not text or len(text.strip()) == 0:
        return None

    # Обрезаем слишком длинный текст для TTS (до 200 символов)
    clean_text = text.strip()[:200]

    def _generate_gtts():
        try:
            from gtts import gTTS
            fp = io.BytesIO()
            tts = gTTS(text=clean_text, lang=lang)
            tts.write_to_fp(fp)
            fp.seek(0)
            return fp.read()
        except Exception:
            return None

    def _generate_fallback():
        try:
            encoded_text = urllib.parse.quote(clean_text)
            url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded_text}&tl={lang}&client=tw-ob"
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read()
        except Exception as e:
            print(f"TTS Fallback error: {e}")
            return None

    # Запускаем синхронную генерацию в отдельном потоке
    audio_bytes = await asyncio.to_thread(_generate_gtts)
    if not audio_bytes:
        audio_bytes = await asyncio.to_thread(_generate_fallback)

    if audio_bytes:
        return BufferedInputFile(audio_bytes, filename="dictor_voice.mp3")
    return None
