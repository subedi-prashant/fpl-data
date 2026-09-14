"""Tests for fpl_data CLI commands (HTTP mocked with responses library)."""

from __future__ import annotations

from pathlib import Path

import pytest
import responses as rsps_lib
from typer.testing import CliRunner

from fpl_data.cli import app
from tests.conftest import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, PLAYER_SUMMARY_PAYLOAD

runner = CliRunner()


def _register_all_mocks() -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        json=BOOTSTRAP_PAYLOAD,
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/fixtures/",
        json=FIXTURES_PAYLOAD,
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/element-summary/1/",
        json=PLAYER_SUMMARY_PAYLOAD,
    )


@rsps_lib.activate
def test_fetch_players(tmp_path: Path) -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        json=BOOTSTRAP_PAYLOAD,
    )
    result = runner.invoke(app, ["fetch-players", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "fetch-players complete" in result.output


@rsps_lib.activate
def test_fetch_fixtures(tmp_path: Path) -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/fixtures/",
        json=FIXTURES_PAYLOAD,
    )
    result = runner.invoke(app, ["fetch-fixtures", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "fetch-fixtures complete" in result.output


@rsps_lib.activate
def test_fetch_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FPL_MANAGER_ID", raising=False)
    _register_all_mocks()
    result = runner.invoke(
        app, ["fetch-all", "--data-dir", str(tmp_path), "--cache-ttl", "0"]
    )
    assert result.exit_code == 0, result.output
    assert "fetch-all complete" in result.output

    # verify DB was written
    db = tmp_path / "fpl.db"
    assert db.exists()


@rsps_lib.activate
def test_refresh(tmp_path: Path) -> None:
    _register_all_mocks()
    result = runner.invoke(
        app, ["refresh", "--data-dir", str(tmp_path), "--cache-ttl", "0"]
    )
    assert result.exit_code == 0, result.output
    assert "refresh complete" in result.output
