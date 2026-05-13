import time
import secrets
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from user_manager import update_user_balance, update_user_field
import uuid

router = Router()

# Кэш для отслеживания количества вызовов команд и активных капч
# Формат: {(chat_id, user_id): {'count': 0, 'captcha_active': False, 'expected_game_id': None, 'last_update': 0}}
_antibot_cache = {}

def check_antibot(chat_id: int, user_id: int) -> bool:
    """
    Проверяет, превысил ли пользователь лимит вызовов команд заработка.
    Возвращает True, если нужно показать капчу (лимит превышен или капча уже активна).
    """
    key = (chat_id, user_id)
    if key not in _antibot_cache:
        _antibot_cache[key] = {'count': 0, 'captcha_active': False, 'expected_game_id': None, 'last_update': time.time()}

    _antibot_cache[key]['last_update'] = time.time()

    if _antibot_cache[key]['captcha_active']:
        return True

    _antibot_cache[key]['count'] += 1

    if _antibot_cache[key]['count'] >= 5:
        _antibot_cache[key]['captcha_active'] = True
        return True

    return False

def force_captcha(chat_id: int, user_id: int):
    """
    Принудительно активирует капчу для пользователя (например, при аномально высоких доходах).
    """
    key = (chat_id, user_id)
    if key not in _antibot_cache:
        _antibot_cache[key] = {'count': 0, 'captcha_active': False, 'expected_game_id': None, 'last_update': time.time()}
    _antibot_cache[key]['captcha_active'] = True

def generate_captcha(chat_id: int, user_id: int):
    """
    Генерирует математическую капчу.
    Возвращает кортеж (текст_вопроса, список_кортежей(текст_кнопки, callback_data))
    """
    rand = secrets.SystemRandom()
    a = rand.randint(1, 20)
    b = rand.randint(1, 20)
    operator = rand.choice(['+', '-'])

    if operator == '+':
        correct_ans = a + b
    else:
        correct_ans = a - b

    question = f"Сколько будет {a} {operator} {b}?"

    options = [correct_ans, correct_ans + rand.randint(1, 5), correct_ans - rand.randint(1, 5)]
    # Чтобы не было дублей, если рандом выдаст 0
    options = list(set(options))
    while len(options) < 3:
        new_opt = correct_ans + rand.randint(6, 15)
        if new_opt not in options:
            options.append(new_opt)

    rand.shuffle(options)

    game_id = str(uuid.uuid4())[:8]

    # Сохраняем game_id для предотвращения подделки
    key = (chat_id, user_id)
    if key in _antibot_cache:
        _antibot_cache[key]['expected_game_id'] = game_id

    keyboard_options = []
    for opt in options:
        is_correct = "1" if opt == correct_ans else "0"
        cb_data = f"captcha_{game_id}_{is_correct}"
        keyboard_options.append((str(opt), cb_data))

    return question, keyboard_options

async def send_captcha(message: types.Message):
    """
    Отправляет капчу пользователю.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    question, options = generate_captcha(chat_id, user_id)

    builder = InlineKeyboardBuilder()
    for opt_text, cb_data in options:
        builder.button(text=opt_text, callback_data=cb_data)

    builder.adjust(3)

    await message.answer(
        f"🤖 <b>ПОДОЗРЕНИЕ НА АВТОКЛИКЕР!</b>\n\nВы слишком часто работаете. Решите капчу, чтобы продолжить:\n\n{question}",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("captcha_"))
async def process_captcha(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return

    game_id = parts[1]
    is_correct = parts[2] == "1"

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    key = (chat_id, user_id)

    # Проверка, что капча активна и game_id совпадает
    if key not in _antibot_cache or not _antibot_cache[key].get('captcha_active'):
        return await callback.answer("У вас нет активной капчи.", show_alert=True)

    expected_game_id = _antibot_cache[key].get('expected_game_id')
    if expected_game_id != game_id:
        return await callback.answer("Эта капча устарела или недействительна.", show_alert=True)

    if is_correct:
        # Правильный ответ
        _antibot_cache[key]['count'] = 0
        _antibot_cache[key]['captcha_active'] = False
        _antibot_cache[key]['expected_game_id'] = None

        # Обнуляем таймеры заработка (бонус от Босса)
        await update_user_field(chat_id, user_id, 'last_work_time', 0)
        await update_user_field(chat_id, user_id, 'last_crime_time', 0)

        await callback.message.edit_text("✅ <b>Проверка пройдена!</b>\nТаймеры заработка обнулены, можете продолжать работу.")
    else:
        # Неправильный ответ
        await update_user_balance(chat_id, user_id, -500, is_debt_repayment=True)

        question, options = generate_captcha(chat_id, user_id)
        builder = InlineKeyboardBuilder()
        for opt_text, cb_data in options:
            builder.button(text=opt_text, callback_data=cb_data)
        builder.adjust(3)

        await callback.message.edit_text(
            f"❌ <b>Неверно!</b> Штраф -500 сыроежек.\nПопробуйте еще раз:\n\n{question}",
            reply_markup=builder.as_markup()
        )
