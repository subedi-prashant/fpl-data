"""Tests for fpl_data.models."""

from __future__ import annotations

from tests.conftest import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, PLAYER_SUMMARY_PAYLOAD
from fpl_data.models import Fixture, Gameweek, Player, PlayerHistory, Team


def test_team_from_dict() -> None:
    t = Team.from_dict(BOOTSTRAP_PAYLOAD["teams"][0])
    assert t.id == 1
    assert t.name == "Arsenal"
    assert t.short_name == "ARS"
    assert t.strength == 4


def test_player_from_dict() -> None:
    p = Player.from_dict(BOOTSTRAP_PAYLOAD["elements"][0])
    assert p.id == 1
    assert p.web_name == "Saka"
    assert p.team_id == 1
    assert p.element_type == 3
    assert p.now_cost == 100
    assert p.total_points == 180


def test_fixture_from_dict() -> None:
    f = Fixture.from_dict(FIXTURES_PAYLOAD[0])
    assert f.id == 1
    assert f.event == 1
    assert f.team_h == 1
    assert f.team_a == 2
    assert f.finished is True
    assert f.team_h_score == 2


def test_gameweek_from_dict() -> None:
    gw = Gameweek.from_dict(BOOTSTRAP_PAYLOAD["events"][0])
    assert gw.id == 1
    assert gw.name == "Gameweek 1"
    assert gw.finished is True
    assert gw.is_current is False


def test_player_history_from_dict() -> None:
    h = PlayerHistory.from_dict(1, PLAYER_SUMMARY_PAYLOAD["history"][0])
    assert h.player_id == 1
    assert h.fixture == 1
    assert h.total_points == 12
    assert h.goals_scored == 1
    assert h.bonus == 3


def test_fixture_optional_fields() -> None:
    """Fixtures without a gameweek (TBD) should parse cleanly."""
    d = {
        "id": 99,
        "event": None,
        "team_h": 5,
        "team_a": 6,
        "team_h_difficulty": 3,
        "team_a_difficulty": 2,
        "team_h_score": None,
        "team_a_score": None,
        "finished": False,
        "kickoff_time": None,
    }
    f = Fixture.from_dict(d)
    assert f.event is None
    assert f.finished is False
