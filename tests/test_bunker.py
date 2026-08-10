# tests/test_bunker.py
import pytest
from bunker.models import Game, Player, Phase
from bunker.engine import (
    create_new_game, start_game_engine, reveal_player_card,
    cast_vote, check_voting_complete, process_voting_results,
    kick_player_from_game, calculate_epilogue
)
from bunker.cards_img import render_player_dossier_png
from bunker.ui import format_lobby_text, format_stage_text

def test_bunker_game_flow():
    game = create_new_game("test_123", chat_id=-100123456, host_id=111, host_name="Alice")
    
    # Add players
    game.players[111] = Player(user_id=111, name="Alice", username="alice", seat=1)
    game.players[222] = Player(user_id=222, name="Bob", username="bob", seat=2)
    game.players[333] = Player(user_id=333, name="Charlie", username="charlie", seat=3)

    assert len(game.players) == 3
    assert game.phase == Phase.LOBBY

    # Test lobby text
    lobby_txt = format_lobby_text(game)
    assert "Alice" in lobby_txt

    # Start game
    started = start_game_engine(game)
    assert started is True
    assert game.phase == Phase.INTRO
    assert game.capacity == 1  # 3 // 2 = 1

    # Check player cards
    player_111 = game.players[111]
    assert len(player_111.cards) == 10
    assert player_111.special_card is not None

    # Test card PNG generation
    png_buf = render_player_dossier_png(player_111, game.scenario)
    assert png_buf is not None
    assert len(png_buf.getvalue()) > 1000

    # Reveal card
    game.phase = Phase.REVEAL
    success, msg = reveal_player_card(game, 111, "profession")
    assert success is True
    assert player_111.cards["profession"].revealed is True

    # Stage text
    stage_txt = format_stage_text(game, "test_bot")
    assert "Alice" in stage_txt
    assert "Профессия" in stage_txt

    # Voting
    game.phase = Phase.VOTING
    cast_vote(game, 111, 222)
    cast_vote(game, 333, 222)
    cast_vote(game, 222, 111)

    assert check_voting_complete(game) is True
    kicked_id, is_tie = process_voting_results(game)
    assert is_tie is False
    assert kicked_id == 222

    # Kick player 222
    kick_msg = kick_player_from_game(game, 222)
    assert "Bob" in kick_msg
    assert game.players[222].alive is False

    # Second voting to reach capacity 1
    game.votes.clear()
    cast_vote(game, 111, 333)
    cast_vote(game, 333, 111)
    # Tie test
    kicked_id_2, is_tie_2 = process_voting_results(game)
    assert is_tie_2 is True

    # Epilogue calculation
    epilogue = calculate_epilogue(game)
    assert "ФИНАЛЬНЫЙ ЭПИЛОГ" in epilogue
    assert "Выжившие в бункере" in epilogue
