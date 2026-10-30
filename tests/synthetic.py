"""A small, fully controlled FPL season in raw API payload shape for model tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

SEASON_START = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
ROLES = [("GKP", 1, 45), ("DEF", 2, 50), ("DEF", 2, 50), ("MID", 3, 70), ("MID", 3, 70), ("FWD", 4, 80)]
FINISHED = [(1, 1, 2, 3, 1), (1, 3, 4, 1, 1), (2, 1, 3, 3, 0), (2, 2, 4, 1, 1), (3, 1, 4, 3, 1), (3, 2, 3, 1, 0)]
UPCOMING = [(4, 2, 1), (4, 4, 3), (5, 3, 1), (5, 4, 2), (6, 4, 1), (6, 3, 2)]


def kickoff(gameweek: int) -> datetime:
    return SEASON_START + timedelta(days=7 * (gameweek - 1))


def player_id(team_id: int, slot: int) -> int:
    return team_id * 10 + slot


def make_season(upcoming: list[tuple[int, int, int]] | None = None) -> tuple[dict, list[dict], dict[int, dict]]:
    upcoming = UPCOMING if upcoming is None else upcoming
    teams = [
        {
            "id": team_id,
            "name": f"Team {team_id}",
            "short_name": f"T{team_id}",
            "strength": None,
            "strength_overall_home": 4 if team_id == 1 else 3,
            "strength_overall_away": 4 if team_id == 1 else 3,
            "strength_attack_home": 0,
            "strength_attack_away": 0,
            "strength_defence_home": 0,
            "strength_defence_away": 0,
        }
        for team_id in range(1, 5)
    ]
    elements = []
    for team_id in range(1, 5):
        for slot, (position, element_type, cost) in enumerate(ROLES, start=1):
            elements.append({
                "id": player_id(team_id, slot),
                "first_name": "Player",
                "second_name": str(player_id(team_id, slot)),
                "web_name": f"P{player_id(team_id, slot)}",
                "team": team_id,
                "element_type": element_type,
                "now_cost": cost + (10 if team_id == 1 else 0),
                "cost_change_start": 0,
                "total_points": 12,
                "event_points": 4,
                "minutes": 270,
                "starts": 3,
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
                "saves": 9 if position == "GKP" else 0,
                "bonus": 1,
                "yellow_cards": 0,
                "red_cards": 0,
                "defensive_contribution": 27 if position in {"DEF", "MID"} else 6,
                "expected_goals": "0.90" if position == "FWD" else "0.30",
                "expected_assists": "0.30",
                "expected_goal_involvements": "1.20",
                "selected_by_percent": "10.0",
                "form": "4.0",
                "points_per_game": "4.0",
                "ep_next": "4.0",
                "status": "a",
                "chance_of_playing_next_round": None,
                "news": "",
                "news_added": None,
                "penalties_order": None,
                "scout_risks": None,
            })
    events = [
        {
            "id": gameweek,
            "name": f"Gameweek {gameweek}",
            "deadline_time": (kickoff(gameweek) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "finished": gameweek <= 3,
            "is_current": gameweek == 3,
            "is_next": gameweek == 4,
            "average_entry_score": 50,
            "highest_score": 100,
        }
        for gameweek in range(1, 7)
    ]
    bootstrap = {
        "teams": teams,
        "elements": elements,
        "events": events,
        "game_config": {"scoring": {"goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}}},
    }
    fixtures = []
    for fixture_id, (gameweek, home, away, home_goals, away_goals) in enumerate(FINISHED, start=1):
        fixtures.append({
            "id": fixture_id,
            "event": gameweek,
            "kickoff_time": kickoff(gameweek).isoformat().replace("+00:00", "Z"),
            "team_h": home,
            "team_a": away,
            "team_h_score": home_goals,
            "team_a_score": away_goals,
            "team_h_difficulty": 3,
            "team_a_difficulty": 3,
            "finished": True,
            "started": True,
        })
    for offset, (gameweek, home, away) in enumerate(upcoming, start=len(fixtures) + 1):
        fixtures.append({
            "id": offset,
            "event": gameweek,
            "kickoff_time": (kickoff(gameweek) + timedelta(hours=offset % 3)).isoformat().replace("+00:00", "Z"),
            "team_h": home,
            "team_a": away,
            "team_h_score": None,
            "team_a_score": None,
            "team_h_difficulty": 2 if away != 1 else 4,
            "team_a_difficulty": 2 if home != 1 else 4,
            "finished": False,
            "started": False,
        })
    live = {}
    for gameweek in range(1, 4):
        payload = []
        for element in elements:
            position = ROLES[element["id"] % 10 - 1][0]
            strong = element["team"] == 1
            payload.append({
                "id": element["id"],
                "stats": {
                    "minutes": 90,
                    "starts": 1,
                    "goals_scored": 1 if strong and position == "FWD" else 0,
                    "assists": 0,
                    "clean_sheets": 0,
                    "goals_conceded": 1,
                    "saves": 3 if position == "GKP" else 0,
                    "bonus": 1 if strong and position == "FWD" else 0,
                    "bps": 20,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "defensive_contribution": 9 if position in {"DEF", "MID"} else 2,
                    "expected_goals": ("0.80" if strong else "0.30") if position == "FWD" else "0.10",
                    "expected_assists": "0.10",
                    "expected_goals_conceded": "1.00",
                    "total_points": 8 if strong and position == "FWD" else 3,
                },
            })
        live[gameweek] = {"elements": payload}
    return bootstrap, fixtures, live
