import io
import urllib.parse
import urllib.request
import asyncio
from aiogram.types import BufferedInputFile

async def text_to_speech_voice(text: str, voice_name: str = "ru-RU-DmitryNeural", lang: str = 'ru') -> BufferedInputFile | None:
    """
    Генерирует голосовое аудиосообщение из текста.
    1. Исполняет запрос через edge-tts (Microsoft Edge TTS API — нейронные голоса, не блокируются в облаке).
    2. Фоллбэк на библиотеку gTTS.
    3. Фоллбэк на HTTP-запрос к Google TTS.
    """
    if not text or len(text.strip()) == 0:
        return None

    clean_text = text.strip()[:200]

    # 1. Попытка через Microsoft Edge TTS
    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, voice=voice_name)
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
        if audio_data:
            return BufferedInputFile(bytes(audio_data), filename="dictor_voice.mp3")
    except Exception as e_edge:
        print(f"edge-tts error or missing: {e_edge}")

    # 2. Попытка через gTTS
    def _generate_gtts():
        try:
            from gtts import gTTS
            fp = io.BytesIO()
            tts = gTTS(text=clean_text, lang=lang)
            tts.write_to_fp(fp)
            fp.seek(0)
            return fp.read()
        except Exception as e_gtts:
            print(f"gTTS error: {e_gtts}")
            return None

    # 3. HTTP фоллбэк
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

    audio_bytes = await asyncio.to_thread(_generate_gtts)
    if not audio_bytes:
        audio_bytes = await asyncio.to_thread(_generate_fallback)

    if audio_bytes:
        return BufferedInputFile(audio_bytes, filename="dictor_voice.mp3")
    return None
