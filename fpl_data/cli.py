"""Typer CLI for the fpl-data package."""

from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env from cwd or any parent directory
except ImportError:
    pass  # python-dotenv is optional (only in dev extras)
from typing import Annotated

import typer

from fpl_data.client import FPLClient
from fpl_data.models import (
    Fixture, Gameweek, Player, PlayerHistory, Team,
    ManagerProfile, ManagerTeamPick, Transfer, ManagerHistory, ManagerSeason,
)
from fpl_data.storage import Storage

app = typer.Typer(help="Fetch and store Fantasy Premier League data.")

# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

CacheTTLOption = Annotated[
    float,
    typer.Option("--cache-ttl", help="Bootstrap cache TTL in hours (default 6)."),
]
VerboseOption = Annotated[
    bool,
    typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
]
DataDirOption = Annotated[
    Path,
    typer.Option("--data-dir", help="Root directory for data files."),
]

_DEFAULT_DATA = Path("data")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _make_client_and_storage(
    data_dir: Path, cache_ttl: float
) -> tuple[FPLClient, Storage]:
    raw_dir = data_dir / "raw"
    db_path = data_dir / "fpl.db"
    client = FPLClient(raw_dir=raw_dir, cache_ttl_hours=cache_ttl)
    storage = Storage(db_path=db_path, raw_dir=raw_dir)
    return client, storage


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("fetch-all")
def fetch_all(
    cache_ttl: CacheTTLOption = 6.0,
    verbose: VerboseOption = False,
    data_dir: DataDirOption = _DEFAULT_DATA,
    manager_id: ManagerIDOption = None,
) -> None:
    """Fetch bootstrap, fixtures, all player histories, and optionally personal account data."""
    _setup_logging(verbose)
    log = logging.getLogger(__name__)
    client, storage = _make_client_and_storage(data_dir, cache_ttl)

    # --- bootstrap ---
    bootstrap = client.get_bootstrap()
    storage.save_raw("bootstrap_static", bootstrap)

    teams = [Team.from_dict(t) for t in bootstrap["teams"]]
    storage.upsert_teams(teams)

    players = [Player.from_dict(p) for p in bootstrap["elements"]]
    storage.upsert_players(players)

    gameweeks = [Gameweek.from_dict(gw) for gw in bootstrap["events"]]
    storage.upsert_gameweeks(gameweeks)

    # --- fixtures ---
    raw_fixtures = client.get_fixtures()
    storage.save_raw("fixtures", raw_fixtures)
    fixtures = [Fixture.from_dict(f) for f in raw_fixtures]
    storage.upsert_fixtures(fixtures)

    # --- player histories ---
    total = len(players)
    for idx, player in enumerate(players, start=1):
        log.info("Player summary %d/%d (id=%d)", idx, total, player.id)
        summary = client.get_player_summary(player.id)
        storage.save_raw(f"player_{player.id}", summary)
        histories = [
            PlayerHistory.from_dict(player.id, h)
            for h in summary.get("history", [])
        ]
        if histories:
            storage.upsert_player_history(histories)

    storage.close()

    # Also fetch personal manager data if a manager ID is provided
    if manager_id is not None or os.getenv("FPL_MANAGER_ID"):
        typer.echo("Fetching personal account data…")
        fetch_manager(
            manager_id=manager_id,
            season=None,
            verbose=verbose,
            data_dir=data_dir,
        )
    else:
        typer.echo("✓ fetch-all complete.")


@app.command("fetch-players")
def fetch_players(
    cache_ttl: CacheTTLOption = 6.0,
    verbose: VerboseOption = False,
    data_dir: DataDirOption = _DEFAULT_DATA,
) -> None:
    """Fetch bootstrap and store teams, players, and gameweeks only."""
    _setup_logging(verbose)
    client, storage = _make_client_and_storage(data_dir, cache_ttl)

    bootstrap = client.get_bootstrap()
    storage.save_raw("bootstrap_static", bootstrap)
    storage.upsert_teams([Team.from_dict(t) for t in bootstrap["teams"]])
    storage.upsert_players([Player.from_dict(p) for p in bootstrap["elements"]])
    storage.upsert_gameweeks([Gameweek.from_dict(gw) for gw in bootstrap["events"]])

    storage.close()
    typer.echo("✓ fetch-players complete.")


