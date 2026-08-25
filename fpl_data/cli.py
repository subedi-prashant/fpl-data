"""Typer CLI for the fpl-data package."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from fpl_data.client import FPLClient
from fpl_data.models import Fixture, Gameweek, Player, PlayerHistory, Team
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
) -> None:
    """Fetch bootstrap, fixtures, and all player histories; store everything."""
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


if __name__ == "__main__":
    app()
