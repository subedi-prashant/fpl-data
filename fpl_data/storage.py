"""Persist raw JSON responses and normalise into SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fpl_data.models import (
    Fixture, Gameweek, Player, PlayerHistory, Team,
    ManagerProfile, ManagerTeamPick, Transfer, ManagerHistory, ManagerSeason,
)

log = logging.getLogger(__name__)


def migrate_db(db_path: Path) -> None:
    """Apply any missing schema changes to an existing DB."""
    con = sqlite3.connect(str(db_path))
    con.executescript(_SCHEMA)
    con.commit()
    con.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id                      INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    short_name              TEXT,
    strength                INTEGER,
    strength_overall_home   INTEGER,
    strength_overall_away   INTEGER,
    strength_attack_home    INTEGER,
    strength_attack_away    INTEGER,
    strength_defence_home   INTEGER,
    strength_defence_away   INTEGER
);

CREATE TABLE IF NOT EXISTS players (
    id                    INTEGER PRIMARY KEY,
    first_name            TEXT,
    second_name           TEXT,
    web_name              TEXT,
    team_id               INTEGER REFERENCES teams(id),
    element_type          INTEGER,
    now_cost              INTEGER,
    total_points          INTEGER,
    minutes               INTEGER,
    goals_scored          INTEGER,
    assists               INTEGER,
    clean_sheets          INTEGER,
    selected_by_percent   TEXT,
    status                TEXT,
    form                  TEXT,
    points_per_game       TEXT
);

CREATE TABLE IF NOT EXISTS fixtures (
    id                  INTEGER PRIMARY KEY,
    event               INTEGER,
    team_h              INTEGER REFERENCES teams(id),
    team_a              INTEGER REFERENCES teams(id),
    team_h_difficulty   INTEGER,
    team_a_difficulty   INTEGER,
    team_h_score        INTEGER,
    team_a_score        INTEGER,
    finished            INTEGER,
    kickoff_time        TEXT
);

CREATE TABLE IF NOT EXISTS gameweeks (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT,
    deadline_time         TEXT,
    average_entry_score   INTEGER,
    finished              INTEGER,
    is_current            INTEGER,
    is_next               INTEGER,
    highest_score         INTEGER
);

CREATE TABLE IF NOT EXISTS player_history (
    player_id       INTEGER REFERENCES players(id),
    fixture         INTEGER,
    opponent_team   INTEGER,
    total_points    INTEGER,
    round           INTEGER,
    minutes         INTEGER,
    goals_scored    INTEGER,
    assists         INTEGER,
    clean_sheets    INTEGER,
    goals_conceded  INTEGER,
    yellow_cards    INTEGER,
    red_cards       INTEGER,
    saves           INTEGER,
    bonus           INTEGER,
    bps             INTEGER,
    value           INTEGER,
    PRIMARY KEY (player_id, fixture)
);

CREATE TABLE IF NOT EXISTS user_profile (
    manager_id              INTEGER PRIMARY KEY,
    name                    TEXT,
    team_name               TEXT,
    team_value              INTEGER,
    bank                    INTEGER,
    total_points            INTEGER,
    rank                    INTEGER,
    season                  INTEGER
);

CREATE TABLE IF NOT EXISTS user_team (
    manager_id              INTEGER REFERENCES user_profile(manager_id),
    season                  INTEGER,
    gameweek                INTEGER,
    player_id               INTEGER REFERENCES players(id),
    position                INTEGER,
    is_captain              INTEGER,
    is_vice_captain         INTEGER,
    points                  INTEGER,
    multiplier              INTEGER,
    PRIMARY KEY (manager_id, season, gameweek, player_id)
);

CREATE TABLE IF NOT EXISTS user_transfers (
    manager_id              INTEGER REFERENCES user_profile(manager_id),
    season                  INTEGER,
    gameweek                INTEGER,
    player_out_id           INTEGER REFERENCES players(id),
    player_in_id            INTEGER REFERENCES players(id),
    entry_cost              INTEGER,
    cost_change_event       INTEGER,
    PRIMARY KEY (manager_id, season, gameweek, player_out_id)
);

CREATE TABLE IF NOT EXISTS user_history (
    manager_id              INTEGER REFERENCES user_profile(manager_id),
    season                  INTEGER,
    total_points            INTEGER,
    rank                    INTEGER,
    transfers_used          INTEGER,
    finished                INTEGER,
    PRIMARY KEY (manager_id, season)
);

CREATE TABLE IF NOT EXISTS user_seasons (
    manager_id              INTEGER REFERENCES user_profile(manager_id),
    season                  INTEGER,
    status                  TEXT,
    PRIMARY KEY (manager_id, season)
);
"""


