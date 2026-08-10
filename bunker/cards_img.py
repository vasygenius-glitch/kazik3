# bunker/cards_img.py
import io
from PIL import Image, ImageDraw, ImageFont
from bunker.models import Player, Scenario

def render_player_dossier_png(player: Player, scenario: Scenario) -> io.BytesIO:
    """
    Генерирует стилизованное PNG изображение карточки игрока ("Дело №...").
    """
    width, height = 700, 900
    img = Image.new("RGB", (width, height), color=(18, 20, 26))
    draw = ImageDraw.Draw(img)

    # Попытка загрузить шрифты
    try:
        font_title = ImageFont.truetype("arial.ttf", 28)
        font_header = ImageFont.truetype("arial.ttf", 22)
        font_body = ImageFont.truetype("arial.ttf", 18)
        font_small = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font_title = ImageFont.load_default()
        font_header = font_title
        font_body = font_title
        font_small = font_title

    # Заголовок / Штамп
    draw.rectangle([(20, 20), (width - 20, height - 20)], outline=(60, 70, 90), width=3)
    draw.rectangle([(25, 25), (width - 25, height - 25)], outline=(40, 48, 62), width=1)
    
    # Красный штамп СЕКРЕТНО
    draw.rectangle([(width - 220, 35), (width - 40, 75)], outline=(200, 40, 40), width=2)
    draw.text((width - 210, 43), "ГРИФ: СЕКРЕТНО", fill=(220, 50, 50), font=font_header)

    # Шапка карточки
    draw.text((40, 35), "☢️ ЛИЧНОЕ ДЕЛО ВЫЖИВАЮЩЕГО", fill=(240, 200, 80), font=font_title)
    draw.text((40, 75), f"Объект: {player.name} (ID: {player.user_id})", fill=(200, 210, 225), font=font_header)
    draw.text((40, 105), f"Катастрофа: {scenario.title} | Бункер: {scenario.bunker_name}", fill=(150, 160, 180), font=font_small)

    draw.line([(40, 130), (width - 40, 130)], fill=(70, 80, 100), width=2)

    # Список характеристик
    y = 150
    draw.text((40, y), "ХАРАКТЕРИСТИКИ ПЕРСОНАЖА:", fill=(180, 200, 240), font=font_header)
    y += 35

    for key, card in player.cards.items():
        # Фоновый прямоугольник для строки
        is_rev = card.revealed
        bg_color = (30, 40, 55) if is_rev else (25, 28, 36)
        border_color = (70, 120, 180) if is_rev else (45, 50, 65)

        draw.rectangle([(40, y), (width - 40, y + 42)], fill=bg_color, outline=border_color, width=1)
        
        # Иконка и название категории
        cat_text = f"{card.icon} {card.category_name}:"
        draw.text((50, y + 10), cat_text, fill=(220, 225, 235), font=font_body)

        # Значение (если раскрыта — текст, иначе зашифровано)
        if is_rev:
            val_text = card.value
            val_color = (100, 230, 140)
        else:
            val_text = "🔒 [ЗАКРЫТО / НЕ РАСКРЫТО]"
            val_color = (130, 140, 155)

        draw.text((280, y + 10), val_text, fill=val_color, font=font_body)
        y += 50

    # Спецкарта
    y += 10
    draw.line([(40, y), (width - 40, y)], fill=(70, 80, 100), width=1)
    y += 15

    draw.text((40, y), "СПЕЦИАЛЬНАЯ КАРТА:", fill=(240, 180, 80), font=font_header)
    y += 35

    if player.special_card:
        sc = player.special_card
        used_str = " (ИСПОЛЬЗОВАНА)" if sc.used else ""
        draw.rectangle([(40, y), (width - 40, y + 50)], fill=(35, 30, 20), outline=(180, 130, 40), width=1)
        draw.text((50, y + 8), f"{sc.icon} {sc.name}{used_str}", fill=(255, 220, 120), font=font_body)
        draw.text((50, y + 30), sc.description, fill=(190, 180, 160), font=font_small)
    else:
        draw.text((40, y), "Отсутствует", fill=(120, 120, 120), font=font_body)

    # Подвал
    draw.text((40, height - 40), "Система автоматического контроля бункеров v3.2", fill=(80, 90, 110), font=font_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
