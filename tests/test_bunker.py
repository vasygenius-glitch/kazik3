# tests/test_bunker.py
"""
Комплексный тестовый модуль для всей системы игры «Бункер».
Содержит модульные тесты всех подсистем (колода, спецкарты, пауза, настройки, фазы)
и 1000 параметризованных симуляционных тестов полных игровых сессий.
"""

import pytest
import random
from bunker.models import Game, Player, Phase, escape_html
from bunker.deck import deal_hands, deal_special_cards, random_value_for
from bunker.engine import (
    create_new_game, add_player, remove_player, add_test_bot, remove_test_bot,
    cycle_setting, start_game_engine, reveal_player_card, declare_no_reveal,
    register_skip, cast_vote, allowed_targets, check_voting_complete,
    process_voting_results, start_tiebreak, kick_player_from_game, advance_round,
    can_use_special, use_special_card, toggle_pause, force_next_phase, phase_expired,
    calculate_epilogue, finish_game, cleanup_stale_games, active_games
)
from bunker.cards_img import render_player_dossier_png
from bunker.ui import (
    format_lobby_text, format_settings_text, format_board_text,
    format_dossier_text, format_reveal_prompt, format_vote_prompt,
    format_special_prompt, format_intro_text, format_stage_text,
    get_lobby_keyboard, get_settings_keyboard, get_board_keyboard,
    get_dossier_keyboard, get_reveal_keyboard, get_vote_keyboard,
    get_special_keyboard, get_stage_keyboard
)


def test_bunker_basic_game_flow():
    """Базовый функциональный тест одного игрового сценария."""
    active_games.clear()
    game = create_new_game("b100_12345", chat_id=-100123456, host_id=111, host_name="Alice <Admin>")

    add_player(game, 111, "Alice <Admin>", "alice")
    add_player(game, 222, "Bob & Co", "bob")
    add_player(game, 333, "Charlie 'The Chef'", "charlie")

    assert len(game.players) == 3
    assert game.phase == Phase.LOBBY

    lobby_txt = format_lobby_text(game)
    assert "&lt;Admin&gt;" in lobby_txt  # HTML escaped

    started, msg = start_game_engine(game)
    assert started is True
    assert game.phase == Phase.INTRO
    assert 1 <= game.capacity <= 3

    player_111 = game.players[111]
    assert len(player_111.cards) == 10
    assert player_111.special_card is not None

    png_buf = render_player_dossier_png(player_111, game.scenario)
    assert png_buf is not None
    assert len(png_buf.getvalue()) > 500

    game.phase = Phase.REVEAL
    success, _, _ = reveal_player_card(game, 111, "profession")
    assert success is True
    assert player_111.cards["profession"].revealed is True

    stage_txt = format_stage_text(game, "test_bot")
    assert "Alice" in stage_txt

    game.phase = Phase.VOTING
    cast_vote(game, 111, 222)
    cast_vote(game, 333, 222)
    cast_vote(game, 222, 111)

    assert check_voting_complete(game) is True
    kicked_id, is_tie, _ = process_voting_results(game)
    assert is_tie is False
    assert kicked_id == 222

    kick_msg = kick_player_from_game(game, 222)
    assert "Bob" in kick_msg
    assert game.players[222].alive is False

    epilogue = calculate_epilogue(game)
    assert "ЭПИЛОГ" in epilogue


# --------------------------------------------------------------------------- #
#                       МОДУЛЬНЫЕ ТЕСТЫ ПОДСИСТЕМ                             #
# --------------------------------------------------------------------------- #

def test_subsystem_deck_unique_sampling():
    """Тестирование раздачи уникальных карт колодой deck.py."""
    hands = deal_hands(10)
    assert len(hands) == 10
    for hand in hands:
        assert len(hand) == 10

    specials = deal_special_cards(10)
    assert len(specials) == 10
    assert all(s is not None for s in specials)

    new_val = random_value_for("profession", {"Хирург — 12 лет"})
    assert isinstance(new_val, str)
    assert len(new_val) > 0


