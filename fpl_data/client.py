"""Thin FPL API client with retry/backoff, rate-limiting, and local bootstrap cache."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"
USER_AGENT = "fpl-data/0.1 (github.com/my-fpl; polite-client)"

# Seconds to sleep between individual player-summary requests
_PLAYER_SLEEP = 0.3


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class FPLClient:
    """Thin wrapper around the public FPL REST API."""

    def __init__(
        self,
        raw_dir: Path = Path("data/raw"),
        cache_ttl_hours: float = 6.0,
    ) -> None:
        self._session = _build_session()
        self._raw_dir = raw_dir
        self._cache_ttl_seconds = cache_ttl_hours * 3600
        self._raw_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_bootstrap(self, *, force: bool = False) -> dict:
        """Return bootstrap-static payload; uses local cache if fresh enough."""
        cache_path = self._raw_dir / "bootstrap_static.json"
        if not force and self._is_cache_fresh(cache_path):
            log.info("Bootstrap cache is fresh — loading from %s", cache_path)
            return json.loads(cache_path.read_text(encoding="utf-8"))

        log.info("Fetching bootstrap-static from FPL API")
        data = self._get(f"{BASE_URL}/bootstrap-static/")
        cache_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.debug("Bootstrap cached to %s", cache_path)
        return data

    def get_fixtures(self) -> list[dict]:
        """Return full fixture list."""
        log.info("Fetching fixtures from FPL API")
        return self._get(f"{BASE_URL}/fixtures/")

    def get_player_summary(self, player_id: int) -> dict:
        """Return per-player gameweek history and upcoming fixtures."""
        log.debug("Fetching player summary for id=%d", player_id)
        data = self._get(f"{BASE_URL}/element-summary/{player_id}/")
        time.sleep(_PLAYER_SLEEP)
        return data

    def get_manager(self, manager_id: int) -> dict:
        """Return manager profile (name, team value, rank, points)."""
        log.info("Fetching manager profile for id=%d", manager_id)
        return self._get(f"{BASE_URL}/entry/{manager_id}/")

    def get_manager_history(self, manager_id: int) -> dict:
        """Return manager's season-by-season history and fixtures."""
        log.info("Fetching manager history for id=%d", manager_id)
        return self._get(f"{BASE_URL}/entry/{manager_id}/history/")

    def get_manager_team(self, manager_id: int, gameweek: int) -> dict:
        """Return manager's team picks for a specific gameweek."""
        log.debug("Fetching manager team for id=%d, gameweek=%d", manager_id, gameweek)
        return self._get(f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/")

    def get_manager_transfers(self, manager_id: int) -> dict:
        """Return manager's transfer history."""
        log.info("Fetching manager transfers for id=%d", manager_id)
        return self._get(f"{BASE_URL}/entry/{manager_id}/transfers/")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, url: str) -> dict | list:
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def _is_cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < self._cache_ttl_seconds
