from __future__ import annotations

import pandas as pd

from dashboard.components import formation_label, render_pitch


def make_squad() -> pd.DataFrame:
    positions = ["GKP", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD", "GKP", "DEF", "MID", "FWD"]
    rows = []
    for squad_pos, position in enumerate(positions, start=1):
        rows.append({
            "id": squad_pos,
            "web_name": "<Captain>" if squad_pos == 9 else f"Player {squad_pos}",
            "team_short": "ARS",
            "position": position,
            "squad_pos": squad_pos,
            "is_captain": squad_pos == 9,
            "is_vice_captain": squad_pos == 10,
            "event_points": squad_pos,
            "selling_price": 50,
            "status": "a",
        })
    return pd.DataFrame(rows)


def test_formation_label_uses_starting_xi_position_counts() -> None:
    assert formation_label(make_squad()) == "3-4-3"


def test_render_pitch_groups_formation_and_bench() -> None:
    html = render_pitch(make_squad(), gameweek=4)

    assert "Formation 3-4-3" in html
    assert html.count('class="pitch-row"') == 4
    assert "Bench" in html
    assert "GW4 points" in html
    assert "&lt;Captain&gt;" in html
    assert "<Captain>" not in html
