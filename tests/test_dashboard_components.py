from __future__ import annotations

import pandas as pd

from dashboard.components import (
    fixture_badges,
    fixture_run_text,
    formation_label,
    heat_style,
    move_reasons,
    render_pitch,
    status_badge,
)


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
            "next_fixture": "CHE (H)",
            "xp_next": 4.25,
        })
    return pd.DataFrame(rows)


def make_fixtures() -> pd.DataFrame:
    return pd.DataFrame([
        {"team_id": 1, "gw": 9, "label": "CHE (H)", "difficulty": 2},
        {"team_id": 1, "gw": 10, "label": "LIV (A)", "difficulty": 5},
        {"team_id": 1, "gw": 10, "label": "BUR (H)", "difficulty": 1},
        {"team_id": 2, "gw": 9, "label": "ARS (A)", "difficulty": 4},
    ])


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


def test_render_pitch_projection_mode_shows_fixture_xp_and_accessible_flags() -> None:
    squad = make_squad()
    squad.loc[squad["id"] == 2, ["status", "chance_of_playing", "status_label"]] = ["d", 75, "Doubtful"]
    squad.loc[squad["id"] == 3, ["status", "status_label"]] = ["i", "Injured"]

    html = render_pitch(squad, gameweek=9, mode="projection")

    assert "GW9 projection" in html
    assert "CHE (H) · 4.2 xP" in html
    assert ">75%<" in html and ">OUT<" in html
    assert 'aria-label="Player 2, ARS, Doubtful, CHE (H), 4.2 projected points"' in html
    assert 'aria-label="&lt;Captain&gt;, ARS, captain, CHE (H), 4.2 projected points"' in html


def test_status_badge_pairs_colour_with_icon_and_words() -> None:
    assert status_badge({"status": "a"}) == ":green-badge[:material/check_circle: Available]"
    assert status_badge({"status": "d", "chance_of_playing": 50}) == ":orange-badge[:material/medical_services: 50% chance]"
    assert status_badge({"status": "i"}) == ":red-badge[:material/personal_injury: Injured]"
    assert status_badge({"status": "u"}) == ":gray-badge[:material/block: Unavailable]"


def test_fixture_badges_include_difficulty_numbers_doubles_and_blanks() -> None:
    fixtures = make_fixtures()

    badges = fixture_badges(fixtures[fixtures["team_id"] == 1], [9, 10, 11])

    assert badges == ":green-badge[CHE (H) · 2] :red-badge[LIV (A) · 5] :green-badge[BUR (H) · 1] :gray-badge[GW11 blank]"
    assert fixture_run_text(fixtures[fixtures["team_id"] == 1], [9, 10, 11]) == "CHE (H), LIV (A) + BUR (H), Blank"


def test_heat_style_caps_intensity_for_readable_text() -> None:
    assert heat_style(16.0, 8.0) == "background-color: rgba(0, 138, 85, 0.55); color: #211a23"
    assert heat_style(0.0, 8.0).startswith("background-color: rgba(0, 138, 85, 0.00)")
    assert heat_style(float("nan"), 8.0) == ""


def test_move_reasons_explain_projection_injury_fixtures_and_form() -> None:
    outgoing = pd.DataFrame([{
        "web_name": "Hurt", "team_id": 2, "position": "MID", "xp_window": 3.0, "status": "i",
        "availability_note": "Knee injury - Expected back 21 Nov", "xmins_next": 0.0, "xgi90_recent": 0.1,
    }])
    incoming = pd.DataFrame([{
        "web_name": "Fit", "team_id": 1, "position": "MID", "xp_window": 18.5, "status": "a",
        "availability_note": "", "xmins_next": 85.0, "xgi90_recent": 0.6,
    }])

    reasons = move_reasons(outgoing, incoming, make_fixtures(), horizon=2)

    assert reasons[0] == "**Fit** projects **18.5** points over the next 2 gameweeks, against **3.0** for **Hurt**."
    assert "**Hurt** is flagged: Knee injury - Expected back 21 Nov." in reasons
    assert "**Fit** is a nailed starter: about 85 expected minutes next gameweek." in reasons
    assert any(reason.startswith("Easier fixtures") for reason in reasons)
    assert any(reason.startswith("Stronger recent form") for reason in reasons)
