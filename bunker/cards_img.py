# bunker/cards_img.py
import io
import logging
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont

from bunker.models import Player, Scenario

logger = logging.getLogger(__name__)

# DejaVu/Liberation не умеют цветные emoji -> вырезаем всё вне BMP, чтобы не было «квадратов»
_NON_BMP = re.compile(r"[\U00010000-\U0010FFFF\u2190-\u2BFF\uFE0F\u20E3]")


def _clean(text: object) -> str:
    return _NON_BMP.sub("", str(text)).strip()


def load_system_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:                                    # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_player_dossier_png(player: Player, scenario: Scenario | None) -> io.BytesIO:
    """PNG «Личное дело». Высота считается динамически — текст больше не вылезает."""
    width = 760
    row_h = 46
    top = 170
    rows = max(1, len(player.cards))
    height = top + rows * row_h + 190

    img = Image.new("RGB", (width, height), (18, 20, 26))
    draw = ImageDraw.Draw(img)

    f_title = load_system_font(26)
    f_head = load_system_font(19)
    f_body = load_system_font(16)
    f_small = load_system_font(13)

    draw.rectangle([(18, 18), (width - 18, height - 18)], outline=(60, 70, 90), width=3)
    draw.rectangle([(24, 24), (width - 24, height - 24)], outline=(40, 48, 62), width=1)
    draw.rectangle([(width - 232, 34), (width - 40, 72)], outline=(200, 40, 40), width=2)
    draw.text((width - 222, 43), "ГРИФ: СЕКРЕТНО", fill=(220, 50, 50), font=f_head)

    draw.text((40, 38), "ЛИЧНОЕ ДЕЛО ВЫЖИВАЮЩЕГО", fill=(240, 200, 80), font=f_title)
    draw.text((40, 78), f"Объект: {_clean(player.name)}  |  Место #{player.seat}",
              fill=(200, 210, 225), font=f_head)
    sc_title = _clean(scenario.title) if scenario else "Неизвестно"
    sc_bunker = _clean(scenario.bunker_name) if scenario else "Неизвестно"
    draw.text((40, 106), f"Катастрофа: {sc_title}  |  Бункер: {sc_bunker}",
              fill=(150, 160, 180), font=f_small)
    draw.line([(40, 132), (width - 40, 132)], fill=(70, 80, 100), width=2)
    draw.text((40, 142), "ХАРАКТЕРИСТИКИ ПЕРСОНАЖА", fill=(180, 200, 240), font=f_head)

    y = top
    for card in player.cards.values():
        rev = card.revealed
        draw.rectangle([(40, y), (width - 40, y + row_h - 6)],
                       fill=(30, 45, 60) if rev else (25, 28, 36),
                       outline=(70, 150, 220) if rev else (45, 50, 65), width=1)
        status = "[OPEN]" if rev else "[LOCK]"
        draw.text((50, y + 12), f"{status} {_clean(card.category_name)}:",
                  fill=(220, 225, 235), font=f_body)
        value = textwrap.shorten(_clean(card.value), width=44, placeholder="…")
        draw.text((300, y + 12), value,
                  fill=(100, 230, 140) if rev else (240, 210, 130), font=f_body)
        y += row_h

    y += 12
    draw.line([(40, y), (width - 40, y)], fill=(70, 80, 100), width=1)
    y += 16
    draw.text((40, y), "СПЕЦИАЛЬНАЯ КАРТА", fill=(240, 180, 80), font=f_head)
    y += 32

    if player.special_card:
        sc = player.special_card
        used = " (ИСПОЛЬЗОВАНА)" if sc.used else ""
        draw.rectangle([(40, y), (width - 40, y + 60)], fill=(35, 30, 20),
                       outline=(180, 130, 40), width=1)
        draw.text((50, y + 8), f"{_clean(sc.name)}{used}", fill=(255, 220, 120), font=f_body)
        draw.text((50, y + 32),
                  textwrap.shorten(_clean(sc.description), width=78, placeholder="…"),
                  fill=(190, 180, 160), font=f_small)
    else:
        draw.text((40, y), "Отсутствует", fill=(120, 120, 120), font=f_body)

    draw.text((40, height - 44), "Система автоматического контроля бункеров v4.0",
              fill=(80, 90, 110), font=f_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
