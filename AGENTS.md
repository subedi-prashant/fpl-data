# Agent notes for fpl-data

## Commands (Windows, run from `fpl-data/`)

- Tests: `.\.venv\Scripts\python.exe -m pytest -q`
- Dashboard: `.\.venv\Scripts\streamlit.exe run dashboard/app.py --server.port 8501`
- Model backtest: `.\.venv\Scripts\fpl-data.exe backtest --from-gw 4` (needs internet)
- Set `PYTHONIOENCODING=utf-8` when printing player names to the console; the default cp1252 codepage crashes on characters like `ć`.

## Layout

- `fpl_data/projections.py`: expected-points model. `fpl_data/recommendations.py`: transfer planner and FPL rules. Both are pure pandas/numpy and fully unit tested.
- `dashboard/app.py` is the Streamlit entrypoint (`st.navigation`); pages live in `dashboard/app_pages/` and their file names are their URL paths.
- `dashboard/components.py` holds pure HTML/markdown builders so they can be tested without Streamlit.
- The dashboard only uses the live public FPL API (cached 15 minutes); it does not read `data/fpl.db`.

## Gotchas

- Streamlit hot-reloads page scripts but not `dashboard/data.py`, `ui.py` or `components.py`; restart the server after editing them.
- Streamlit remembers the sidebar collapsed state in browser `localStorage`, so clear it when checking first-visit layouts.
- matplotlib is not installed, so don't use `Styler.background_gradient`; use `dashboard.components.heat_style` / `difficulty_style`.
- FPL money values are integers in tenths of £1m (`55` = £5.5m). Keep calculations in tenths.
- The FPL API currently returns `0` for `strength_attack_*`/`strength_defence_*`; the team model falls back to `strength_overall_*`.