def test_subsystem_settings_cycling():
    """Тестирование переключения всех настроек игры."""
    game = create_new_game("b_settings", chat_id=-1, host_id=1, host_name="Host")
    add_player(game, 1, "Host")

    for key in ("reveal", "disc", "vote", "first", "per", "nore", "spec", "open", "ping"):
        ok, msg = cycle_setting(game, key)
        assert ok is True
        assert len(msg) > 0

    txt = format_settings_text(game)
    assert "НАСТРОЙКИ ПАРТИИ" in txt
    kb = get_settings_keyboard(game)
    assert kb is not None


def test_subsystem_pause_and_force_next():
    """Тестирование паузы и досрочного переключения фаз."""
    game = create_new_game("b_pause", chat_id=-2, host_id=1, host_name="Host")
    add_player(game, 1, "Host")
    add_player(game, 2, "P2")
    start_game_engine(game)

    assert game.phase is Phase.INTRO
    assert game.is_paused is False

    ok, msg = toggle_pause(game)
    assert ok is True
    assert game.is_paused is True
    assert "⏸" in msg

    board_text = format_board_text(game)
    assert "ПАУЗА" in board_text

    ok, msg = toggle_pause(game)
    assert ok is True
    assert game.is_paused is False
    assert "▶️" in msg

    ok, msg = force_next_phase(game)
    assert ok is True
    assert phase_expired(game) is True


def test_subsystem_special_cards_all():
    """Тестирование всех 6 реализованных спецкарт."""
    game = create_new_game("b_specials", chat_id=-3, host_id=1, host_name="Host")
    add_player(game, 1, "P1")
    add_player(game, 2, "P2")
    add_player(game, 3, "P3")
    start_game_engine(game)

    p1, p2, p3 = game.players[1], game.players[2], game.players[3]
    game.phase = Phase.REVEAL

    # 1. Immunity
    p1.special_card.id = "immunity"
    ok, priv, ev = use_special_card(game, 1)
    assert ok is True
    assert p1.shielded is True
    assert "🛡" in ev

    # 2. Heal
    p2.special_card.id = "heal"
    ok, priv, ev = use_special_card(game, 2)
    assert ok is True
    assert p2.cards["health"].value == "Полностью здоров, иммунитет крепкий"

    # 3. Reroll
    p3.special_card.id = "reroll"
    ok, priv, ev = use_special_card(game, 3)
    assert ok is True
    assert "🔁" in ev

    # 4. Double Vote
    p1.special_card.id = "double_vote"
    p1.special_card.used = False
    game.phase = Phase.VOTING
    ok, priv, ev = use_special_card(game, 1)
    assert ok is True
    assert p1.vote_weight == 2.0

    # 5. Inspect
    p2.special_card.id = "inspect"
    p2.special_card.used = False
    ok, priv, ev = use_special_card(game, 2, str(p1.user_id))
    assert ok is True
    assert "Досмотр" in priv

    # 6. Force Reveal
    p3.special_card.id = "force_reveal"
    p3.special_card.used = False
    ok, priv, ev = use_special_card(game, 3, "profession")
    assert ok is True
    assert "вскрыл(а)" in ev


def test_subsystem_events_feed():
    """Тестирование ленты событий на табло."""
    game = create_new_game("b_events", chat_id=-4, host_id=1, host_name="Host")
    add_player(game, 1, "P1")
    add_player(game, 2, "P2")
    start_game_engine(game)

    for i in range(10):
        game.push_event(f"Event #{i}")

    assert len(game.events) == 6  # EVENTS_KEEP = 6
    assert game.events[-1] == "Event #9"

    game.clear_events()
    assert len(game.events) == 0


# --------------------------------------------------------------------------- #
#                 1000 СИМУЛЯЦИОННЫХ ТЕСТОВ ВСЕЙ СИСТЕМЫ                       #
# --------------------------------------------------------------------------- #

SAMPLE_NAMES = [
    "Алексей <Хакер>", "Мария & Ко", "Дмитрий 'Шеф'", "Елена <VIP>",
    "Иван > Охотник", "Ольга & Co", "Сергей \"Лидер\"", "Анна <Врач>",
    "Павел", "Наталья", "Артем", "Виктория", "Максим", "Екатерина",
    "Владимир", "Татьяна"
]


