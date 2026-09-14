from __future__ import annotations

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


def formation_label(squad: pd.DataFrame) -> str:
    starters = squad[squad["squad_pos"] <= 11]
    counts = starters["position"].value_counts()
    return f"{int(counts.get('DEF', 0))}-{int(counts.get('MID', 0))}-{int(counts.get('FWD', 0))}"


def player_card(player: pd.Series, gameweek: int, bench: bool = False) -> str:
    team = escape(str(player.get("team_short", "")))
    name = escape(str(player.get("web_name", "Unknown")))
    primary, secondary, kit_text = TEAM_COLORS.get(team, ("#5B247A", "#00FF87", "#FFFFFF"))
    captain = "C" if bool(player.get("is_captain", False)) else "V" if bool(player.get("is_vice_captain", False)) else ""
    captain_badge = f'<span class="captain-badge">{captain}</span>' if captain else ""
    status = str(player.get("status", "a"))
    status_badge = '<span class="status-dot" title="Flagged"></span>' if status != "a" else ""
    points = int(player.get("event_points", 0) or 0)
    selling_price = int(player.get("selling_price", player.get("now_cost", 0)) or 0) / 10
    detail = f"£{selling_price:.1f}m" if bench else f"{points} pts · £{selling_price:.1f}m"
    card_class = "player-card bench-player" if bench else "player-card"
    return f"""
<div class="{card_class}">
  <div class="kit-wrap">
    {captain_badge}{status_badge}
    <div class="kit" style="--kit-primary:{primary};--kit-secondary:{secondary};--kit-text:{kit_text}"><span>{team}</span></div>
  </div>
  <div class="nameplate"><strong>{name}</strong><span>{detail}</span></div>
</div>
"""


def render_pitch(squad: pd.DataFrame, gameweek: int) -> str:
    starters = squad[squad["squad_pos"] <= 11].sort_values("squad_pos")
    bench = squad[squad["squad_pos"] > 11].sort_values("squad_pos")
    rows = []
    for position in ["GKP", "DEF", "MID", "FWD"]:
        players = starters[starters["position"] == position]
        cards = "".join(player_card(player, gameweek) for _, player in players.iterrows())
        rows.append(f'<div class="pitch-row" data-position="{position}">{cards}</div>')
    bench_cards = "".join(player_card(player, gameweek, bench=True) for _, player in bench.iterrows())
    formation = formation_label(squad)
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
.nameplate strong {{ font-size:12px; line-height:1.1; }}
.nameplate span {{ padding-top:3px; border-top:1px solid rgba(255,255,255,.13); color:#d9ccd9; font-size:10px; line-height:1.1; font-weight:500; }}
.captain-badge {{ position:absolute; z-index:3; top:0; left:50%; width:22px; height:22px; margin-left:-36px; border-radius:50%; display:grid; place-items:center; background:#fff; color:#37003c; font-size:11px; font-weight:800; box-shadow:0 2px 4px rgba(0,0,0,.25); }}
.status-dot {{ position:absolute; z-index:3; top:4px; left:calc(50% + 25px); width:10px; height:10px; border:2px solid #fff; border-radius:50%; background:#dc2626; }}
.bench-panel {{ padding:14px 16px 17px; background:#f5f3f6; }}
.bench-label {{ margin:0 0 11px; color:#5c5260; font-size:11px; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }}
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
  .nameplate strong {{ padding:4px 3px; font-size:9px; }}
  .nameplate span {{ padding:3px 2px; font-size:8px; }}
  .captain-badge {{ width:19px; height:19px; margin-left:-29px; font-size:9px; }}
  .status-dot {{ left:calc(50% + 18px); }}
  .bench-panel {{ padding:12px 6px 14px; }}
  .bench-row {{ gap:4px; }}
  .bench-player {{ width:24%; min-width:0; }}
}}
</style>
<div class="squad-shell" role="region" aria-label="Current FPL squad, formation {formation}">
  <div class="squad-toolbar"><span>Starting XI · GW{int(gameweek)} points</span><span class="formation">Formation {formation}</span></div>
  <div class="fpl-pitch"><div class="halfway-line"></div><div class="pitch-content">{''.join(rows)}</div></div>
  <div class="bench-panel"><p class="bench-label">Bench · substitution order</p><div class="bench-row">{bench_cards}</div></div>
</div>
"""
