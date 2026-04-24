# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make launch       # uv run streamlit run app.py
make lint         # ruff check on app.py, pages/, src/
make format       # black format on app.py, pages/, src/
make sync         # uv sync --all-extras (install/update dependencies)
make requirements # export requirements.txt from pyproject.toml (Streamlit Cloud)
make clean        # remove __pycache__, .ruff_cache, build artifacts
```

No test suite is configured.

## Architecture

This is a **Streamlit multi-page app** for tracking National Park visits and passport stamp collection. It is a personal project for two users (Evan and Kelsey).

```
app.py                     # Home page (minimal — title/setup only)
pages/
  1_Stamps.py              # Passport stamp tracking page
  2_Visits.py              # Park visit tracking page
src/
  paths.py                 # PROJECT_ROOT constant (pathlib.Path)
config/
  colors.json              # Color palettes keyed by region and visitor status
data/
  manual_tracking/         # Primary data source — hand-maintained CSVs
  raw/                     # KML/KMZ exports from Google Maps
  processed/               # Archived processed data
notebooks/                 # One-time data pipeline notebooks (KML → CSV)
```

### Data Pipeline

Raw data originates as **KML/KMZ exports from Google Maps**. The Jupyter notebooks in `notebooks/` document the one-time transformation into the manual tracking CSVs. The Streamlit app reads only from `data/manual_tracking/`.

**Stamps CSV** (`national_park_passport_stamp_series.csv`): `name`, `year`, `latitude`, `longitude`, `region`, `visited` (Yes/No).

**Visits CSV** (`national_park_visited_records.csv`): `name`, `latitude`, `longitude`, `split`, `Kelsey` (bool), `Evan` (bool). The app derives a display status — "Evan", "Kelsey", "Evan And Kelsey", or "Not Visited" — at load time.

### Key Patterns

- **Path resolution:** Always use `PROJECT_ROOT` from `src.paths` rather than relative strings.
- **Data caching:** Load functions are decorated with `@st.cache_data`.
- **Colors:** All region and visitor color mappings live in `config/colors.json`. Read it once at load time rather than hardcoding hex values inline.
- **Maps:** Folium + streamlit-folium. Markers use icon classes (`fa-check`, `fa-close`, `fa-star`) colored by region/visitor status from the color config.
- **Charts:** Altair (not plotnine) is used here — this project predates the global plotnine preference. Keep charts in Altair unless doing a full rewrite.

### Deployment

Deployed on **Streamlit Cloud**. `runtime.txt` pins the Python version; `requirements.txt` is exported from `pyproject.toml` via `make requirements` and committed for the cloud runner.
