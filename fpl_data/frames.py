"""Build tidy pandas DataFrames from raw FPL API payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Not eligible",
}
GAMEWEEK_STAT_COLUMNS = [
    "minutes",
    "starts",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "bps",
    "yellow_cards",
    "red_cards",
    "defensive_contribution",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "total_points",
]


def _float(value: object) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _scout_risks(value: object) -> list[dict]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def build_teams(bootstrap: Mapping) -> pd.DataFrame:
    rows = [
        {
            "id": int(team["id"]),
            "name": team.get("name", ""),
            "short_name": team.get("short_name", ""),
            "strength_overall_home": int(team.get("strength_overall_home") or 0),
            "strength_overall_away": int(team.get("strength_overall_away") or 0),
            "strength_attack_home": int(team.get("strength_attack_home") or 0),
            "strength_attack_away": int(team.get("strength_attack_away") or 0),
            "strength_defence_home": int(team.get("strength_defence_home") or 0),
            "strength_defence_away": int(team.get("strength_defence_away") or 0),
        }
        for team in bootstrap.get("teams", [])
    ]
    return pd.DataFrame(rows)


def build_players(bootstrap: Mapping) -> pd.DataFrame:
    teams = {int(team["id"]): team for team in bootstrap.get("teams", [])}
    rows = []
    for element in bootstrap.get("elements", []):
        team = teams.get(int(element["team"]), {})
        rows.append({
            "id": int(element["id"]),
            "web_name": element.get("web_name", ""),
            "full_name": f"{element.get('first_name', '')} {element.get('second_name', '')}".strip(),
            "team_id": int(element["team"]),
            "team": team.get("name", ""),
            "team_short": team.get("short_name", ""),
            "element_type": int(element["element_type"]),
            "position": POSITION_MAP.get(int(element["element_type"]), "?"),
            "now_cost": int(element.get("now_cost") or 0),
            "cost_change_start": int(element.get("cost_change_start") or 0),
            "total_points": int(element.get("total_points") or 0),
            "event_points": int(element.get("event_points") or 0),
            "minutes": int(element.get("minutes") or 0),
            "starts": int(element.get("starts") or 0),
            "goals_scored": int(element.get("goals_scored") or 0),
            "assists": int(element.get("assists") or 0),
            "clean_sheets": int(element.get("clean_sheets") or 0),
            "saves": int(element.get("saves") or 0),
            "bonus": int(element.get("bonus") or 0),
            "yellow_cards": int(element.get("yellow_cards") or 0),
            "red_cards": int(element.get("red_cards") or 0),
            "defensive_contribution": int(element.get("defensive_contribution") or 0),
            "expected_goals": _float(element.get("expected_goals")),
            "expected_assists": _float(element.get("expected_assists")),
            "expected_goal_involvements": _float(element.get("expected_goal_involvements")),
            "selected_pct": _float(element.get("selected_by_percent")),
            "form": _float(element.get("form")),
            "ppg": _float(element.get("points_per_game")),
            "ep_next": _float(element.get("ep_next")),
            "status": element.get("status") or "a",
            "chance_of_playing": element.get("chance_of_playing_next_round"),
            "news": element.get("news") or "",
            "news_added": element.get("news_added"),
            "penalties_order": element.get("penalties_order"),
            "scout_risks": _scout_risks(element.get("scout_risks")),
        })
    players = pd.DataFrame(rows)
    if players.empty:
        return players
    players["news_added"] = pd.to_datetime(players["news_added"], utc=True, errors="coerce")
    players["cost_m"] = players["now_cost"] / 10.0
    players["value"] = (players["total_points"] / players["cost_m"].where(players["cost_m"] > 0)).round(1).fillna(0.0)
    players["status_label"] = players["status"].map(STATUS_LABELS).fillna(players["status"])
    return players


def build_gameweeks(bootstrap: Mapping) -> pd.DataFrame:
    rows = [
        {
            "id": int(event["id"]),
            "name": event.get("name", ""),
            "deadline_time": event.get("deadline_time"),
            "finished": bool(event.get("finished", False)),
            "is_current": bool(event.get("is_current", False)),
            "is_next": bool(event.get("is_next", False)),
            "average_entry_score": event.get("average_entry_score"),
            "highest_score": event.get("highest_score"),
        }
        for event in bootstrap.get("events", [])
    ]
    gameweeks = pd.DataFrame(rows)
    if not gameweeks.empty:
        gameweeks["deadline_time"] = pd.to_datetime(gameweeks["deadline_time"], utc=True, errors="coerce")
    return gameweeks


def build_fixtures(raw_fixtures: Iterable[Mapping], teams: pd.DataFrame) -> pd.DataFrame:
    team_lookup = teams.set_index("id") if not teams.empty else pd.DataFrame()
    rows = []
    for fixture in raw_fixtures:
        home_id = int(fixture["team_h"])
        away_id = int(fixture["team_a"])
        rows.append({
            "id": int(fixture["id"]),
            "event": fixture.get("event"),
            "kickoff_time": fixture.get("kickoff_time"),
            "team_h_id": home_id,
            "team_h": team_lookup["name"].get(home_id, "") if not team_lookup.empty else "",
            "team_h_short": team_lookup["short_name"].get(home_id, "") if not team_lookup.empty else "",
            "team_a_id": away_id,
            "team_a": team_lookup["name"].get(away_id, "") if not team_lookup.empty else "",
            "team_a_short": team_lookup["short_name"].get(away_id, "") if not team_lookup.empty else "",
            "team_h_difficulty": int(fixture.get("team_h_difficulty") or 3),
            "team_a_difficulty": int(fixture.get("team_a_difficulty") or 3),
            "team_h_score": fixture.get("team_h_score"),
            "team_a_score": fixture.get("team_a_score"),
            "finished": bool(fixture.get("finished", False)),
            "started": bool(fixture.get("started", False)),
        })
    fixtures = pd.DataFrame(rows)
    if fixtures.empty:
        return fixtures
    fixtures["kickoff_time"] = pd.to_datetime(fixtures["kickoff_time"], utc=True, errors="coerce")
    fixtures["event"] = pd.to_numeric(fixtures["event"], errors="coerce").astype("Int64")
    fixtures["gw"] = fixtures["event"]
    return fixtures


def build_gameweek_stats(live_payloads: Mapping[int, Mapping]) -> pd.DataFrame:
    """Flatten `/event/{gw}/live/` payloads into one row per player per gameweek."""
    rows = []
    for gameweek, payload in live_payloads.items():
        for element in payload.get("elements", []):
            stats = element.get("stats", {})
            row = {"player_id": int(element["id"]), "gw": int(gameweek)}
            row.update({column: _float(stats.get(column)) for column in GAMEWEEK_STAT_COLUMNS})
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["player_id", "gw", *GAMEWEEK_STAT_COLUMNS])
    return pd.DataFrame(rows).sort_values(["player_id", "gw"]).reset_index(drop=True)