class Storage:
    def __init__(
        self,
        db_path: Path = Path("data/fpl.db"),
        raw_dir: Path = Path("data/raw"),
    ) -> None:
        self._db_path = db_path
        self._raw_dir = raw_dir
        db_path.parent.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(db_path))
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(_SCHEMA)
        self._con.commit()
        log.info("SQLite DB ready at %s", db_path)

    def close(self) -> None:
        self._con.close()

    # ------------------------------------------------------------------
    # Raw JSON cache
    # ------------------------------------------------------------------

    def save_raw(self, name: str, payload: dict | list) -> Path:
        """Dump *payload* to a timestamped JSON file in raw_dir."""
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self._raw_dir / f"{name}_{ts}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.debug("Raw JSON saved → %s", path)
        return path

    # ------------------------------------------------------------------
    # Upsert helpers
    # ------------------------------------------------------------------

    def upsert_teams(self, teams: list[Team]) -> None:
        rows = [
            (
                t.id, t.name, t.short_name, t.strength,
                t.strength_overall_home, t.strength_overall_away,
                t.strength_attack_home, t.strength_attack_away,
                t.strength_defence_home, t.strength_defence_away,
            )
            for t in teams
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO teams VALUES (?,?,?,?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.info("Upserted %d teams", len(rows))

    def upsert_players(self, players: list[Player]) -> None:
        rows = [
            (
                p.id, p.first_name, p.second_name, p.web_name,
                p.team_id, p.element_type, p.now_cost, p.total_points,
                p.minutes, p.goals_scored, p.assists, p.clean_sheets,
                p.selected_by_percent, p.status, p.form, p.points_per_game,
            )
            for p in players
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO players VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.info("Upserted %d players", len(rows))

    def upsert_fixtures(self, fixtures: list[Fixture]) -> None:
        rows = [
            (
                f.id, f.event, f.team_h, f.team_a,
                f.team_h_difficulty, f.team_a_difficulty,
                f.team_h_score, f.team_a_score,
                int(f.finished), f.kickoff_time,
            )
            for f in fixtures
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO fixtures VALUES (?,?,?,?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.info("Upserted %d fixtures", len(rows))

    def upsert_gameweeks(self, gameweeks: list[Gameweek]) -> None:
        rows = [
            (
                gw.id, gw.name, gw.deadline_time, gw.average_entry_score,
                int(gw.finished), int(gw.is_current), int(gw.is_next),
                gw.highest_score,
            )
            for gw in gameweeks
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO gameweeks VALUES (?,?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.info("Upserted %d gameweeks", len(rows))

    def upsert_player_history(self, histories: list[PlayerHistory]) -> None:
        rows = [
            (
                h.player_id, h.fixture, h.opponent_team, h.total_points,
                h.round, h.minutes, h.goals_scored, h.assists,
                h.clean_sheets, h.goals_conceded, h.yellow_cards,
                h.red_cards, h.saves, h.bonus, h.bps, h.value,
            )
            for h in histories
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO player_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._con.commit()
        log.debug("Upserted %d player_history rows", len(rows))

    def upsert_manager_profile(self, profiles: list[ManagerProfile]) -> None:
        rows = [
            (
                p.manager_id, p.name, p.team_name, p.team_value, p.bank,
                p.total_points, p.rank, p.season,
            )
            for p in profiles
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO user_profile VALUES (?,?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.info("Upserted %d manager profiles", len(rows))

    def upsert_manager_team(self, picks: list[ManagerTeamPick]) -> None:
        rows = [
            (
                p.manager_id, p.season, p.gameweek, p.player_id, p.position,
                int(p.is_captain), int(p.is_vice_captain), p.points, p.multiplier,
            )
            for p in picks
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO user_team VALUES (?,?,?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.debug("Upserted %d manager team picks", len(rows))

    def upsert_manager_transfers(self, transfers: list[Transfer]) -> None:
        rows = [
            (
                t.manager_id, t.season, t.gameweek, t.player_out_id,
                t.player_in_id, t.entry_cost, t.cost_change_event,
            )
            for t in transfers
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO user_transfers VALUES (?,?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.debug("Upserted %d manager transfers", len(rows))

    def upsert_manager_history(self, histories: list[ManagerHistory]) -> None:
        rows = [
            (
                h.manager_id, h.season, h.total_points, h.rank,
                h.transfers_used, int(h.finished),
            )
            for h in histories
        ]
        self._con.executemany(
            "INSERT OR REPLACE INTO user_history VALUES (?,?,?,?,?,?)", rows
        )
        self._con.commit()
        log.info("Upserted %d manager history records", len(rows))

    def upsert_manager_seasons(self, seasons: list[ManagerSeason]) -> None:
        rows = [(s.manager_id, s.season, s.status) for s in seasons]
        self._con.executemany(
            "INSERT OR REPLACE INTO user_seasons VALUES (?,?,?)", rows
        )
        self._con.commit()
        log.debug("Upserted %d manager season records", len(rows))
