# tests/test_bunker.py
import pytest
import random
from bunker.models import Game, Player, Phase, escape_html
from bunker.engine import (
    create_new_game, add_player, remove_player, start_game_engine,
    reveal_player_card, cast_vote, check_voting_complete, process_voting_results,
    kick_player_from_game, advance_round, calculate_epilogue, finish_game,
    cleanup_stale_games, active_games
)
from bunker.cards_img import render_player_dossier_png
from bunker.ui import format_lobby_text, format_stage_text, get_lobby_keyboard, get_stage_keyboard


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
    assert "ФИНАЛЬНЫЙ ЭПИЛОГ" in epilogue


SAMPLE_NAMES = [
    "Алексей <Хакер>", "Мария & Ко", "Дмитрий 'Шеф'", "Елена <VIP>",
    "Иван > Охотник", "Ольга & Co", "Сергей \"Лидер\"", "Анна <Врач>",
    "Павел", "Наталья", "Артем", "Виктория", "Максим", "Екатерина",
    "Владимир", "Татьяна"
]


@pytest.mark.parametrize(
    "game_idx",
    range(1, 501),
    ids=[f"game_case_{i:03d}" for i in range(1, 501)]
)
def test_simulated_bunker_game_instance(game_idx: int):
    """
    Каждый из 500 отдельных тестов симулирует изолированную партию игры «Бункер».
    """
    gid = f"b{game_idx}_99999"
    chat_id = -1000000 - game_idx
    host_id = 1000 + game_idx
    host_name = random.choice(SAMPLE_NAMES)

    g = create_new_game(gid, chat_id, host_id, host_name)
    player_count = random.randint(2, 12)

    for p_i in range(player_count):
        uid = (game_idx * 100) + p_i
        p_name = f"{random.choice(SAMPLE_NAMES)} #{p_i}"
        add_player(g, uid, p_name, f"user_{uid}")

    assert len(g.players) == player_count

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
        if len(alive) <= g.capacity:
            break

        # 1. Фаза REVEAL
        g.phase = Phase.REVEAL
        for p in alive:
            hidden = p.hidden_cards()
            if hidden:
                card_to_rev = random.choice(hidden)
                reveal_player_card(g, p.user_id, card_to_rev.category_id)

        # 2. Фаза VOTING
        g.phase = Phase.VOTING
        g.votes.clear()
        for voter in alive:
            targets = [target.user_id for target in alive if target.user_id != voter.user_id]
            if targets:
                target_id = random.choice(targets)
                cast_vote(g, voter.user_id, target_id)

        kicked_id, is_tie, _ = process_voting_results(g)
        if is_tie:
            g.phase = Phase.TIEBREAK
            g.votes.clear()
            for voter in alive:
                targets = [t for t in g.tie_candidates if t != voter.user_id]
                if targets:
                    cast_vote(g, voter.user_id, random.choice(targets))
            kicked_id, is_tie, _ = process_voting_results(g)

        if kicked_id:
            kick_player_from_game(g, kicked_id)

        cont = advance_round(g)
        if not cont:
            break

    epilogue_txt = calculate_epilogue(g)
    assert "ФИНАЛЬНЫЙ ЭПИЛОГ" in epilogue_txt
    finish_game(g)
    assert g.phase is Phase.FINISHED
