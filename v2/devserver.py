"""Локальный стенд Mini App без Telegram (только для разработки).

    python -m v2.devserver [порт]

Поднимает API и фронтенд на 127.0.0.1, создаёт тестовый чат с игроками-ботами,
которые сидят в зале, ставят в Краш/Рулетку/Складчину и принимают дуэли.
Ссылка для браузера печатается при старте. В продакшене не используется.
"""
import asyncio
import os
import random
import sys
import tempfile
import time
from pathlib import Path

_tmp = Path(tempfile.gettempdir())
os.environ.setdefault("V2_DEV", "1")
os.environ.setdefault("DB_BACKEND", "local")
os.environ.setdefault("LOCAL_DB_PATH", str(_tmp / "kazik_v2_dev_db.json"))
os.environ.setdefault("BOT_TOKEN", "123456789:" + "D" * 35)
os.environ.setdefault("V2_AVATAR_DIR", str(_tmp / "kazik_v2_dev_avatars"))

CHAT = -1001234567890
ME = 1
BOTS = [
    (101, "Сыроежкин", "Грибники"), (102, "Маша Лисичкина", "Грибники"), (103, "Боровик", None),
    (104, "Опятя", "Мухоморы"), (105, "Груздь Петрович", "Мухоморы"), (106, "Лена", None),
    (107, "Подберёзовик", "Грибники"), (108, "Ksenia", None), (109, "Рыжик", "Мухоморы"),
    (110, "Дед Валуй", None), (111, "Волнушка", None), (112, "Моховик", "Грибники"),
]
ACTS = ["lobby", "crash", "roulette", "bj", "slots", "mines", "jackpot", "games", "top", "dice", "duel", "poker"]


