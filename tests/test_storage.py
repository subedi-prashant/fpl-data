"""Tests for fpl_data.storage."""

from __future__ import annotations

from pathlib import Path

from fpl_data.models import Fixture, Gameweek, Player, PlayerHistory, Team
from fpl_data.storage import Storage
from tests.conftest import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, PLAYER_SUMMARY_PAYLOAD


def _make_storage(tmp_path: Path) -> Storage:
    return Storage(
        db_path=tmp_path / "fpl.db",
        raw_dir=tmp_path / "raw",
    )


def test_upsert_teams(tmp_path: Path) -> None:
    st = _make_storage(tmp_path)
    teams = [Team.from_dict(t) for t in BOOTSTRAP_PAYLOAD["teams"]]
    st.upsert_teams(teams)

    cur = st._con.execute("SELECT id, name FROM teams")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == (1, "Arsenal")
    st.close()


def test_upsert_players(tmp_path: Path) -> None:
    st = _make_storage(tmp_path)
    teams = [Team.from_dict(t) for t in BOOTSTRAP_PAYLOAD["teams"]]
    st.upsert_teams(teams)
    players = [Player.from_dict(p) for p in BOOTSTRAP_PAYLOAD["elements"]]
    st.upsert_players(players)

    cur = st._con.execute("SELECT id, web_name FROM players")
    rows = cur.fetchall()
    assert rows[0] == (1, "Saka")
    st.close()


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    """Running upsert twice must not duplicate rows."""
    st = _make_storage(tmp_path)
    teams = [Team.from_dict(t) for t in BOOTSTRAP_PAYLOAD["teams"]]
    st.upsert_teams(teams)
    st.upsert_teams(teams)

    count = st._con.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    assert count == 1
    st.close()


def test_upsert_fixtures(tmp_path: Path) -> None:
    st = _make_storage(tmp_path)
    fixtures = [Fixture.from_dict(f) for f in FIXTURES_PAYLOAD]
    st.upsert_fixtures(fixtures)

    count = st._con.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0]
    assert count == 1
    st.close()


def test_upsert_gameweeks(tmp_path: Path) -> None:
    st = _make_storage(tmp_path)
    gameweeks = [Gameweek.from_dict(gw) for gw in BOOTSTRAP_PAYLOAD["events"]]
    st.upsert_gameweeks(gameweeks)

    row = st._con.execute("SELECT id, name FROM gameweeks").fetchone()
    assert row == (1, "Gameweek 1")
    st.close()


def test_upsert_player_history(tmp_path: Path) -> None:
    st = _make_storage(tmp_path)
    # need players table populated first (FK)
    teams = [Team.from_dict(t) for t in BOOTSTRAP_PAYLOAD["teams"]]
    st.upsert_teams(teams)
    players = [Player.from_dict(p) for p in BOOTSTRAP_PAYLOAD["elements"]]
    st.upsert_players(players)

    histories = [
        PlayerHistory.from_dict(1, h)
        for h in PLAYER_SUMMARY_PAYLOAD["history"]
    ]
    st.upsert_player_history(histories)

    count = st._con.execute("SELECT COUNT(*) FROM player_history").fetchone()[0]
    assert count == 1
    st.close()


def test_save_raw_creates_file(tmp_path: Path) -> None:
    st = _make_storage(tmp_path)
    path = st.save_raw("test_payload", {"key": "value"})
    assert path.exists()
    assert "test_payload" in path.name
    st.close()
