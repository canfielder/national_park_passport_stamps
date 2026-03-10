###############################################################################
# SETUP #

import altair as alt
import folium
import folium.plugins as plugins
import json
import os
import pandas as pd
import pathlib as pl
import streamlit as st
import streamlit_folium as stf

from src.paths import PROJECT_ROOT

st.set_page_config(
    page_title = "National Parks Passport Stamps",
    layout = "wide"
    )

###############################################################################
# LOAD #
# Load data
@st.cache_data
def load_data():
    # Stamp ---------------------------------------------------------
    table_path = pl.Path(
        PROJECT_ROOT,
        'data',
        'manual_tracking',
        'national_park_passport_stamp_series.csv'
    )
    df = pd.read_csv(table_path)

    return df

df = load_data()

# Load config for region colors
with open(os.path.join(PROJECT_ROOT, "config", "colors.json"), "r") as f:
    colors = json.load(f)
    region_colors = colors["region"]

###############################################################################
# APP #

# Sidebar filters
st.sidebar.header("Filter Stamps")
years = sorted(df["year"].dropna().unique())
regions = sorted(df["region"].dropna().unique())
visited_options = ["Yes", "No"]

visited_filter = st.sidebar.multiselect("Visited", visited_options, default=visited_options)
region_filter = st.sidebar.multiselect("Select Region", regions, default=regions)
year_filter = st.sidebar.multiselect("Select Year", years, default=years)

# Apply filters
df_filtered = df[
    (df["year"].isin(year_filter)) &
    (df["region"].isin(region_filter)) &
    (df["visited"].isin(visited_filter))
]

# Summary metrics (always based on full dataset)
total = len(df)
collected = (df["visited"] == "Yes").sum()
pct = f"{collected / total * 100:.1f}%"

col1, col2, col3 = st.columns(3)
col1.metric("Total Stamps in Series", total)
col2.metric("Collected", f"{collected} / {total}")
col3.metric("Progress", pct)

st.divider()

# Tabs
tab1, tab2, tab3 = st.tabs(["Map View", "Table View", "Region Progress"])

with tab1:
    st.header("National Park Passport Stamp Locations")

    # Fallback location (continental US center)
    default_location = [39.8283, -98.5795]

    if df_filtered.empty:
        st.info("No stamps match your current filters. Showing base map only.")
        map_center = default_location
    else:
        # Safe calculation of mean coordinates
        map_center = [
            df_filtered["latitude"].mean(),
            df_filtered["longitude"].mean()
        ]

    # Create map
    m = folium.Map(location=map_center, zoom_start=5)

    for _, row in df_filtered.iterrows():
        color = region_colors.get(row["region"], "blue")
        msg = f"{row['name']} ({row['year']})"

        # Assign Icon
        if row["visited"] == "Yes":
            icon = "check"
        else:
            icon = "close"

        folium.Marker(
            location = [row["latitude"], row["longitude"]],
            popup = msg,
            tooltip = msg,
            icon = plugins.BeautifyIcon(
                icon = icon,
                icon_shape = "marker",
                border_color = color,
                background_color = color
            )
        ).add_to(m)

    plugins.Fullscreen(position="topleft").add_to(m)
    stf.st_folium(
        m,
        height = 750,
        width = 1000,
        returned_objects = []
    )


with tab2:
    st.header("Stamp Details Table")
    # Sort Dataframe
    sorted_df = df_filtered.sort_values(by=["year", "name", "region"])

    # Style Year
    # Formatting
    styled_df = sorted_df.style.format({
            'year': lambda x: f"{x:.0f}"  # Remove commas from years (treated as float/int)
        })

    st.dataframe(styled_df, use_container_width=True)

with tab3:
    st.header("Progress by Region")

    region_stats = (
        df.groupby("region")
        .agg(
            total=("visited", "count"),
            collected=("visited", lambda x: (x == "Yes").sum())
        )
        .reset_index()
    )
    region_stats["pct"] = (region_stats["collected"] / region_stats["total"] * 100).round(1)
    region_stats["pct_label"] = region_stats["pct"].astype(str) + "%"
    region_stats["y_label"] = (
        region_stats["region"] + " ("
        + region_stats["collected"].astype(str) + "/"
        + region_stats["total"].astype(str) + ")"
    )

    bars = alt.Chart(region_stats).mark_bar().encode(
        x=alt.X("pct:Q", title="% Collected", scale=alt.Scale(domain=[0, 100])),
        y=alt.Y("y_label:N", sort="-x", title=None),
        tooltip=["region:N", "collected:Q", "total:Q", "pct:Q"]
    )

    text = alt.Chart(region_stats).mark_text(align="left", dx=5, color="gray").encode(
        x=alt.X("pct:Q"),
        y=alt.Y("y_label:N", sort="-x"),
        text="pct_label:N"
    )

    st.altair_chart((bars + text).properties(height=300), use_container_width=True)