def _avatars(handles):
    """Рисует простые «фото» для ботов, чтобы на стенде были видны аватарки."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return
    out = Path(os.environ["V2_AVATAR_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    for h in handles:
        path = out / f"{h}.jpg"
        if path.exists():
            path.touch()
            continue
        size = 160
        a = tuple(rnd.randint(40, 230) for _ in range(3))
        b = tuple(rnd.randint(20, 160) for _ in range(3))
        img = Image.new("RGB", (size, size), a)
        d = ImageDraw.Draw(img)
        for y in range(size):
            k = y / size
            d.line([(0, y), (size, y)], fill=tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3)))
        for _ in range(4):
            r = rnd.randint(18, 60)
            x, y = rnd.randint(0, size), rnd.randint(0, size)
            d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randint(60, 255) for _ in range(3)))
        d.ellipse([52, 34, 108, 90], fill=(242, 214, 190))
        d.ellipse([30, 92, 130, 190], fill=tuple(rnd.randint(30, 200) for _ in range(3)))
        img = img.filter(ImageFilter.GaussianBlur(1.2))
        img.save(path, "JPEG", quality=82)


async def seed():
    from db import get_db, init_db
    from user_manager import flush_user_data, get_user_data
    from v2 import profile, security, settings
    from v2.wallet import save

    init_db(None)
    await settings.set_enabled(CHAT, True, ME)
    rnd = random.Random(42)
    people = [(ME, "Ты-тестер", "Грибники")] + BOTS
    for uid, name, clan in people:
        data = await get_user_data(CHAT, uid, name)
        data["full_name"] = name
        if int(data.get("balance", 0) or 0) < 1000:
            data["balance"] = 250_000 if uid == ME else rnd.choice([12_000, 48_000, 150_000, 900_000, 2_400_000, 31_000_000])
        if clan:
            data["clan"] = clan
        s = profile.st(data)
        if not s.get("xp"):
            s["xp"] = rnd.randint(200, 60_000) if uid != ME else 4_200
        save(CHAT, uid, data)
    await flush_user_data()
    clans = get_db().collection("chats").document(str(CHAT)).collection("clans")
    await clans.document("Грибники").set({"members": [101, 102, 107, 112, ME], "treasury": 1_250_000})
    await clans.document("Мухоморы").set({"members": [104, 105, 109], "treasury": 480_000})
    _avatars([security.handle_for(uid) for uid, _, _ in people])


def _ctx(uid, name, clan):
    from v2 import security
    from v2.wallet import Ctx
    c = Ctx(CHAT, uid, name, name, security.handle_for(uid))
    c.clan = clan
    return c


async def crowd():
    """Боты: присутствие, ставки на общих столах, быстрые игры для ленты и лиги."""
    from v2 import api, live
    from v2.games import solo, tables
    from v2.wallet import GameError

    hub = await live.hub(CHAT)
    rnd = random.Random()
    bots = [(_ctx(uid, name, clan)) for uid, name, clan in BOTS]
    acts = {c.uid: rnd.choice(ACTS) for c in bots}
    crash_rid = roul_rid = ""
    while True:
        await asyncio.sleep(1.0)
        now = time.time()
        for c in bots[:9]:
            if rnd.random() < 0.05:
                acts[c.uid] = rnd.choice(ACTS)
            hub.touch(c.uid, c.handle, c.name, acts[c.uid])
        try:
            t = tables.table(hub, "crash")
            if t.phase == "bet" and t.rid != crash_rid and t.t_bet_end - now < 5:
                crash_rid = t.rid
                for c in rnd.sample(bots, rnd.randint(2, 6)):
                    auto = rnd.choice([1.3, 1.5, 2.0, 2.5, 3.0, 5.0, 10.0])
                    try:
                        await t.bet(c, rnd.choice([100, 500, 1000, 2500, 10_000]), auto, c.clan)
                    except GameError:
                        pass
            r = tables.table(hub, "roulette")
            if r.phase == "bet" and r.rid != roul_rid and r.t_next - now < 12:
                roul_rid = r.rid
                for c in rnd.sample(bots, rnd.randint(1, 5)):
                    for _ in range(rnd.randint(1, 3)):
                        kind = rnd.choice(["n", "red", "black", "odd", "even", "dozen", "col", "low", "high"])
                        value = rnd.randrange(37) if kind == "n" else rnd.randint(1, 3) if kind in ("dozen", "col") else None
                        try:
                            await r.bet(c, kind, value, rnd.choice([100, 300, 1000, 5000]), c.clan)
                        except GameError:
                            pass
            j = tables.table(hub, "jackpot")
            if j.phase in ("open", "count") and len(j.bets) < 5 and rnd.random() < 0.08:
                c = rnd.choice(bots)
                try:
                    await j.bet(c, rnd.choice([1000, 5000, 20_000, 50_000]), c.clan)
                except GameError:
                    pass
            for d in list(hub.duels.values()):
                if d["state"] == "open" and d["uid"] == ME and now - d["ts"] > 6 and not d["target"]:
                    try:
                        await tables.duel_accept(hub, rnd.choice(bots), d["id"])
                    except GameError:
                        pass
            if not any(d["state"] == "open" and d["uid"] != ME for d in hub.duels.values()) and rnd.random() < 0.05:
                c = rnd.choice(bots)
                direct = rnd.random() < 0.4
                await tables.duel_create(hub, c, rnd.choice([1000, 5000, 25_000]), ME if direct else None,
                                         "Ты-тестер" if direct else "", c.clan)
            if rnd.random() < 0.25:
                c = rnd.choice(bots)
                game = rnd.choice(["slots", "dice", "cups"])
                bet = rnd.choice([200, 1000, 5000, 20_000])
                res = await (solo.slots(c, bet) if game == "slots" else solo.dice(c, bet, rnd.choice(["hi", "lo", "seven"]))
                             if game == "dice" else solo.cups(c, bet, 3, rnd.randrange(3)))
                api._after_game(hub, c, game, res)
        except Exception as exc:  # стенд не должен падать из-за одной ставки
            print("crowd:", type(exc).__name__, exc)


async def main(port: int):
    from aiohttp import web
    from v2 import api, security
    from v2.games import tables

    await seed()
    app = web.Application()
    app.router.add_get("/", lambda r: web.HTTPFound(f"/app/?dev={ME}:Ты-тестер&c={security.chat_token(CHAT)}"))
    api.setup(app, None)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    asyncio.create_task(tables.loop())
    asyncio.create_task(crowd())
    print(f"Казик V2 dev: http://127.0.0.1:{port}/app/?dev={ME}:Ты-тестер&c={security.chat_token(CHAT)}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8090))
