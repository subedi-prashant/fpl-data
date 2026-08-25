"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


BOOTSTRAP_PAYLOAD: dict = {
    "teams": [
        {
            "id": 1,
            "name": "Arsenal",
            "short_name": "ARS",
            "strength": 4,
            "strength_overall_home": 1280,
            "strength_overall_away": 1260,
            "strength_attack_home": 1280,
            "strength_attack_away": 1270,
            "strength_defence_home": 1260,
            "strength_defence_away": 1250,
        }
    ],
    "elements": [
        {
            "id": 1,
            "first_name": "Bukayo",
            "second_name": "Saka",
            "web_name": "Saka",
            "team": 1,
            "element_type": 3,
            "now_cost": 100,
            "total_points": 180,
            "minutes": 2700,
            "goals_scored": 12,
            "assists": 10,
            "clean_sheets": 8,
            "selected_by_percent": "45.5",
            "status": "a",
            "form": "7.5",
            "points_per_game": "6.8",
        }
    ],
    "events": [
        {
            "id": 1,
            "name": "Gameweek 1",
            "deadline_time": "2025-08-16T10:00:00Z",
            "average_entry_score": 55,
            "finished": True,
            "is_current": False,
            "is_next": False,
            "highest_score": 102,
        }
    ],
}

FIXTURES_PAYLOAD: list = [
    {
        "id": 1,
        "event": 1,
        "team_h": 1,
        "team_a": 2,
        "team_h_difficulty": 3,
        "team_a_difficulty": 4,
        "team_h_score": 2,
        "team_a_score": 0,
        "finished": True,
        "kickoff_time": "2025-08-16T12:30:00Z",
    }
]

PLAYER_SUMMARY_PAYLOAD: dict = {
    "history": [
        {
            "fixture": 1,
            "opponent_team": 2,
            "total_points": 12,
            "round": 1,
            "minutes": 90,
            "goals_scored": 1,
            "assists": 1,
            "clean_sheets": 1,
            "goals_conceded": 0,
            "yellow_cards": 0,
            "red_cards": 0,
            "saves": 0,
            "bonus": 3,
            "bps": 45,
            "value": 100,
        }
    ],
    "fixtures": [],
}
