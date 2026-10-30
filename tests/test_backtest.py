from __future__ import annotations

from pathlib import Path

import numpy as np
import responses as rsps_lib
from typer.testing import CliRunner

from fpl_data.backtest import run_backtest, summarise_backtest
from fpl_data.cli import app
from tests.synthetic import make_season


def test_backtest_scores_both_models_without_future_data() -> None:
    bootstrap, raw_fixtures, live = make_season()

    results = run_backtest(bootstrap, raw_fixtures, live, [2, 3])

    assert set(results["model"]) == {"new_model", "legacy"}
    assert results.groupby("model").size().to_dict() == {"legacy": 2, "new_model": 2}
    assert np.isfinite(results[["rmse", "mae"]].to_numpy()).all()
    assert list(summarise_backtest(results).index) == ["legacy", "new_model"]


@rsps_lib.activate
def test_backtest_command_prints_model_comparison(tmp_path: Path) -> None:
    bootstrap, raw_fixtures, live = make_season()
    base = "https://fantasy.premierleague.com/api"
    rsps_lib.add(rsps_lib.GET, f"{base}/bootstrap-static/", json=bootstrap)
    rsps_lib.add(rsps_lib.GET, f"{base}/fixtures/", json=raw_fixtures)
    for gameweek, payload in live.items():
        rsps_lib.add(rsps_lib.GET, f"{base}/event/{gameweek}/live/", json=payload)

    result = CliRunner().invoke(app, ["backtest", "--from-gw", "2", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "new_model" in result.output
    assert "Average across gameweeks" in result.output