@app.command("fetch-fixtures")
def fetch_fixtures(
    verbose: VerboseOption = False,
    data_dir: DataDirOption = _DEFAULT_DATA,
) -> None:
    """Fetch and store fixtures only."""
    _setup_logging(verbose)
    client, storage = _make_client_and_storage(data_dir, cache_ttl=0)

    raw_fixtures = client.get_fixtures()
    storage.save_raw("fixtures", raw_fixtures)
    storage.upsert_fixtures([Fixture.from_dict(f) for f in raw_fixtures])

    storage.close()
    typer.echo("✓ fetch-fixtures complete.")


@app.command("refresh")
def refresh(
    cache_ttl: CacheTTLOption = 0.0,
    verbose: VerboseOption = False,
    data_dir: DataDirOption = _DEFAULT_DATA,
) -> None:
    """Re-fetch everything, ignoring the cache (TTL defaults to 0)."""
    _setup_logging(verbose)
    log = logging.getLogger(__name__)
    client, storage = _make_client_and_storage(data_dir, cache_ttl)

    log.info("Force-refresh: cache_ttl=%.1fh", cache_ttl)

    bootstrap = client.get_bootstrap(force=(cache_ttl == 0.0))
    storage.save_raw("bootstrap_static", bootstrap)
    storage.upsert_teams([Team.from_dict(t) for t in bootstrap["teams"]])
    players = [Player.from_dict(p) for p in bootstrap["elements"]]
    storage.upsert_players(players)
    storage.upsert_gameweeks([Gameweek.from_dict(gw) for gw in bootstrap["events"]])

    raw_fixtures = client.get_fixtures()
    storage.save_raw("fixtures", raw_fixtures)
    storage.upsert_fixtures([Fixture.from_dict(f) for f in raw_fixtures])

    total = len(players)
    for idx, player in enumerate(players, start=1):
        log.info("Player summary %d/%d (id=%d)", idx, total, player.id)
        summary = client.get_player_summary(player.id)
        storage.save_raw(f"player_{player.id}", summary)
        histories = [
            PlayerHistory.from_dict(player.id, h)
            for h in summary.get("history", [])
        ]
        if histories:
            storage.upsert_player_history(histories)

    storage.close()
    typer.echo("✓ refresh complete.")


ManagerIDOption = Annotated[
    int | None,
    typer.Option(
        "--manager-id",
        help="Your FPL manager ID (public entry ID). If not provided, reads from FPL_MANAGER_ID env var.",
    ),
]
SeasonOption = Annotated[
    int | None,
    typer.Option("--season", help="Season year (e.g., 2024 for 2024-25). Defaults to current."),
]


def _get_manager_id(manager_id: int | None) -> int:
    """Get manager ID from argument or environment variable."""
    if manager_id is not None and manager_id > 0:
        return manager_id
    
    env_id = os.getenv("FPL_MANAGER_ID")
    if env_id:
        try:
            return int(env_id)
        except ValueError:
            raise typer.BadParameter(f"Invalid FPL_MANAGER_ID in environment: {env_id}")
    
    raise typer.BadParameter("Manager ID must be provided via --manager-id or FPL_MANAGER_ID env var")


