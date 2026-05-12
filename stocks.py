import io
import asyncio
import secrets
import time
import logging
import hashlib
from typing import Dict, Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile, InputMediaPhoto

from db import get_db
from user_manager import get_user_data, update_user_balance, update_user_field
from economy_utils import calculate_progressive_tax, get_global_tax
from utils_pkg.cache_manager import global_cache
from utils import fire_and_forget

router = Router()
secure_random = secrets.SystemRandom()

# Список компаний
COMPANIES = {
    "chzp": {"name": "ГазСыр (CHZP)", "ticker": "CHZP", "desc": "Энергетический гигант сырной промышленности."},
    "smlk": {"name": "SpaceMilk (SMLK)", "ticker": "SMLK", "desc": "Высокие технологии и доставка молока на Луну."},
    "ratt": {"name": "RatTech (RATT)", "ticker": "RATT", "desc": "Оборонные технологии и производство ловушек."},
    "glds": {"name": "Golden Syr (GLDS)", "ticker": "GLDS", "desc": "Крупнейший банк и хранилище золотых головок сыра."}
}

def fmt(num: float | int) -> str:
    try: return f"{int(num):,}".replace(",", ".")
    except Exception: return "0"

# --- ГЕНЕРАЦИЯ ГРАФИКОВ ---
def _generate_stock_chart_sync(name: str, prices: list) -> bytes:
    if not prices: prices = [100]
    is_growing = prices[-1] >= prices[0]
    
    # ПРЕМИУМ ЦВЕТА: Золотой для роста, Стальной для падения
    main_color = '#FBC02D' if is_growing else '#90A4AE' 
    bg_color = '#050A12' # Глубокий темно-синий (корпоративный)
    grid_color = '#1C2735'
    
    fig = Figure(figsize=(9, 5), dpi=100)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    x = list(range(len(prices)))
    
    # 1. Градиентная заливка (Area)
    ax.fill_between(x, prices, min(prices)*0.9, color=main_color, alpha=0.08)
    
    # 2. Основная линия с небольшим свечением
    ax.plot(x, prices, color=main_color, linewidth=3, zorder=10, solid_capstyle='round')
    ax.plot(x, prices, color=main_color, linewidth=6, alpha=0.1, zorder=9)
    
    # 3. Узлы (Dots) на каждой точке для "технического" вида
    ax.scatter(x, prices, color=main_color, s=20, zorder=11, alpha=0.5)
    ax.scatter(x[-1], prices[-1], color='white', s=60, zorder=12, edgecolors=main_color, linewidth=2)

    # 4. Сетка (только горизонтальная для чистоты)
    ax.yaxis.grid(True, color=grid_color, linestyle='--', linewidth=0.5, alpha=0.5)
    ax.xaxis.grid(False)
    
    # 5. Оформление осей
    ax.tick_params(axis='both', colors='#546E7A', labelsize=9)
    ax.set_title(f"CORPORATE INDEX: {name.upper()}", color='white', fontsize=16, pad=25, fontweight='bold', loc='center', fontname='sans-serif')
    
    # Убираем все лишние рамки
    for side in ['top', 'right', 'bottom', 'left']:
        ax.spines[side].set_visible(False)
        
    # Добавляем плашку с текущей ценой
    last_price = prices[-1]
    ax.text(x[-1], last_price, f" {fmt(last_price)} ", color='black', fontweight='bold', 
            bbox=dict(facecolor=main_color, edgecolor='none', boxstyle='round,pad=0.2'),
            ha='left', va='center', fontsize=10)

    fig.tight_layout()
    buf = io.BytesIO()
    canvas.print_png(buf)
    buf.seek(0)
    return buf.read()

async def generate_stock_chart(name: str, prices: list) -> bytes:
    p_hash = hashlib.md5(str(prices).encode()).hexdigest()
    cache_key = f"stock_chart_{name}_{p_hash}"
    cached = global_cache.get(cache_key)
    if cached: return cached
    
    chart_bytes = await asyncio.to_thread(_generate_stock_chart_sync, name, prices)
    global_cache.set(cache_key, chart_bytes, ttl=600)
    return chart_bytes

# --- ЛОГИКА РЫНКА ---
async def get_stocks_db():
    db = get_db()
    doc = await db.collection('bot_settings').document('stocks').get()
    
    from seasons import get_season_config
    cfg = await get_season_config()
    seasonal_stocks = cfg.get('strings', {}).get('stocks', {})
    
    # Объединяем базовые и сезонные компании
    ALL_COMPANIES = {**COMPANIES, **seasonal_stocks}
    
    if doc.exists:
        data = doc.to_dict()
        # Добавляем новые компании в цены если их там нет
        for cid in ALL_COMPANIES:
            if cid not in data['prices']:
                data['prices'][cid] = [secure_random.randint(1000, 5000)]
        return data, ALL_COMPANIES
    
    # Инициализация
    data = {
        'last_update': int(time.time()),
        'prices': {cid: [secure_random.randint(1000, 5000)] for cid in ALL_COMPANIES},
        'news': "Рынок стабилен."
    }
    await db.collection('bot_settings').document('stocks').set(data)
    return data, ALL_COMPANIES

