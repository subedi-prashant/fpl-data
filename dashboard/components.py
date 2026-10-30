from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

import pandas as pd

TEAM_COLORS = {
    "ARS": ("#E30613", "#FFFFFF", "#FFFFFF"),
    "AVL": ("#670E36", "#95BFE5", "#FFFFFF"),
    "BOU": ("#DA291C", "#111111", "#FFFFFF"),
    "BRE": ("#E30613", "#FFFFFF", "#FFFFFF"),
    "BHA": ("#0057B8", "#FFFFFF", "#FFFFFF"),
    "BUR": ("#6C1D45", "#99D6EA", "#FFFFFF"),
    "CHE": ("#034694", "#FFFFFF", "#FFFFFF"),
    "COV": ("#71C5E8", "#FFFFFF", "#172B4D"),
    "CRY": ("#1B458F", "#C4122E", "#FFFFFF"),
    "EVE": ("#003399", "#FFFFFF", "#FFFFFF"),
    "FUL": ("#FFFFFF", "#111111", "#111111"),
    "HUL": ("#F5A623", "#111111", "#111111"),
    "IPS": ("#0057B8", "#FFFFFF", "#FFFFFF"),
    "LEE": ("#FFFFFF", "#FFCD00", "#172B4D"),
    "LEI": ("#003090", "#FDBE11", "#FFFFFF"),
    "LIV": ("#C8102E", "#00B2A9", "#FFFFFF"),
    "MCI": ("#6CABDD", "#FFFFFF", "#172B4D"),
    "MUN": ("#DA291C", "#FBE122", "#FFFFFF"),
    "NEW": ("#111111", "#FFFFFF", "#FFFFFF"),
    "NFO": ("#DD0000", "#FFFFFF", "#FFFFFF"),
    "SOU": ("#D71920", "#FFFFFF", "#FFFFFF"),
    "SUN": ("#EB172B", "#FFFFFF", "#FFFFFF"),
    "TOT": ("#FFFFFF", "#132257", "#132257"),
    "WHU": ("#7A263A", "#1BB1E7", "#FFFFFF"),
    "WOL": ("#FDB913", "#231F20", "#231F20"),
}
DIFFICULTY_BADGE_COLORS = {1: "green", 2: "green", 3: "gray", 4: "orange", 5: "red"}
DIFFICULTY_CELL_COLORS = {1: "#1f7a4d", 2: "#9fd8b8", 3: "#e7e3ea", 4: "#f2b880", 5: "#c94a57"}
DIFFICULTY_TEXT_COLORS = {1: "#ffffff", 2: "#10301f", 3: "#211a23", 4: "#3d2205", 5: "#ffffff"}
STATUS_BADGES = {
    "d": ("orange", ":material/medical_services:", "Doubtful"),
    "i": ("red", ":material/personal_injury:", "Injured"),
    "s": ("red", ":material/gavel:", "Suspended"),
    "u": ("gray", ":material/block:", "Unavailable"),
    "n": ("gray", ":material/block:", "Not eligible"),
}


def formation_label(squad: pd.DataFrame) -> str:
    starters = squad[squad["squad_pos"] <= 11]
    counts = starters["position"].value_counts()
    return f"{int(counts.get('DEF', 0))}-{int(counts.get('MID', 0))}-{int(counts.get('FWD', 0))}"


def _markdown_safe(text: str) -> str:
    return str(text).replace("[", "(").replace("]", ")")


def status_badge(player: Mapping) -> str:
    """Inline markdown badge: colour plus icon and words, never colour alone."""
    status = str(player.get("status") or "a")
    if status == "a":
        return ":green-badge[:material/check_circle: Available]"
    color, icon, label = STATUS_BADGES.get(status, ("gray", ":material/help:", status))
    chance = pd.to_numeric(player.get("chance_of_playing"), errors="coerce")
    if status == "d" and pd.notna(chance):
        label = f"{int(chance)}% chance"
    return f":{color}-badge[{icon} {label}]"


def fixture_badges(fixtures: pd.DataFrame, gameweeks: Sequence[int]) -> str:
    """One badge per fixture with opponent, venue and the 1-5 difficulty number."""
    badges = []
    for gameweek in gameweeks:
        rows = fixtures[fixtures["gw"] == gameweek]
        if rows.empty:
            badges.append(f":gray-badge[GW{gameweek} blank]")
            continue
        for row in rows.itertuples():
            badges.append(f":{DIFFICULTY_BADGE_COLORS[int(row.difficulty)]}-badge[{_markdown_safe(row.label)} · {int(row.difficulty)}]")
    return " ".join(badges)