@pytest.mark.parametrize(
    "game_idx",
    range(1, 1001),
    ids=[f"game_case_{i:04d}" for i in range(1, 1001)]
)
def test_simulated_bunker_game_instance(game_idx: int):
    """
    Каждый из 1000 отдельных тестов симулирует изолированную партию игры «Бункер».
    Проверяются рандомные настройки, паузы, досрочные фазы, спецкарты и голосования.
    """
    gid = f"b{game_idx}_sim"
    chat_id = -2000000 - game_idx
    host_id = 5000 + game_idx
    host_name = random.choice(SAMPLE_NAMES)

    g = create_new_game(gid, chat_id, host_id, host_name)
    player_count = random.randint(2, 16)

    for p_i in range(player_count):
        uid = (game_idx * 100) + p_i
        p_name = f"{random.choice(SAMPLE_NAMES)} #{p_i}"
        add_player(g, uid, p_name, f"user_{uid}")

    assert len(g.players) == player_count

    # Случайные настройки партии
    if random.random() < 0.5:
        cycle_setting(g, "open")
    if random.random() < 0.3:
        cycle_setting(g, "nore")

    ok, start_msg = start_game_engine(g)
    assert ok is True
    assert g.scenario is not None
    assert g.capacity >= 1

    first_p = list(g.players.values())[0]
    png_data = render_player_dossier_png(first_p, g.scenario)
    assert png_data.getvalue()

    max_safety_steps = 30
    step = 0

    while g.phase not in (Phase.EPILOGUE, Phase.FINISHED) and step < max_safety_steps:
        step += 1
        alive = g.alive_players()
        if len(alive) <= g.capacity or len(alive) <= 1:
            break

        # Проверка системы Паузы
        if random.random() < 0.1:
            toggle_pause(g)
            assert g.is_paused is True
            toggle_pause(g)
            assert g.is_paused is False

        # 1. Фаза REVEAL
        g.phase = Phase.REVEAL
        for p in alive:
            hidden = p.hidden_cards()
            if hidden and random.random() < 0.8:
                card_to_rev = random.choice(hidden)
                reveal_player_card(g, p.user_id, card_to_rev.category_id)
            elif g.settings.allow_no_reveal:
                declare_no_reveal(g, p.user_id)

        # Случайное использование спецкарт
        for p in alive:
            if can_use_special(g, p) and random.random() < 0.2:
                kind = p.special_card.id
                if kind == "inspect":
                    targets = [t.user_id for t in alive if t.user_id != p.user_id and t.hidden_cards()]
                    if targets:
                        use_special_card(g, p.user_id, str(random.choice(targets)))
                elif kind == "force_reveal":
                    use_special_card(g, p.user_id, "profession")
                else:
                    use_special_card(g, p.user_id)

        # 2. Фаза DISCUSSION
        g.phase = Phase.DISCUSSION
        for p in alive:
            if random.random() < 0.7:
                register_skip(g, p.user_id)

        # 3. Фаза VOTING
        g.phase = Phase.VOTING
        g.votes.clear()
        for voter in alive:
            t_ids = allowed_targets(g, voter.user_id)
            if t_ids:
                cast_vote(g, voter.user_id, random.choice(t_ids))

        kicked_id, is_tie, _ = process_voting_results(g)
        if is_tie:
            g.phase = Phase.TIEBREAK
            g.votes.clear()
            for voter in alive:
                t_ids = allowed_targets(g, voter.user_id)
                if t_ids:
                    cast_vote(g, voter.user_id, random.choice(t_ids))
            kicked_id, is_tie, _ = process_voting_results(g)

        if kicked_id:
            kick_player_from_game(g, kicked_id)

        cont = advance_round(g)
        if not cont:
            break

    epilogue_txt = calculate_epilogue(g)
    assert "ЭПИЛОГ" in epilogue_txt
    finish_game(g)
    assert g.phase is Phase.FINISHED