async def update_stocks_task():
    """Фоновая задача обновления рынка акций раз в 30 минут."""
    while True:
        try:
            await asyncio.sleep(1800)
            db = get_db()
            doc = await db.collection('bot_settings').document('stocks').get()
            
            from seasons import get_season_config
            cfg = await get_season_config()
            seasonal_stocks = cfg.get('strings', {}).get('stocks', {})
            ALL_COMPANIES = {**COMPANIES, **seasonal_stocks}

            data = doc.to_dict() if doc.exists else {}
            
            prices = data.get('prices', {cid: [secure_random.randint(1000, 5000)] for cid in ALL_COMPANIES})
            
            new_news = "На рынке без существенных изменений."
            # Шанс новости 20%
            if secure_random.random() < 0.2:
                cid = secure_random.choice(list(ALL_COMPANIES.keys()))
                event = secure_random.choice(["jump", "drop"])
                if event == "jump":
                    impact = secure_random.uniform(1.15, 1.30)
                    new_news = f"🚀 ПОЗИТИВ: Акции {ALL_COMPANIES[cid]['ticker']} взлетели на фоне отличного отчета!"
                else:
                    impact = secure_random.uniform(0.70, 0.85)
                    new_news = f"📉 НЕГАТИВ: Инвесторы избавляются от {ALL_COMPANIES[cid]['ticker']} после скандала!"
            else:
                impact = 1.0
            
            for cid in ALL_COMPANIES:
                history = prices.get(cid, [1000])
                last = history[-1]
                
                # Базовый шум +/- 3%
                change = secure_random.uniform(0.97, 1.03)
                # Применяем влияние новости если это та компания
                if impact != 1.0 and ALL_COMPANIES[cid]['ticker'] in new_news:
                    change *= impact
                
                new_p = max(100, int(last * change))
                history.append(new_p)
                if len(history) > 30: history.pop(0)
                prices[cid] = history
                
            await db.collection('bot_settings').document('stocks').set({
                'prices': prices,
                'last_update': int(time.time()),
                'news': new_news
            }, merge=True)
            
        except Exception as e:
            logging.error(f"Error in stocks task: {e}")

# --- ХЕНДЛЕРЫ ---
@router.message(Command("stocks"))
async def cmd_stocks(message: types.Message):
    data, ALL_COMPANIES = await get_stocks_db()
    prices = data.get('prices', {})
    news = data.get('news', "Нет новостей.")
    
    text = f"🏦 <b>ФОНДОВАЯ БИРЖА</b>\n\n📢 <b>Новости:</b> {news}\n\n"
    builder = InlineKeyboardBuilder()
    
    for cid, info in ALL_COMPANIES.items():
        curr = prices.get(cid, [1000])[-1]
        prev = prices.get(cid, [1000])[-2] if len(prices.get(cid, [])) > 1 else curr
        emoji = "📈" if curr >= prev else "📉"
        text += f"• <b>{info['ticker']}</b>: {fmt(curr)} сыр. {emoji}\n"
        builder.button(text=f"{info['ticker']} | {fmt(curr)}", callback_data=f"stk_view_{cid}")
        
    builder.button(text="💼 Мой портфель", callback_data="stk_portfolio")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "stk_main")
async def cb_stk_main(callback: types.CallbackQuery):
    data, ALL_COMPANIES = await get_stocks_db()
    prices = data.get('prices', {})
    news = data.get('news', "Нет новостей.")
    
    text = f"🏦 <b>ФОНДОВАЯ БИРЖА</b>\n\n📢 <b>Новости:</b> {news}\n\n"
    builder = InlineKeyboardBuilder()
    
    for cid, info in ALL_COMPANIES.items():
        curr = prices.get(cid, [1000])[-1]
        prev = prices.get(cid, [1000])[-2] if len(prices.get(cid, [])) > 1 else curr
        emoji = "📈" if curr >= prev else "📉"
        text += f"• <b>{info['ticker']}</b>: {fmt(curr)} сыр. {emoji}\n"
        builder.button(text=f"{info['ticker']} | {fmt(curr)}", callback_data=f"stk_view_{cid}")
        
    builder.button(text="💼 Мой портфель", callback_data="stk_portfolio")
    builder.adjust(1)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("stk_view_"))
