"""Tests for fpl_data.client (HTTP mocked with responses library)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import responses as rsps_lib

from fpl_data.client import FPLClient
from tests.conftest import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, PLAYER_SUMMARY_PAYLOAD


@rsps_lib.activate
def test_get_bootstrap_fetches_and_caches(tmp_path: Path) -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        json=BOOTSTRAP_PAYLOAD,
    )
    client = FPLClient(raw_dir=tmp_path / "raw", cache_ttl_hours=6)
    data = client.get_bootstrap()
    assert data["teams"][0]["name"] == "Arsenal"

    cache_file = tmp_path / "raw" / "bootstrap_static.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text())
    assert cached["teams"][0]["name"] == "Arsenal"


@rsps_lib.activate
def test_get_bootstrap_uses_cache_when_fresh(tmp_path: Path) -> None:
    """Second call must NOT make an HTTP request when cache is fresh."""
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        json=BOOTSTRAP_PAYLOAD,
    )
    client = FPLClient(raw_dir=tmp_path / "raw", cache_ttl_hours=6)
    client.get_bootstrap()          # populates cache
    client.get_bootstrap()          # should read from cache
    assert len(rsps_lib.calls) == 1  # only one real HTTP call


@rsps_lib.activate
def test_get_bootstrap_force_bypasses_cache(tmp_path: Path) -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        json=BOOTSTRAP_PAYLOAD,
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        json=BOOTSTRAP_PAYLOAD,
    )
    client = FPLClient(raw_dir=tmp_path / "raw", cache_ttl_hours=6)
    client.get_bootstrap()
    client.get_bootstrap(force=True)
    assert len(rsps_lib.calls) == 2


@rsps_lib.activate
def test_get_fixtures(tmp_path: Path) -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/fixtures/",
        json=FIXTURES_PAYLOAD,
    )
    client = FPLClient(raw_dir=tmp_path / "raw")
    data = client.get_fixtures()
    assert isinstance(data, list)
    assert data[0]["id"] == 1


@rsps_lib.activate
def test_get_player_summary(tmp_path: Path) -> None:
    rsps_lib.add(
        rsps_lib.GET,
        "https://fantasy.premierleague.com/api/element-summary/1/",
        json=PLAYER_SUMMARY_PAYLOAD,
    )
    client = FPLClient(raw_dir=tmp_path / "raw")
    data = client.get_player_summary(1)
    assert "history" in data
    assert data["history"][0]["total_points"] == 12