def fixture_run_text(fixtures: pd.DataFrame, gameweeks: Sequence[int]) -> str:
    labels = []
    for gameweek in gameweeks:
        rows = fixtures[fixtures["gw"] == gameweek]
        labels.append(" + ".join(rows["label"]) if not rows.empty else "Blank")
    return ", ".join(labels)


def heat_style(value: float, vmax: float) -> str:
    """Green intensity for a number; capped so dark text keeps at least 4.5:1 contrast."""
    if pd.isna(value) or vmax <= 0:
        return ""
    alpha = 0.55 * max(0.0, min(1.0, float(value) / vmax))
    return f"background-color: rgba(0, 138, 85, {alpha:.2f}); color: #211a23"


def difficulty_style(difficulty: float) -> str:
    if pd.isna(difficulty):
        return "background-color: #f4f2f5; color: #475467"
    level = int(difficulty)
    return f"background-color: {DIFFICULTY_CELL_COLORS[level]}; color: {DIFFICULTY_TEXT_COLORS[level]}"


def average_difficulty(fixtures: pd.DataFrame) -> float:
    return float(fixtures["difficulty"].mean()) if not fixtures.empty else 3.0


def move_reasons(outgoing: pd.DataFrame, incoming: pd.DataFrame, team_fixtures: pd.DataFrame, horizon: int) -> list[str]:
    """Plain-language reasons behind a recommended move, derived from the model inputs."""
    reasons = []
    out_names = " and ".join(f"**{name}**" for name in outgoing["web_name"])
    in_names = " and ".join(f"**{name}**" for name in incoming["web_name"])
    reasons.append(
        f"{in_names} {'project' if len(incoming) > 1 else 'projects'} **{incoming['xp_window'].sum():.1f}** points over the next "
        f"{horizon} gameweek{'s' if horizon != 1 else ''}, against **{outgoing['xp_window'].sum():.1f}** for {out_names}."
    )
    for player in outgoing.to_dict("records"):
        if player.get("status") != "a":
            note = player.get("availability_note") or "flagged by FPL"
            reasons.append(f"**{player['web_name']}** is flagged: {_markdown_safe(note)}.")
        elif player.get("xmins_next", 90) < 55:
            reasons.append(f"**{player['web_name']}** is a rotation risk: about {player['xmins_next']:.0f} expected minutes next gameweek.")
    for player in incoming.to_dict("records"):
        if player.get("xmins_next", 0) >= 75:
            reasons.append(f"**{player['web_name']}** is a nailed starter: about {player['xmins_next']:.0f} expected minutes next gameweek.")
    out_runs = team_fixtures[team_fixtures["team_id"].isin(outgoing["team_id"])]
    in_runs = team_fixtures[team_fixtures["team_id"].isin(incoming["team_id"])]
    out_difficulty, in_difficulty = average_difficulty(out_runs), average_difficulty(in_runs)
    if in_difficulty <= out_difficulty - 0.4:
        reasons.append(f"Easier fixtures: average difficulty **{in_difficulty:.1f}** for the new {'players' if len(incoming) > 1 else 'player'} vs **{out_difficulty:.1f}** (1 easy, 5 hard).")
    elif in_difficulty >= out_difficulty + 0.4:
        reasons.append(f"Despite tougher fixtures (average difficulty **{in_difficulty:.1f}** vs **{out_difficulty:.1f}**), the projected output is higher.")
    in_form, out_form = incoming["xgi90_recent"].mean(), outgoing["xgi90_recent"].mean()
    if in_form >= out_form + 0.15 and (incoming["position"] != "GKP").all():
        reasons.append(f"Stronger recent form: **{in_form:.2f}** expected goal involvements per 90 over the last 4 gameweeks vs **{out_form:.2f}**.")
    return reasons