async def cb_stk_view(callback: types.CallbackQuery):
    cid = callback.data.replace("stk_view_", "")
    
    data, ALL_COMPANIES = await get_stocks_db()
    if cid not in ALL_COMPANIES: return
    
    prices = data.get('prices', {}).get(cid, [1000])
    curr = prices[-1]
    
    chart_bytes = await generate_stock_chart(ALL_COMPANIES[cid]['ticker'], prices)
    photo = BufferedInputFile(chart_bytes, filename=f"{cid}.png")
    
    text = (
        f"📊 <b>{ALL_COMPANIES[cid]['name']}</b>\n\n"
        f"📝 {ALL_COMPANIES[cid]['desc']}\n"
        f"💰 Текущая цена: <b>{fmt(curr)}</b> сыр.\n\n"
        f"<i>Графики обновляются раз в 10 минут.</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить (1 шт) 🟢", callback_data=f"stk_buy_1_{cid}")
    builder.button(text="Купить (10 шт) 🟢", callback_data=f"stk_buy_10_{cid}")
    builder.button(text="Продать (1 шт) 🔴", callback_data=f"stk_sell_1_{cid}")
    builder.button(text="Продать всё 🔴", callback_data=f"stk_sell_all_{cid}")
    builder.button(text="⬅️ Назад", callback_data="stk_main")
    builder.adjust(2, 2, 1)
    
    if callback.message.photo:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.delete()
        await callback.message.answer_photo(photo=photo, caption=text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("stk_buy_"))
async def cb_stk_buy(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    qty = int(parts[2])
    cid = parts[3]
    
    data, ALL_COMPANIES = await get_stocks_db()
    price = data.get('prices', {}).get(cid, [1000])[-1]
    
    # Налог на роскошь при покупке
    base_tax = await get_global_tax()
    ud = await get_user_data(callback.message.chat.id, callback.from_user.id)
    tax_rate = calculate_progressive_tax(ud.get('balance', 0), base_tax, ud.get('skills', {}).get('negotiation', 0))
    
    total_cost = int((price * qty) * (1 + tax_rate / 100))
    
    if ud.get('balance', 0) < total_cost:
        return await callback.answer(f"❌ Недостаточно сыра! Нужно {fmt(total_cost)} (с учетом налога {tax_rate}%).", show_alert=True)
    
    await update_user_balance(callback.message.chat.id, callback.from_user.id, -total_cost)
    
    portfolio = ud.get('stocks_portfolio', {})
    portfolio[cid] = portfolio.get(cid, 0) + qty
    await update_user_field(callback.message.chat.id, callback.from_user.id, 'stocks_portfolio', portfolio)
    
    await callback.answer(f"✅ Куплено {qty} акций {ALL_COMPANIES[cid]['ticker']}!")
    await cb_stk_view(callback)

@router.callback_query(F.data.startswith("stk_sell_"))
async def cb_stk_sell(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    qty_str = parts[2]
    cid = parts[3]
    
    ud = await get_user_data(callback.message.chat.id, callback.from_user.id)
    portfolio = ud.get('stocks_portfolio', {})
    
    if cid not in portfolio or portfolio[cid] <= 0:
        return await callback.answer("❌ У вас нет акций этой компании.", show_alert=True)
    
    qty = portfolio[cid] if qty_str == "all" else int(qty_str)
    if portfolio[cid] < qty:
        return await callback.answer("❌ Недостаточно акций для продажи.", show_alert=True)
    
    data, ALL_COMPANIES = await get_stocks_db()
    price = data.get('prices', {}).get(cid, [1000])[-1]
    
    # Комиссия при продаже (фиксированная 5% + прогрессивный налог)
    base_tax = await get_global_tax()
    tax_rate = calculate_progressive_tax(ud.get('balance', 0), base_tax, ud.get('skills', {}).get('negotiation', 0))
    
    total_tax = 5 + tax_rate
    profit = int((price * qty) * (1 - total_tax / 100))
    
    await update_user_balance(callback.message.chat.id, callback.from_user.id, profit)
    
    portfolio[cid] -= qty
    if portfolio[cid] <= 0: del portfolio[cid]
    await update_user_field(callback.message.chat.id, callback.from_user.id, 'stocks_portfolio', portfolio)
    
    await callback.answer(f"✅ Продано {qty} акций! Вы получили {fmt(profit)} сыр (налог {total_tax}%).")
    await cb_stk_view(callback)

@router.callback_query(F.data == "stk_portfolio")
async def cb_stk_portfolio(callback: types.CallbackQuery):
    ud = await get_user_data(callback.message.chat.id, callback.from_user.id)
    portfolio = ud.get('stocks_portfolio', {})
    data, ALL_COMPANIES = await get_stocks_db()
    prices = data.get('prices', {})
    
    text = "💼 <b>ВАШ ИНВЕСТИЦИОННЫЙ ПОРТФЕЛЬ</b>\n\n"
    total_value = 0
    
    if not portfolio:
        text += "<i>Вы пока не владеете акциями.</i>"
    else:
        for cid, qty in portfolio.items():
            if cid in ALL_COMPANIES:
                curr_p = prices.get(cid, [1000])[-1]
                val = qty * curr_p
                total_value += val
                text += f"▪️ <b>{ALL_COMPANIES[cid]['ticker']}</b>: {qty} шт. (≈ {fmt(val)} сыр.)\n"
    
    text += f"\n💰 Оценка активов: <b>{fmt(total_value)}</b> сыр."
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="stk_main")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
