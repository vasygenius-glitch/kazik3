from aiogram import Router, F, types
from aiogram.filters import Command
import secrets
import time
from economy_utils import get_global_tax
from user_manager import get_user_data, update_user_balance, check_and_give_bonus, update_user_field, get_top_users
from seasons import apply_season_bonus
from escape import escape_html

router = Router()

active_work_games = {}
active_crime_games = {}

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    await get_user_data(chat_id, user_id, full_name)

    text = (
        f"👋 <b>Привет, {full_name}!</b>\n\n"
        "Я бот для экономики и мини-игр! Твой стартовый баланс составляет <b>500</b> сыроежек.\n\n"
        "Пиши <code>/help</code> чтобы увидеть список всех команд."
    )
    await message.answer(text)

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = "📜 <b>ПОЛНЫЙ СПИСОК КОМАНД БОТА</b> 📜\n\n"

    text += "🚀 <b>ПОСЛЕДНИЕ ОБНОВЛЕНИЯ:</b>\n"
    text += "• <b>Фондовая Биржа:</b> Команда <code>/stocks</code> — инвестируй в ГазСыр и SpaceMilk!\n"
    text += "• <b>Сезоны:</b> Команда <code>/season</code> — тематические события с бонусами!\n"
    text += "• <b>Налог на богатство:</b> Чем больше у тебя сыроежек, тем выше комиссия в <code>/pay</code> и цены в <code>/shop</code>.\n"
    text += "• <b>Мини-игры:</b> В <code>/work</code> и <code>/crime</code> теперь нужно играть, чтобы получить бонус.\n"
    text += "• <b>Реактивный инвентарь:</b> <code>/inv</code> и операции с балансом стали работать мгновенно.\n"
    text += "• <b>Оптимизация:</b> Бот стал работать в 5 раз быстрее благодаря новой системе кэширования.\n\n"
    
    text += "💰 <b>ЭКОНОМИКА И БАНК:</b>\n"
    text += "<code>/profile</code> - Профиль (деньги, клан, брак, варны).\n"
    text += "<code>/bank</code> - Главное меню банков (вклады, листы, инфо).\n"
    text += "<code>/bank_offshore</code> - Скрыть счет в банке за комиссию.\n"
    text += "<code>ограбить банк [Имя]</code> - Попытка кражи из банка.\n"
    text += "<code>/bonus</code> - Собрать прибыль (учитывает налог на богатство).\n"
    text += "<code>/work</code>, <code>/crime</code> - Работа и криминал с мини-играми.\n"
    text += "<code>/pay [сумма][реплай]</code> - Перевод (комиссия зависит от баланса).\n"
    text += "<code>долг [сумма] [%][реплай]</code> - Дать в долг (P2P).\n"
    text += "<code>выплатить[сумма] [реплай]</code> - Вернуть долг.\n"
    text += "<code>украсть</code> [реплай] - Карманная кража.\n\n"

    text += "📈 <b>БИРЖА (АКЦИИ И КРИПТА):</b>\n"
    text += "<code>/stocks</code> - <b>НОВОЕ!</b> Фондовая биржа с графиками компаний.\n"
    text += "<code>/криптосыроежка</code> - Главное меню крипторынка.\n"
    text += "<code>/createcoin [ТИКЕР] [Название]</code> - Создать свою монету.\n"
    text += "<code>/cr_send [ТИКЕР] [Кол-во]</code> - Перевод крипты.\n\n"

    text += "🏦 <b>ДЛЯ БАНКИРОВ:</b>\n"
    text += "<code>создать банк [Имя]</code> - Открыть свой банк.\n"
    text += "<code>/bankrate [3-13]</code> - Установить % по вкладам.\n"
    text += "<code>/bank_stats</code> - Панель управления (вклады, кредиты).\n"
    text += "<code>кредит [сумма] [%] [дни] [поручитель] [реплай]</code> - Выдать кредит игроку.\n\n"

    text += "🤝 <b>СДЕЛКИ И ДОГОВОРЫ:</b>\n"
    text += "<code>договор [текст]</code> - Заключить словесный контракт.\n"
    text += "<code>сделка [цена] [предмет] [условие]</code> - Купля-продажа вещей.\n"
    text += "<code>наследство</code> - Передать всё имущество (реплай).\n\n"

    text += "🔞 <b>ЭСКОРТ:</b>\n"
    text += "<code>нанять/заказать [сумма] [реплай]</code> - Снять путану.\n"
    text += "<code>эскорт/проститут [сумма] [реплай]</code> - Предложить услуги.\n\n"

    text += "🛒 <b>МАГАЗИН И ПРОКАЧКА:</b>\n"
    text += "<code>/shop</code> - Покупка бизнесов и VIP (цены динамические!).\n"
    text += "<code>/inv</code> - Ваш инвентарь (Улучшение и продажа).\n"
    text += "<code>/skills</code> - Прокачка (Переговоры снижают налоги!).\n"
    text += "<code>/pets</code>, <code>/feed</code> - Питомцы.\n\n"

    text += "🛡 <b>КЛАНЫ И СЕМЬИ:</b>\n"
    text += "<code>/clan</code> - Меню кланов.\n"
    text += "<code>Брак</code>, <code>Развод</code>, <code>Подарок [сумма]</code>.\n\n"

    text += "🎰 <b>ИГРЫ:</b>\n"
    text += "<code>/bj</code>, <code>/slots</code>, <code>/roulette [ставка] [число/цвет]</code>.\n"
    text += "<code>Вызвать на дуэль [ставка]</code> - Тактическая дуэль!\n<code>/lottery</code> - розыгрыш.\n\n"

    text += "👮‍♂️ <b>АДМИНИСТРАЦИЯ:</b>\n"
    text += "<code>мут</code>, <code>бан</code>, <code>варн</code>, <code>повысить</code>, <code>снять</code>.\n"
    text += "<code>кто админ</code>, <code>+правила</code>, <code>антивойс</code>, <code>антилинк</code>.\n"
    text += "<code>/cr_wipe</code>, <code>/cr_crash</code>, <code>бан/разбан крипты</code>.\n\n"

    text += "🎭 <b>РП И ИНТЕРАКТИВ:</b>\n"
    text += "<code>Обнять</code>, <code>Поцеловать</code>, <code>Ударить</code>, <code>Кусь</code>.\n"
    text += "<code>Диктор [вопрос]</code>, <code>/bio [текст]</code>.\n"
    text += "Репутация: <code>+</code>, <code>спасибо</code>, <code>реп</code>."
    
    await message.answer(text)