def player_card(player: Mapping, gameweek: int, bench: bool = False, mode: str = "points") -> str:
    team = escape(str(player.get("team_short", "")))
    name = escape(str(player.get("web_name", "Unknown")))
    primary, secondary, kit_text = TEAM_COLORS.get(team, ("#5B247A", "#00FF87", "#FFFFFF"))
    captain = "C" if bool(player.get("is_captain", False)) else "V" if bool(player.get("is_vice_captain", False)) else ""
    captain_badge = f'<span class="captain-badge" aria-hidden="true">{captain}</span>' if captain else ""
    status = str(player.get("status", "a"))
    chance = pd.to_numeric(player.get("chance_of_playing"), errors="coerce")
    flag_text = f"{int(chance)}%" if status == "d" and pd.notna(chance) else {"d": "?", "i": "OUT", "s": "BAN", "u": "OUT", "n": "OUT"}.get(status, "")
    status_flag = f'<span class="status-flag status-{escape(status)}" aria-hidden="true">{escape(flag_text)}</span>' if status != "a" else ""
    selling_price = int(player.get("selling_price", player.get("now_cost", 0)) or 0) / 10
    if mode == "projection":
        fixture = escape(str(player.get("next_fixture") or "Blank"))
        detail = f"{fixture} · {float(player.get('xp_next', 0) or 0):.1f} xP"
        spoken = f"{fixture}, {float(player.get('xp_next', 0) or 0):.1f} projected points"
    else:
        points = int(player.get("event_points", 0) or 0)
        detail = f"£{selling_price:.1f}m" if bench else f"{points} pts · £{selling_price:.1f}m"
        spoken = f"{points} points, sale price {selling_price:.1f} million"
    role = {"C": ", captain", "V": ", vice-captain"}.get(captain, "")
    availability = f", {escape(str(player.get('status_label') or flag_text))}" if status != "a" else ""
    label = f"{name}, {team}{role}{availability}, {spoken}"
    card_class = "player-card bench-player" if bench else "player-card"
    return f"""
<div class="{card_class}" role="listitem" aria-label="{label}">
  <div class="kit-wrap" aria-hidden="true">
    {captain_badge}{status_flag}
    <div class="kit" style="--kit-primary:{primary};--kit-secondary:{secondary};--kit-text:{kit_text}"><span>{team}</span></div>
  </div>
  <div class="nameplate" aria-hidden="true"><strong>{name}</strong><span>{detail}</span></div>
</div>
"""


