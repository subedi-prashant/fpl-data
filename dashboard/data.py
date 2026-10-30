"""Cached data loading for the dashboard: public FPL API -> tidy frames -> xP model."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd
import requests
import streamlit as st

from fpl_data import frames
from fpl_data.client import BASE_URL, build_session
from fpl_data.projections import Projections, project_players, scoring_from_bootstrap, upcoming_gameweeks
from fpl_data.recommendations import build_manager_squad, infer_free_transfers

CACHE_TTL = 15 * 60
MAX_HORIZON = 6


@dataclass
class League:
    scoring: dict
    teams: pd.DataFrame
    players: pd.DataFrame
    gameweeks: pd.DataFrame
    fixtures: pd.DataFrame
    stats: pd.DataFrame
    current_gw: int
    next_gw: int | None
    fetched_at: pd.Timestamp

    @property
    def season_label(self) -> str:
        first_deadline = self.gameweeks["deadline_time"].min()
        if pd.isna(first_deadline):
            return ""
        return f"{first_deadline.year}/{str(first_deadline.year + 1)[-2:]}"

    @property
    def next_deadline(self) -> pd.Timestamp | None:
        upcoming = self.gameweeks[self.gameweeks["id"] == self.next_gw]
        return None if upcoming.empty else upcoming.iloc[0]["deadline_time"]


@dataclass
class Manager:
    manager_id: int
    name: str
    team_name: str
    rank: int | None
    total_points: int
    event_points: int
    team_value: int
    bank: int
    gameweek: int
    free_transfers: int
    squad: pd.DataFrame
    history: dict = field(default_factory=dict)
    transfers: list = field(default_factory=list)


@st.cache_resource
def _session() -> requests.Session:
    return build_session()


def _get_all(paths: list[str], workers: int = 4) -> list:
    """Fetch several endpoints in parallel; worker threads never touch Streamlit APIs."""
    session = _session()

    def get(path: str) -> dict | list:
        response = session.get(f"{BASE_URL}/{path}", timeout=30)
        response.raise_for_status()
        return response.json()

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(paths)))) as pool:
        return list(pool.map(get, paths))


@st.cache_data(ttl=CACHE_TTL, show_spinner="Fetching the latest FPL data…")
def _fetch_league_payloads() -> tuple[dict, list[dict]]:
    bootstrap, raw_fixtures = _get_all(["bootstrap-static/", "fixtures/"])
    return bootstrap, raw_fixtures


@st.cache_data(ttl=6 * 3600, max_entries=4, show_spinner="Loading gameweek stats…")
def _fetch_gameweek_stats(finished_gameweeks: tuple[int, ...]) -> pd.DataFrame:
    payloads = _get_all([f"event/{gameweek}/live/" for gameweek in finished_gameweeks])
    return frames.build_gameweek_stats(dict(zip(finished_gameweeks, payloads)))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_league() -> League:
    bootstrap, raw_fixtures = _fetch_league_payloads()
    teams = frames.build_teams(bootstrap)
    gameweeks = frames.build_gameweeks(bootstrap)
    finished = tuple(int(gameweek) for gameweek in gameweeks.loc[gameweeks["finished"], "id"])
    current = gameweeks.loc[gameweeks["is_current"], "id"]
    upcoming = upcoming_gameweeks(gameweeks, 1)
    return League(
        scoring=scoring_from_bootstrap(bootstrap),
        teams=teams,
        players=frames.build_players(bootstrap),
        gameweeks=gameweeks,
        fixtures=frames.build_fixtures(raw_fixtures, teams),
        stats=_fetch_gameweek_stats(finished) if finished else frames.build_gameweek_stats({}),
        current_gw=int(current.iloc[0]) if not current.empty else 1,
        next_gw=upcoming[0] if upcoming else None,
        fetched_at=pd.Timestamp.now(tz="UTC"),
    )


@st.cache_data(ttl=CACHE_TTL, show_spinner="Projecting points for every player…")
def load_projections() -> Projections:
    league = load_league()
    return project_players(
        league.players,
        league.teams,
        league.fixtures,
        league.stats,
        upcoming_gameweeks(league.gameweeks, MAX_HORIZON),
        league.scoring,
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=200, show_spinner="Loading your team…")
def _fetch_manager_payloads(manager_id: int) -> tuple[dict, dict, list]:
    profile, history, transfers = _get_all([f"entry/{manager_id}/", f"entry/{manager_id}/history/", f"entry/{manager_id}/transfers/"])
    return profile, history, transfers


@st.cache_data(ttl=CACHE_TTL, max_entries=200, show_spinner=False)
def _fetch_picks(manager_id: int, gameweek: int) -> dict:
    return _get_all([f"entry/{manager_id}/event/{gameweek}/picks/"])[0]


def load_manager(manager_id: int) -> Manager:
    """Load a public manager's squad. Raises `requests.RequestException` on API errors."""
    league = load_league()
    profile, history, transfers = _fetch_manager_payloads(manager_id)
    gameweek = int(profile.get("current_event") or 0)
    picks = _fetch_picks(manager_id, gameweek) if gameweek else {}
    entry_history = picks.get("entry_history", {})
    squad = build_manager_squad(league.players, picks, transfers, history) if picks else pd.DataFrame()
    return Manager(
        manager_id=manager_id,
        name=f"{profile.get('player_first_name', '')} {profile.get('player_last_name', '')}".strip(),
        team_name=profile.get("name") or "Unnamed team",
        rank=profile.get("summary_overall_rank"),
        total_points=int(profile.get("summary_overall_points") or 0),
        event_points=int(entry_history.get("points", profile.get("summary_event_points") or 0)),
        team_value=int(entry_history.get("value", profile.get("last_deadline_value") or 0)),
        bank=int(entry_history.get("bank", profile.get("last_deadline_bank") or 0)),
        gameweek=gameweek,
        free_transfers=infer_free_transfers(history),
        squad=squad,
        history=history,
        transfers=transfers,
    )


def refresh() -> None:
    st.cache_data.clear()