@app.command("fetch-manager")
def fetch_manager(
    manager_id: ManagerIDOption = None,
    season: SeasonOption = None,
    verbose: VerboseOption = False,
    data_dir: DataDirOption = _DEFAULT_DATA,
) -> None:
    """Fetch personal FPL account data (profile, team picks, transfers) and store."""
    _setup_logging(verbose)
    log = logging.getLogger(__name__)
    
    # Resolve manager ID from arg or env var
    try:
        resolved_manager_id = _get_manager_id(manager_id)
    except typer.BadParameter as e:
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(code=1)
    
    client, storage = _make_client_and_storage(data_dir, cache_ttl=0)

    try:
        # Fetch manager profile and history
        log.info("Fetching manager profile (id=%d)", resolved_manager_id)
        profile_data = client.get_manager(resolved_manager_id)
        storage.save_raw(f"manager_{resolved_manager_id}_profile", profile_data)

        profile = ManagerProfile.from_dict(resolved_manager_id, profile_data)
        storage.upsert_manager_profile([profile])
        log.info("Manager: %s (%s) — Rank: %s, Points: %d",
                 profile.team_name, profile.name, profile.rank or "N/A", profile.total_points)

        # Fetch history and season info
        log.info("Fetching manager history (id=%d)", resolved_manager_id)
        history_data = client.get_manager_history(resolved_manager_id)
        storage.save_raw(f"manager_{resolved_manager_id}_history", history_data)

        # API returns past[].season_name = "2023/24" — extract start year as int
        def _parse_season(season_name: str) -> int:
            return int(season_name.split("/")[0])

        # Derive current season year from bootstrap events
        bootstrap = client.get_bootstrap()
        current_season_year = int(bootstrap["events"][0]["deadline_time"][:4])
        max_gw = max(gw["id"] for gw in bootstrap["events"])
        # Latest played GW = highest finished GW
        played_gws = [gw["id"] for gw in bootstrap["events"] if gw.get("finished")]
        latest_played_gw = max(played_gws) if played_gws else 0

        # Build season list from past history
        seasons_to_fetch: list[int] = []
        if history_data.get("past"):
            for past_season in history_data["past"]:
                seasons_to_fetch.append(_parse_season(past_season["season_name"]))
        # Always include current season
        seasons_to_fetch.append(current_season_year)

        # Filter by requested season if specified
        if season:
            seasons_to_fetch = [s for s in seasons_to_fetch if s == season]
            if not seasons_to_fetch:
                log.warning("Requested season %d not found in manager history", season)

        log.info("Seasons to fetch: %s", seasons_to_fetch)

        # Store manager season records and history
        manager_seasons = []
        manager_histories = []
        for s in seasons_to_fetch:
            manager_seasons.append(ManagerSeason(resolved_manager_id, s, "active"))

        if history_data.get("past"):
            for past in history_data["past"]:
                manager_histories.append(ManagerHistory(
                    manager_id=resolved_manager_id,
                    season=_parse_season(past["season_name"]),
                    total_points=past["total_points"],
                    rank=past.get("rank"),
                    transfers_used=past.get("transfers_made", 0),
                    finished=True,
                ))

        # current[] is per-GW entries; summarise into one season record
        if history_data.get("current"):
            current_gws = history_data["current"]
            total_pts = sum(gw.get("points", 0) for gw in current_gws)
            last_gw = current_gws[-1] if current_gws else {}
            manager_histories.append(ManagerHistory(
                manager_id=resolved_manager_id,
                season=current_season_year,
                total_points=last_gw.get("total_points", total_pts),
                rank=last_gw.get("overall_rank"),
                transfers_used=sum(gw.get("event_transfers", 0) for gw in current_gws),
                finished=False,
            ))

        if manager_seasons:
            storage.upsert_manager_seasons(manager_seasons)
        if manager_histories:
            storage.upsert_manager_history(manager_histories)

        # Fetch team picks for each played GW in the current season only
        for s in seasons_to_fetch:
            if s != current_season_year:
                log.info("Skipping historical pick fetch for season %d (not supported by API)", s)
                continue
            log.info("Fetching team picks for season %d (GW 1–%d)", s, latest_played_gw)

            for gw in range(1, latest_played_gw + 1):
                log.debug("Fetching picks for gameweek %d", gw)
                try:
                    picks_data = client.get_manager_team(resolved_manager_id, gw)
                    storage.save_raw(f"manager_{resolved_manager_id}_gw{gw}", picks_data)

                    picks = []
                    for pick in picks_data.get("picks", []):
                        picks.append(ManagerTeamPick(
                            manager_id=resolved_manager_id,
                            season=s,
                            gameweek=gw,
                            player_id=pick["element"],
                            position=pick["position"],
                            is_captain=pick["is_captain"],
                            is_vice_captain=pick["is_vice_captain"],
                            points=pick.get("points", 0),
                            multiplier=pick.get("multiplier", 1),
                        ))
                    if picks:
                        storage.upsert_manager_team(picks)
                except Exception as e:
                    log.debug("Could not fetch gameweek %d: %s", gw, e)

        # Fetch transfers
        log.info("Fetching manager transfers (id=%d)", resolved_manager_id)
        transfers_data = client.get_manager_transfers(resolved_manager_id)
        storage.save_raw(f"manager_{resolved_manager_id}_transfers", transfers_data)

        transfers = []
        for t in transfers_data:
            transfers.append(Transfer(
                manager_id=resolved_manager_id,
                season=current_season_year,
                gameweek=t["event"],
                player_out_id=t["element_out"],
                player_in_id=t["element_in"],
                entry_cost=t["entry_cost"],
                cost_change_event=t.get("cost_change_event", 0),
            ))
        if transfers:
            storage.upsert_manager_transfers(transfers)

        storage.close()
        typer.echo(f"✓ fetch-manager complete. Processed {len(seasons_to_fetch)} season(s).")

    except Exception as e:
        log.error("Failed to fetch manager data: %s", e)
        storage.close()
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("list-seasons")
def list_seasons(
    manager_id: ManagerIDOption = None,
    verbose: VerboseOption = False,
    data_dir: DataDirOption = _DEFAULT_DATA,
) -> None:
    """List all available seasons for a manager."""
    _setup_logging(verbose)
    log = logging.getLogger(__name__)
    
    # Resolve manager ID from arg or env var
    try:
        resolved_manager_id = _get_manager_id(manager_id)
    except typer.BadParameter as e:
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(code=1)
    
    client, storage = _make_client_and_storage(data_dir, cache_ttl=0)

    try:
        log.info("Fetching available seasons for manager %d", resolved_manager_id)
        history_data = client.get_manager_history(resolved_manager_id)

        seasons = []
        if history_data.get("past"):
            for past in history_data["past"]:
                season = int(past["season_name"].split("/")[0])
                points = past["total_points"]
                rank = past.get("rank", "N/A")
                seasons.append((season, points, rank, "Completed"))

        if history_data.get("current"):
            current_gws = history_data["current"]
            if current_gws:
                last = current_gws[-1]
                # Derive year from bootstrap since current entries have no season field
                bootstrap = client.get_bootstrap()
                season = int(bootstrap["events"][0]["deadline_time"][:4])
                points = last.get("total_points", 0)
                rank = last.get("overall_rank", "N/A")
                seasons.append((season, points, rank, "Active"))

        if seasons:
            typer.echo(f"\nSeasons for manager {resolved_manager_id}:")
            typer.echo("-" * 60)
            typer.echo(f"{'Season':<10} {'Points':<10} {'Rank':<10} {'Status':<15}")
            typer.echo("-" * 60)
            for season, points, rank, status in sorted(seasons, reverse=True):
                typer.echo(f"{season:<10} {points:<10} {rank:<10} {status:<15}")
            typer.echo("-" * 60)
        else:
            typer.echo(f"No seasons found for manager {resolved_manager_id}")

        storage.close()

    except Exception as e:
        log.error("Failed to fetch seasons: %s", e)
        storage.close()
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