def render_pitch(squad: pd.DataFrame, gameweek: int, mode: str = "points") -> str:
    starters = squad[squad["squad_pos"] <= 11].sort_values("squad_pos")
    bench = squad[squad["squad_pos"] > 11].sort_values("squad_pos")
    rows = []
    for position in ["GKP", "DEF", "MID", "FWD"]:
        players = starters[starters["position"] == position]
        cards = "".join(player_card(player, gameweek, mode=mode) for _, player in players.iterrows())
        rows.append(f'<div class="pitch-row" role="list" data-position="{position}">{cards}</div>')
    bench_cards = "".join(player_card(player, gameweek, bench=True, mode=mode) for _, player in bench.iterrows())
    formation = formation_label(squad)
    toolbar = f"GW{int(gameweek)} projection" if mode == "projection" else f"Starting XI · GW{int(gameweek)} points"
    return f"""
<style>
.squad-shell {{ border:1px solid #d9d5dd; border-radius:14px; overflow:hidden; background:#fff; box-shadow:0 8px 28px rgba(55,0,60,.08); }}
.squad-toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:13px 18px; color:#fff; background:#37003c; font-size:13px; font-weight:650; letter-spacing:.01em; }}
.squad-toolbar .formation {{ color:#00ff87; }}
.fpl-pitch {{ position:relative; min-height:650px; padding:34px 18px 28px; overflow:hidden; background:repeating-linear-gradient(90deg,#167443 0,#167443 12.5%,#13703f 12.5%,#13703f 25%); }}
.fpl-pitch::before {{ content:""; position:absolute; inset:18px; border:2px solid rgba(255,255,255,.42); pointer-events:none; }}
.fpl-pitch::after {{ content:""; position:absolute; left:50%; top:50%; width:108px; height:108px; border:2px solid rgba(255,255,255,.42); border-radius:50%; transform:translate(-50%,-50%); pointer-events:none; }}
.halfway-line {{ position:absolute; z-index:0; top:50%; left:18px; right:18px; height:2px; background:rgba(255,255,255,.42); }}
.pitch-content {{ position:relative; z-index:1; min-height:588px; display:flex; flex-direction:column; justify-content:space-between; }}
.pitch-row {{ display:flex; justify-content:space-evenly; align-items:flex-start; gap:8px; min-height:126px; }}
.player-card {{ position:relative; width:min(116px,18%); min-width:72px; text-align:center; filter:drop-shadow(0 5px 5px rgba(0,0,0,.17)); }}
.kit-wrap {{ position:relative; display:flex; justify-content:center; min-height:68px; }}
.kit {{ position:relative; width:52px; height:49px; margin-top:7px; border:3px solid var(--kit-secondary); border-radius:12px 12px 5px 5px; display:grid; place-items:center; background:var(--kit-primary); color:var(--kit-text); font-size:10px; font-weight:800; letter-spacing:.05em; box-sizing:border-box; }}
.kit::before,.kit::after {{ content:""; position:absolute; top:3px; width:19px; height:28px; background:var(--kit-primary); border:3px solid var(--kit-secondary); z-index:-1; }}
.kit::before {{ left:-15px; transform:skewY(-25deg); border-radius:7px 2px 4px 7px; }}
.kit::after {{ right:-15px; transform:skewY(25deg); border-radius:2px 7px 7px 4px; }}
.nameplate {{ overflow:hidden; border-radius:5px; background:#37003c; color:#fff; }}
.nameplate strong,.nameplate span {{ display:block; overflow:hidden; padding:4px 6px; text-overflow:ellipsis; white-space:nowrap; }}
.nameplate strong {{ font-size:12px; line-height:1.15; }}
.nameplate span {{ padding-top:3px; border-top:1px solid rgba(255,255,255,.13); color:#efe6ef; font-size:11px; line-height:1.15; font-weight:500; }}
.captain-badge {{ position:absolute; z-index:3; top:0; left:50%; width:22px; height:22px; margin-left:-36px; border-radius:50%; display:grid; place-items:center; background:#fff; color:#37003c; font-size:11px; font-weight:800; box-shadow:0 2px 4px rgba(0,0,0,.25); }}
.status-flag {{ position:absolute; z-index:3; top:0; left:calc(50% + 16px); min-width:22px; padding:2px 5px; border:2px solid #fff; border-radius:10px; font-size:10px; font-weight:800; line-height:14px; color:#fff; background:#b42318; box-shadow:0 2px 4px rgba(0,0,0,.25); }}
.status-flag.status-d {{ background:#b54708; }}
.status-flag.status-u,.status-flag.status-n {{ background:#475467; }}
.bench-panel {{ padding:14px 16px 17px; background:#f5f3f6; }}
.bench-label {{ margin:0 0 11px; color:#5c5260; font-size:12px; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }}
.bench-row {{ display:flex; justify-content:space-evenly; gap:10px; }}
.bench-player {{ width:22%; max-width:125px; filter:none; }}
.bench-player .kit {{ width:42px; height:40px; border-width:2px; }}
.bench-player .kit::before,.bench-player .kit::after {{ width:16px; height:23px; border-width:2px; }}
.bench-player .kit::before {{ left:-12px; }}
.bench-player .kit::after {{ right:-12px; }}
@media (max-width:640px) {{
  .squad-shell {{ border-radius:10px; }}
  .squad-toolbar {{ padding:11px 12px; }}
  .fpl-pitch {{ min-height:560px; padding:24px 6px 20px; }}
  .fpl-pitch::before {{ inset:10px 6px; }}
  .halfway-line {{ left:6px; right:6px; }}
  .pitch-content {{ min-height:516px; }}
  .pitch-row {{ gap:3px; min-height:110px; }}
  .player-card {{ width:19%; min-width:58px; }}
  .kit-wrap {{ min-height:58px; }}
  .kit {{ width:40px; height:39px; border-width:2px; font-size:8px; }}
  .kit::before,.kit::after {{ width:14px; height:22px; border-width:2px; }}
  .kit::before {{ left:-11px; }}
  .kit::after {{ right:-11px; }}
  .nameplate strong {{ padding:4px 3px; font-size:10px; }}
  .nameplate span {{ padding:3px 2px; font-size:9px; }}
  .captain-badge {{ width:19px; height:19px; margin-left:-29px; font-size:9px; }}
  .status-flag {{ left:calc(50% + 10px); font-size:9px; }}
  .bench-panel {{ padding:12px 6px 14px; }}
  .bench-row {{ gap:4px; }}
  .bench-player {{ width:24%; min-width:0; }}
}}
</style>
<div class="squad-shell" role="region" aria-label="FPL squad, formation {formation}">
  <div class="squad-toolbar"><span>{toolbar}</span><span class="formation">Formation {formation}</span></div>
  <div class="fpl-pitch"><div class="halfway-line"></div><div class="pitch-content">{''.join(rows)}</div></div>
  <div class="bench-panel"><p class="bench-label">Bench · substitution order</p><div class="bench-row" role="list">{bench_cards}</div></div>
</div>
"""
