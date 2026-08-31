"""Data models for FPL entities using stdlib dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Team:
    id: int
    name: str
    short_name: str
    strength: int
    strength_overall_home: int
    strength_overall_away: int
    strength_attack_home: int
    strength_attack_away: int
    strength_defence_home: int
    strength_defence_away: int

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        return cls(
            id=d["id"],
            name=d["name"],
            short_name=d["short_name"],
            strength=d.get("strength", 0),
            strength_overall_home=d.get("strength_overall_home", 0),
            strength_overall_away=d.get("strength_overall_away", 0),
            strength_attack_home=d.get("strength_attack_home", 0),
            strength_attack_away=d.get("strength_attack_away", 0),
            strength_defence_home=d.get("strength_defence_home", 0),
            strength_defence_away=d.get("strength_defence_away", 0),
        )


@dataclass
class Player:
    id: int
    first_name: str
    second_name: str
    web_name: str
    team_id: int
    element_type: int  # 1=GK,2=DEF,3=MID,4=FWD
    now_cost: int      # cost in 0.1 £ units (e.g. 55 → £5.5m)
    total_points: int
    minutes: int
    goals_scored: int
    assists: int
    clean_sheets: int
    selected_by_percent: str
    status: str        # a=available, d=doubtful, i=injured, u=unavailable
    form: str
    points_per_game: str

    @classmethod
    def from_dict(cls, d: dict) -> "Player":
        return cls(
            id=d["id"],
            first_name=d["first_name"],
            second_name=d["second_name"],
            web_name=d["web_name"],
            team_id=d["team"],
            element_type=d["element_type"],
            now_cost=d["now_cost"],
            total_points=d["total_points"],
            minutes=d.get("minutes", 0),
            goals_scored=d.get("goals_scored", 0),
            assists=d.get("assists", 0),
            clean_sheets=d.get("clean_sheets", 0),
            selected_by_percent=d.get("selected_by_percent", "0.0"),
            status=d.get("status", "a"),
            form=d.get("form", "0.0"),
            points_per_game=d.get("points_per_game", "0.0"),
        )


@dataclass
class Fixture:
    id: int
    event: int | None       # gameweek number; None = unscheduled TBD
    team_h: int
    team_a: int
    team_h_difficulty: int
    team_a_difficulty: int
    team_h_score: int | None
    team_a_score: int | None
    finished: bool
    kickoff_time: str | None

    @classmethod
    def from_dict(cls, d: dict) -> "Fixture":
        return cls(
            id=d["id"],
            event=d.get("event"),
            team_h=d["team_h"],
            team_a=d["team_a"],
            team_h_difficulty=d.get("team_h_difficulty", 0),
            team_a_difficulty=d.get("team_a_difficulty", 0),
            team_h_score=d.get("team_h_score"),
            team_a_score=d.get("team_a_score"),
            finished=bool(d.get("finished", False)),
            kickoff_time=d.get("kickoff_time"),
        )


@dataclass
class Gameweek:
    id: int
    name: str
    deadline_time: str
    average_entry_score: int
    finished: bool
    is_current: bool
    is_next: bool
    highest_score: int | None

    @classmethod
    def from_dict(cls, d: dict) -> "Gameweek":
        return cls(
            id=d["id"],
            name=d["name"],
            deadline_time=d["deadline_time"],
            average_entry_score=d.get("average_entry_score", 0),
            finished=bool(d.get("finished", False)),
            is_current=bool(d.get("is_current", False)),
            is_next=bool(d.get("is_next", False)),
            highest_score=d.get("highest_score"),
        )


@dataclass
class PlayerHistory:
    player_id: int
    fixture: int
    opponent_team: int
    total_points: int
    round: int          # gameweek number
    minutes: int
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    yellow_cards: int
    red_cards: int
    saves: int
    bonus: int
    bps: int
    value: int          # cost at that gameweek in 0.1 £ units

    @classmethod
    def from_dict(cls, player_id: int, d: dict) -> "PlayerHistory":
        return cls(
            player_id=player_id,
            fixture=d["fixture"],
            opponent_team=d["opponent_team"],
            total_points=d["total_points"],
            round=d["round"],
            minutes=d.get("minutes", 0),
            goals_scored=d.get("goals_scored", 0),
            assists=d.get("assists", 0),
            clean_sheets=d.get("clean_sheets", 0),
            goals_conceded=d.get("goals_conceded", 0),
            yellow_cards=d.get("yellow_cards", 0),
            red_cards=d.get("red_cards", 0),
            saves=d.get("saves", 0),
            bonus=d.get("bonus", 0),
            bps=d.get("bps", 0),
            value=d.get("value", 0),
        )


@dataclass
class ManagerProfile:
    """User's FPL manager profile information."""
    manager_id: int
    name: str
    team_name: str
    team_value: int        # in 0.1 £ units (e.g., 1050 → £105.0m)
    bank: int              # in 0.1 £ units
    total_points: int
    rank: int | None
    season: int            # e.g., 2024 for 2024-25 season

    @classmethod
    def from_dict(cls, manager_id: int, d: dict) -> "ManagerProfile":
        manager_name = f"{d.get('player_first_name', '')} {d.get('player_last_name', '')}".strip()
        return cls(
            manager_id=manager_id,
            name=manager_name,
            team_name=d.get("name", ""),
            team_value=d.get("last_deadline_value", 0),
            bank=d.get("last_deadline_bank", 0),
            total_points=d.get("summary_overall_points", 0),
            rank=d.get("summary_overall_rank"),
            season=d.get("current_event", 1),
        )


@dataclass
class ManagerTeamPick:
    """A single player picked in a manager's team for a gameweek."""
    manager_id: int
    season: int
    gameweek: int
    player_id: int
    position: int          # 1=GK, 2=DEF, 3=MID, 4=FWD (squad position in team sheet)
    is_captain: bool
    is_vice_captain: bool
    points: int
    multiplier: int        # 1x (auto), 2x (captain), 0x (benched)


@dataclass
class Transfer:
    """A transfer made by the manager."""
    manager_id: int
    season: int
    gameweek: int
    player_out_id: int
    player_in_id: int
    entry_cost: int        # cost in 0.1 £ units
    cost_change_event: int # cumulative change for this player


@dataclass
class ManagerHistory:
    """Season-level history for a manager."""
    manager_id: int
    season: int
    total_points: int
    rank: int | None
    transfers_used: int
    finished: bool         # True if season is complete


@dataclass
class ManagerSeason:
    """Tracks which seasons are available for a manager."""
    manager_id: int
    season: int
    status: str            # "active" or "completed"

    @classmethod
    def from_dict(cls, manager_id: int, season: int, d: dict) -> "ManagerSeason":
        return cls(
            manager_id=manager_id,
            season=season,
            status="completed" if d.get("finished", False) else "active",
        )