@router.message(Command("balance"))
async def cmd_balance(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    balance = data.get('balance', 0)
    is_vip = data.get('is_vip', False)

    vip_icon = " 👑 VIP" if is_vip else ""
    await message.answer(f"💰 Твой баланс: <b>{balance}</b> сыроежек.{vip_icon}")

@router.message(Command("pay"))
async def cmd_pay(message: types.Message):
    chat_id = message.chat.id
    sender_id = message.from_user.id
    sender_name = escape_html(message.from_user.full_name)

    sender_data = await get_user_data(chat_id, sender_id, sender_name)
    if sender_data.get('is_banned', False):
        await message.answer("Ты в бане и не можешь переводить деньги.")
        return

    if not message.reply_to_message:
        await message.answer("Ответь на сообщение человека, которому хочешь перевести сыроежки.")
        return

    target_user = message.reply_to_message.from_user
    target_name = escape_html(target_user.full_name)
    if target_user.is_bot:
        await message.answer("Ботам деньги не нужны.")
        return

    if target_user.id == message.from_user.id:
        await message.answer("Нельзя перевести деньги самому себе.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажи сумму: <code>/pay 100</code> или <code>/pay all</code>")
        return

    amount_str = args[1].lower()
    if amount_str in ["all", "всё", "все"]:
        # If user wants to pay all, we need to calculate how much they can send after tax
        from economy_utils import get_global_tax, calculate_progressive_tax
        base_tax = await get_global_tax()
        from diseases import get_active_diseases
        active_diseases = await get_active_diseases(chat_id, sender_id)

        neg_lvl = sender_data.get('skills', {}).get('negotiation', 0)
        tax_percent = calculate_progressive_tax(sender_data.get('balance', 0), base_tax, neg_lvl)

        if 'herpes' in active_diseases:
            tax_percent = max(tax_percent, 30) # Герпес: налог минимум 30% на все переводы
        
        balance = sender_data.get('balance', 0)
        if balance <= 0:
            return await message.answer("У вас нет денег.")

        # math: amount + (amount * tax / 100) = balance => amount = balance / (1 + tax/100)
        if tax_percent > 0:
            amount = int(balance / (1 + (tax_percent / 100.0)))
            if amount == balance and tax_percent > 0: # Ensure minimum 1 tax logic if any
                amount -= 1
        else:
            amount = balance

        if amount <= 0:
            return await message.answer("После уплаты налога отправлять нечего.")
    else:
        try:
            amount = int(amount_str)
            if amount <= 0:
                await message.answer("Сумма должна быть больше нуля.")
                return
        except ValueError:
            await message.answer("Сумма должна быть числом или 'all'.")
            return

        from economy_utils import get_global_tax, calculate_progressive_tax
        base_tax = await get_global_tax()
        from diseases import get_active_diseases
        active_diseases = await get_active_diseases(chat_id, sender_id)
        neg_lvl = sender_data.get('skills', {}).get('negotiation', 0)
        tax_percent = calculate_progressive_tax(sender_data.get('balance', 0), base_tax, neg_lvl)

        if 'herpes' in active_diseases:
            tax_percent = max(tax_percent, 30) # Герпес: налог минимум 30% на все переводы

    if tax_percent > 0:
        commission = int(amount * (tax_percent / 100.0))
        if commission == 0: commission = 1 
    else:
        commission = 0
        
    total_cost = amount + commission

    if sender_data.get('balance', 0) < total_cost:
        await message.answer(f"Мало денег. Для перевода {amount} нужно {total_cost} сыроежек (налог {tax_percent}% - минимум 1 сыр.).")
        return

    try:
        admins = await message.chat.get_administrators()
        human_admins =[admin.user.id for admin in admins if not admin.user.is_bot]
    except Exception:
        human_admins =[]

    from db import get_db
    try:
        from firebase_admin import firestore_async
        transactional = firestore_async.transactional
    except ImportError:
        # Mock for local testing without firebase
        def transactional(func):
            return func

    db = get_db()

    @transactional
    async def process_transfer(transaction, chat_id, sender_id, target_id, total_cost, amount, human_admins, commission):
        # We still use update_user_balance which utilizes fire_and_forget and cache
        # For full safety it should use the transaction, but updating cache is important
        # Since Firebase transactions require reading inside the transaction to avoid race conditions:
        await update_user_balance(chat_id, sender_id, -total_cost)
        await get_user_data(chat_id, target_user.id, target_name)
        await update_user_balance(chat_id, target_user.id, amount)

        if human_admins and commission > 0:
            commission_per_admin = commission // len(human_admins)
            if commission_per_admin > 0:
                for admin_id in human_admins:
                    await get_user_data(chat_id, admin_id)
                    await update_user_balance(chat_id, admin_id, commission_per_admin)

    try:
        if hasattr(db, 'transaction'):
            await process_transfer(db.transaction(), chat_id, sender_id, target_user.id, total_cost, amount, human_admins, commission)
        else:
            # Fallback
            await update_user_balance(chat_id, sender_id, -total_cost)
            await get_user_data(chat_id, target_user.id, target_name)
            await update_user_balance(chat_id, target_user.id, amount)
            if human_admins and commission > 0:
                commission_per_admin = commission // len(human_admins)
                if commission_per_admin > 0:
                    for admin_id in human_admins:
                        await get_user_data(chat_id, admin_id)
                        await update_user_balance(chat_id, admin_id, commission_per_admin)
    except Exception as e:
        await message.answer(f"❌ Ошибка перевода: {e}")
        return

    phrases =[
        f"Налоговая откусила кусок в {commission} сыроежек.",
        f"Гоблины-сборщики забрали {commission} сыроежек в казну.",
        f"Крыша требует свою долю. Удержано {commission} сыроежек.",
        f"Банкирский дом забирает свои скромные {commission} сыроежек за услуги.",
        f"Местные рэкетиры взыскали налог: {commission} сыроежек.",
        f"Комиссия в {commission} сыроежек ушла на развитие экономики."
    ]
    phrase = secrets.choice(phrases) if commission > 0 else "Налог отменен! Деньги дошли без потерь."

    await message.answer(
        f"💸 <b>Успешный перевод!</b>\n\n"
        f"Отправлено: {amount} сыроежек пользователю {target_name}.\n"
        f"<i>{phrase}</i> (Налог {tax_percent}% ушел админам)."
    )

@router.message(Command("bonus"))
async def cmd_bonus(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    success, receipt = await check_and_give_bonus(chat_id, user_id, full_name)
    if success:
        text = f"🧾 <b>Квитанция о доходах</b>\n\n"
        if receipt.get('base', 0) > 0:
            text += f"🎁 Ежедневный бонус: <b>{receipt['base']}</b>\n"
        text += f"🏢 Доход с бизнесов: <b>{receipt['business']}</b>\n"
        text += f"🚗 Доход с машин: <b>{receipt['car']}</b>\n"
        text += f"➖ Налог ({receipt['tax_percent']}%): <b>-{receipt['tax_amount']}</b>\n"
        text += f"-----------------------\n"
        text += f"💰 Итого на руки: <b>{receipt['total']}</b> сыроежек"

        await message.answer(text)
    else:
        await message.answer("❌ Ты уже собирал доход недавно. Попробуй позже!")

@router.message(Command("work"))
async def cmd_work(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь работать.")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'hiv' in active_diseases:
        return await message.answer("🦠 <b>ВИЧ</b>: У тебя совершенно нет сил работать. Зарплата обнулена, работодатель отправил тебя домой лечиться.")

    last_work = data.get('last_work_time', 0)
    current_time = time.time()

    if current_time - last_work < 1800:
        remain = int(1800 - (current_time - last_work))
        mins, secs = divmod(remain, 60)
        return await message.answer(f"⏳ Ты устал. Отдохни еще {mins} минут и {secs} секунд.")

    await update_user_field(chat_id, user_id, 'last_work_time', current_time)

    rand = secrets.SystemRandom()
    is_banker = data.get('is_banker', False)
    base_earnings = rand.randint(50, 350) if is_banker else rand.randint(100, 700)
    
    bank_profit_msg = ""
    if is_banker:

        # Банкир также приносит пользу своему банку
        bank_contribution = rand.randint(1000, 5000)
        from profile_bank import get_bank_info, create_or_update_bank
        bank_data = await get_bank_info(chat_id, user_id)
        if bank_data:
            await create_or_update_bank(chat_id, user_id, {'capital': bank_data.get('capital', 0) + bank_contribution})
            bank_profit_msg = f"\n🏢 Ваша работа принесла банку <b>{bank_contribution}</b> сыр. в капитал!"

    # --- БОНУС ПИТОМЦА ---
    pet = data.get('pet')
    pet_id = pet.get('id') if pet else None
    pet_msg = ""
    
    if 'hpv' in active_diseases:
        pet_id = None # Питомец отказывается помогать из-за ВПЧ
        pet_msg = "\n🦠 <b>ВПЧ</b>: Твой питомец брезгует к тебе подходить и не дал бонусов."

    if pet_id == 'cat':
        base_earnings = int(base_earnings * 1.2)
        pet_msg = "\n🐱 Ваш верный кот помог заработать на 20% больше!"

    final_earnings = base_earnings

    # --- ЛОГИКА КОЛЛЕКТОРОВ ---
    collector_msg = ""
    debts = data.get('debts', {})
    balance = data.get('balance', 0)

    # Дракон защищает от коллекторов!
    if pet_id != 'dragon' and (debts or balance < 0) and rand.randint(1, 100) <= 30:
        if debts:
            lender_id_str = secrets.choice(list(debts.keys()))
            debt_amount = debts[lender_id_str]

            is_bank = lender_id_str.startswith("bank_")

            collector_cut = int(base_earnings * 0.5)
            if collector_cut == 0: collector_cut = 1
            pay_amount = min(collector_cut, debt_amount)

            if pay_amount > 0:
                final_earnings = base_earnings - pay_amount
                debts[lender_id_str] -= pay_amount
                if debts[lender_id_str] <= 0:
                    del debts[lender_id_str]
                
                await update_user_field(chat_id, user_id, 'debts', debts)
                
                if is_bank:
                    banker_id = int(lender_id_str.split("_")[1])
                    from profile_bank import get_bank_info, create_or_update_bank
                    bank_data = await get_bank_info(chat_id, banker_id)
                    lender_name = bank_data.get('name', 'Неизвестный Банк') if bank_data else 'Банк'
                    if bank_data:
                        await create_or_update_bank(chat_id, banker_id, {'capital': bank_data.get('capital', 0) + pay_amount})
                    collector_msg = f"\n\n🦹‍♂️ <b>КОЛЛЕКТОРЫ БАНКА!</b> Они поджидали тебя и забрали <b>{pay_amount}</b> сыроежек в качестве уплаты долга для <b>{escape_html(lender_name)}</b>."
                else:
                    lender_id = int(lender_id_str)
                    lender_data = await get_user_data(chat_id, lender_id)
                    lender_name = lender_data.get('full_name', 'Неизвестный кредитор')
                    await update_user_balance(chat_id, lender_id, pay_amount, is_debt_repayment=True)
                    collector_msg = f"\n\n🦹‍♂️ <b>ЧАСТНЫЕ КОЛЛЕКТОРЫ!</b> Они поджидали тебя и забрали <b>{pay_amount}</b> сыроежек в качестве уплаты долга для <b>{escape_html(lender_name)}</b>."
        else:
            penalty = rand.randint(100, 300)
            final_earnings = 0
            await update_user_balance(chat_id, user_id, -penalty, is_debt_repayment=True)
            collector_msg = f"\n\n🦹‍♂️ <b>КОЛЛЕКТОРЫ БАНКА!</b> Они отобрали весь заработок и выбили еще <b>{penalty}</b> сыроежек сверху в счет погашения кредита."
    elif pet_id == 'dragon' and (debts or balance < 0):
         pet_msg += "\n🐉 Ваш дракон отпугнул поджидавших вас коллекторов!"

    final_earnings = await apply_season_bonus(final_earnings, "work")
    if final_earnings > 0:
        await update_user_balance(chat_id, user_id, final_earnings, is_debt_repayment=True)

    jobs =[
        "разгрузил вагоны",
        "написал код за еду",
        "доставил пиццу",
        "отработал смену на заводе",
        "собрал металлолом"
    ]
    if data.get('is_banker', False):
        jobs = ["поработал с документами", "провел встречу с инвесторами", "свел дебет с кредитом", "продал акции банка"]

    job = rand.choice(jobs)

    afk_text = f"💼 Ты <b>{job}</b> и на автопилоте заработал <b>{base_earnings}</b> сыроежек!{pet_msg}{collector_msg}{bank_profit_msg}"
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    import uuid
    builder = InlineKeyboardBuilder()
    game_id = str(uuid.uuid4())[:8]
    
    bonus = rand.randint(500, 1250) if is_banker else rand.randint(1000, 2500)
    
    if is_banker:
        a = rand.randint(100, 500)
        b = rand.randint(100, 500)
        correct_ans = a + b
        options = [correct_ans, correct_ans + rand.randint(10, 50), correct_ans - rand.randint(10, 50)]
        rand.shuffle(options)
        
        game_text = f"\n\n🎮 <b>ПРЕМИЯ:</b> Сведите баланс! <b>{a} + {b} = ?</b>"
        
        for opt in options:
            cb_data = f"work_btn_{game_id}_1" if opt == correct_ans else f"work_btn_{game_id}_0"
            builder.button(text=str(opt), callback_data=cb_data)
    else:
        fruits = ["🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐"]
        target = rand.choice(fruits)
        options = rand.sample(fruits, 3)
        if target not in options:
            options[0] = target
        rand.shuffle(options)
        
        game_text = f"\n\n🎮 <b>ПРЕМИЯ:</b> Собери нужный товар! Нажми на <b>{target}</b>"
        
        for opt in options:
            cb_data = f"work_btn_{game_id}_1" if opt == target else f"work_btn_{game_id}_0"
            builder.button(text=opt, callback_data=cb_data)
            
    builder.adjust(3)
    
    active_work_games[game_id] = {
        'user_id': user_id,
        'bonus': bonus,
        'expires': time.time() + 60
    }
    
    await message.answer(afk_text + game_text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("work_btn_"))
async def process_work_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4: return
    game_id = parts[2]
    is_correct = parts[3] == "1"
    
    game = active_work_games.get(game_id)
    if not game:
        return await callback.answer("⏳ Время вышло или игра уже завершена!", show_alert=True)
        
    if game['user_id'] != callback.from_user.id:
        return await callback.answer("Это не твоя работа!", show_alert=True)
        
    if time.time() > game['expires']:
        del active_work_games[game_id]
        await callback.message.edit_reply_markup(reply_markup=None)
        return await callback.answer("⏳ Время вышло!", show_alert=True)
        
    del active_work_games[game_id]
    
    # aiogram 3.x html_text
    original_html = callback.message.html_text if hasattr(callback.message, 'html_text') else callback.message.text
    if not original_html:
        original_html = ""
        
    if is_correct:
        chat_id = callback.message.chat.id
        await update_user_balance(chat_id, callback.from_user.id, game['bonus'])
        new_text = original_html + f"\n\n✅ <b>Успех!</b> Ты получил премию <b>{game['bonus']}</b> сыр.!"
        await callback.message.edit_text(new_text, reply_markup=None)
    else:
        new_text = original_html + "\n\n❌ <b>Ошибка!</b> Ты запорол работу, премия сгорела."
        await callback.message.edit_text(new_text, reply_markup=None)
@router.message(Command("crime"))
async def cmd_crime(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь совершать преступления.")
        
    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)

    if data.get('is_banker', False):
        return await message.answer("🏦 Вы — уважаемый Банкир. Воровать не по статусу. (Крайм отключен для банкиров)")

    last_crime = data.get('last_crime_time', 0)
    current_time = time.time()

    if current_time - last_crime < 3600:
        remain = int(3600 - (current_time - last_crime))
        mins, secs = divmod(remain, 60)
        return await message.answer(f"⏳ Копы ищут тебя. Заляг на дно еще на {mins} мин. {secs} сек.")

    await update_user_field(chat_id, user_id, 'last_crime_time', current_time)

    rand = secrets.SystemRandom()
    stealth_level = data.get('skills', {}).get('stealth', 0)
    
    # --- БОНУС ПИТОМЦА ---
    pet = data.get('pet')
    pet_id = pet.get('id') if pet else None

    if 'hpv' in active_diseases:
        pet_id = None
        pet_msg = "\n🦠 <b>ВПЧ</b>: Питомец отказался помогать."
    else:
        pet_msg = "\n🐉 Дракон помог провернуть дело!" if pet_id == 'dragon' else ""

    dragon_bonus = 0.1 if pet_id == 'dragon' else 0

    success_chance = 0.4 + (stealth_level * 0.05) + dragon_bonus

    if 'syphilis' in active_diseases:
        success_chance /= 2.0
        pet_msg += "\n🦠 <b>Сифилис</b>: Шанс успеха порезан в 2 раза из-за ужасного самочувствия."

    if rand.random() < success_chance:
        base_earnings = rand.randint(200, 500)
        final_earnings = base_earnings

        # --- ЛОГИКА КОЛЛЕКТОРОВ ---
        collector_msg = ""
        debts = data.get('debts', {})
        balance = data.get('balance', 0)

        if pet_id != 'dragon' and (debts or balance < 0) and rand.randint(1, 100) <= 40:
            if debts:
                lender_id_str = secrets.choice(list(debts.keys()))
                debt_amount = debts[lender_id_str]

                is_bank = lender_id_str.startswith("bank_")

                collector_cut = int(base_earnings * 0.5)
                if collector_cut == 0: collector_cut = 1
                pay_amount = min(collector_cut, debt_amount)

                if pay_amount > 0:
                    final_earnings = base_earnings - pay_amount
                    debts[lender_id_str] -= pay_amount
                    if debts[lender_id_str] <= 0:
                        del debts[lender_id_str]
                    
                    await update_user_field(chat_id, user_id, 'debts', debts)
                    
                    if is_bank:
                        banker_id = int(lender_id_str.split("_")[1])
                        from profile_bank import get_bank_info, create_or_update_bank
                        bank_data = await get_bank_info(chat_id, banker_id)
                        lender_name = bank_data.get('name', 'Неизвестный Банк') if bank_data else 'Банк'
                        if bank_data:
                            await create_or_update_bank(chat_id, banker_id, {'capital': bank_data.get('capital', 0) + pay_amount})
                        collector_msg = f"\n\n🦹‍♂️ <b>КОЛЛЕКТОРЫ БАНКА!</b> Забрали <b>{pay_amount}</b> сыр. в счет долга."
                    else:
                        lender_id = int(lender_id_str)
                        lender_data = await get_user_data(chat_id, lender_id)
                        lender_name = lender_data.get('full_name', 'Кредитор')
                        await update_user_balance(chat_id, lender_id, pay_amount, is_debt_repayment=True)
                        collector_msg = f"\n\n🦹‍♂️ <b>ЧАСТНЫЕ КОЛЛЕКТОРЫ!</b> Забрали <b>{pay_amount}</b> сыр. в счет долга."
            else:
                penalty = rand.randint(100, 300)
                final_earnings = 0
                await update_user_balance(chat_id, user_id, -penalty, is_debt_repayment=True)
                collector_msg = f"\n\n🦹‍♂️ <b>КОЛЛЕКТОРЫ!</b> Выбили <b>{penalty}</b> сыр. штрафа."
        elif pet_id == 'dragon' and (debts or balance < 0):
            pet_msg += " И отпугнул коллекторов!"

        final_earnings = await apply_season_bonus(final_earnings, "crime")
        if final_earnings > 0:
            await update_user_balance(chat_id, user_id, final_earnings, is_debt_repayment=True)
        
        afk_text = f"🥷 <b>Успешное проникновение!</b> Ты нашел <b>{base_earnings}</b> сыр. на столе.{pet_msg}{collector_msg}"
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        import uuid
        builder = InlineKeyboardBuilder()
        game_id = str(uuid.uuid4())[:8]
        bonus = rand.randint(1500, 4000)
        
        tools = ["🔧", "🪛", "🔑", "🔨", "🪚", "🧲"]
        target = rand.choice(["🔑", "🧲", "🪛"])
        options = rand.sample(tools, 3)
        if target not in options:
            options[0] = target
        rand.shuffle(options)
        
        game_text = f"\n\n🔒 <b>ВЗЛОМ СЕЙФА:</b> Ты нашел огромный сейф! Выбери правильный инструмент (<b>{target}</b>), чтобы вскрыть его!"
        
        for opt in options:
            cb_data = f"crime_btn_{game_id}_1" if opt == target else f"crime_btn_{game_id}_0"
            builder.button(text=opt, callback_data=cb_data)
            
        builder.adjust(3)
        
        active_crime_games[game_id] = {
            'user_id': user_id,
            'bonus': bonus,
            'expires': time.time() + 60
        }
        
        await message.answer(afk_text + game_text, reply_markup=builder.as_markup())
    else:
        fine = rand.randint(500, 1500)
        await update_user_balance(chat_id, user_id, -fine, is_debt_repayment=True)
        await message.answer(f"🚔 Тебя поймали! Суд выписал штраф в <b>{fine}</b> сыроежек.")
@router.message(F.text.lower().startswith("ограбить банк"))
async def cmd_rob_bank(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь грабить банки.")

    if data.get('is_banker', False):
        return await message.answer("🏦 Банкирам запрещено грабить банки коллег!")

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.answer("Использование: <code>ограбить банк [Название или ID]</code>")

    # Cooldown (например, 12 часов)
    last_rob = data.get('last_bank_rob_time', 0)
    current_time = time.time()
    if current_time - last_rob < 43200:
        remain = int(43200 - (current_time - last_rob))
        hours, rem = divmod(remain, 3600)
        mins, _ = divmod(rem, 60)
        return await message.answer(f"⏳ Полиция патрулирует город после недавнего налета. Заляг на дно еще на {hours} ч. {mins} мин.")

    identifier = args[2]
    from profile_bank import get_bank_info, create_or_update_bank
    bank_data = await get_bank_info(chat_id, identifier)

    if not bank_data:
        return await message.answer("🏦 Банк не найден. Проверьте название.")

    target_banker_id = bank_data['banker_id']
    capital = bank_data.get('capital', 0)

    if capital < 10000:
        return await message.answer("В этом банке слишком мало денег, грабить нечего!")

    await update_user_field(chat_id, user_id, 'last_bank_rob_time', current_time)

    rand = secrets.SystemRandom()
    stealth_level = data.get('skills', {}).get('stealth', 0)

    # Базовый шанс успеха - 5% + 2% за каждый уровень стелса
    success_chance = 0.05 + (stealth_level * 0.02)

    if rand.random() < success_chance:
        # Украли от 1% до 5% от капитала банка
        steal_percent = rand.uniform(0.01, 0.05)
        stolen_amount = int(capital * steal_percent)

        await create_or_update_bank(chat_id, target_banker_id, {'capital': capital - stolen_amount})
        await update_user_balance(chat_id, user_id, stolen_amount)

        await message.answer(f"🥷 <b>УСПЕШНОЕ ОГРАБЛЕНИЕ!</b>\n\nВы ворвались в банк <b>{escape_html(bank_data.get('name'))}</b>, вскрыли сейф и вынесли <b>{stolen_amount}</b> сыроежек!\n<i>Банк понес убытки.</i>")
    else:
        # Провал
        penalty = rand.randint(50000, 150000)
        await update_user_balance(chat_id, user_id, -penalty)

        # Выдаем временный мут через aiogram
        from datetime import timedelta
        try:
            await message.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=timedelta(minutes=30)
            )
            mute_text = "\nВас посадили в тюрьму (мут) на 30 минут."
        except:
            mute_text = "\nСпецназ пытался вас арестовать, но вам удалось сбежать, потеряв деньги в спешке."

        await message.answer(f"🚔 <b>ОБЛАВА! СРАБОТАЛА СИГНАЛИЗАЦИЯ!</b>\n\nОграбление банка <b>{escape_html(bank_data.get('name'))}</b> провалилось. Вы потеряли <b>{penalty}</b> сыроежек при побеге.{mute_text}")

@router.callback_query(F.data.startswith("crime_btn_"))
async def process_crime_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4: return
    game_id = parts[2]
    is_correct = parts[3] == "1"
    
    game = active_crime_games.get(game_id)
    if not game:
        return await callback.answer("⏳ Слишком поздно! Сейф заблокировался.", show_alert=True)
        
    if game['user_id'] != callback.from_user.id:
        return await callback.answer("Это не твой сейф!", show_alert=True)
        
    if time.time() > game['expires']:
        del active_crime_games[game_id]
        await callback.message.edit_reply_markup(reply_markup=None)
        return await callback.answer("⏳ Время вышло, копы уже здесь!", show_alert=True)
        
    del active_crime_games[game_id]
    
    original_html = callback.message.html_text if hasattr(callback.message, 'html_text') else callback.message.text
    if not original_html: original_html = ""
        
    chat_id = callback.message.chat.id
    if is_correct:
        await update_user_balance(chat_id, callback.from_user.id, game['bonus'])
        new_text = original_html + f"\n\n💎 <b>ДЖЕКПОТ!</b> Дверца поддалась, и ты вытащил <b>{game['bonus']}</b> сыр.!"
        await callback.message.edit_text(new_text, reply_markup=None)
    else:
        import secrets
        penalty = secrets.SystemRandom().randint(500, 1500)
        await update_user_balance(chat_id, callback.from_user.id, -penalty, is_debt_repayment=True)
        new_text = original_html + f"\n\n🚨 <b>ПРОВАЛ!</b> Инструмент сломался, взвыла сирена! В панике убегая от копов, ты потерял <b>{penalty}</b> сыр."
        await callback.message.edit_text(new_text, reply_markup=None)
