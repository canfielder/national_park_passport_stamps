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
scripts/
  generate_itinerary.py   # Trip itinerary generator (see below)
data/
  trips/                  # One subfolder per trip, each containing parkstamps.org HTML files
```

### Data Pipeline

Raw data originates as **KML/KMZ exports from Google Maps**. The Jupyter notebooks in `notebooks/` document the one-time transformation into the manual tracking CSVs. The Streamlit app reads only from `data/manual_tracking/`.

**Stamps CSV** (`national_park_passport_stamp_series.csv`): `name`, `year`, `latitude`, `longitude`, `region`, `visited` (Yes/No), `date_visited` (ISO `YYYY-MM-DD`, blank when unknown — most pre-existing visits have no recorded date).

**Visits CSV** (`national_park_visited_records.csv`): `name`, `latitude`, `longitude`, `split`, `Kelsey` (bool), `Evan` (bool). The app derives a display status — "Evan", "Kelsey", "Evan And Kelsey", or "Not Visited" — at load time.

### Key Patterns

- **Path resolution:** Always use `PROJECT_ROOT` from `src.paths` rather than relative strings.
- **Data caching:** Load functions are decorated with `@st.cache_data`.
- **Colors:** All region and visitor color mappings live in `config/colors.json`. Read it once at load time rather than hardcoding hex values inline.
- **Maps:** Folium + streamlit-folium. Markers use icon classes (`fa-check`, `fa-close`, `fa-star`) colored by region/visitor status from the color config.
- **Charts:** Altair (not plotnine) is used here — this project predates the global plotnine preference. Keep charts in Altair unless doing a full rewrite.

### Itinerary Generator

`scripts/generate_itinerary.py` is a standalone CLI tool for trip planning around NPS cancellation stamps (distinct from the passport stamp series). The user saves printer-friendly pages from [parkstamps.org](https://www.parkstamps.org) (`searchPrint.php?locationId=XXXX`) as HTML files using SingleFile or "Save Page As", places them in a trip subfolder under `data/trips/`, and runs:

```bash
uv run python -m scripts.generate_itinerary data/trips/<trip-folder>
```

Output is `data/trips/<trip-folder>/itinerary.html` — a mobile-friendly single-page HTML file. It cross-references the passport series CSV to flag uncollected series stamps within 25 km of each cancellation location. Collection status is detected by looking for the username `CanfieldER` in the HTML.

### NPTC Master Map & Stamp Photo Log

`src/nptc_map.py` parses the NPTC master map KML export (`NPTCMasterMap_MM-DD-YYYY.kml`, ~20 MB, gitignored under `data/raw/nptc/`). It is the preferred source for collected status: each stamp carries a collected checkmark, but there are no collection dates.

`scripts/log_stamp_photos.py` logs photos in `data/stamp_photos/` (images gitignored; EXIF holds GPS) to `data/manual_tracking/cancellation_stamp_log.csv`, one row per stamp. Dates come from the file name, then from EXIF only if it falls within the trip folder's date range, then from the trip start. Photo GPS is ignored on purpose, because stamps are photographed at the hotel or at home. `scripts/sync_photo_names.py` renames photos to the naming convention (`YYYYMMDD__<location_id>__<stamp_id>` in `YYYYMMDD[-YYYYMMDD]_trip-name/` folders) from the log, which is the source of truth. `data/stamp_photos/` is the folder of record. See `data/stamp_photos/README.md`.

### Deployment

Deployed on **Streamlit Cloud**. `runtime.txt` pins the Python version; `requirements.txt` is exported from `pyproject.toml` via `make requirements` and committed for the cloud runner.
