###############################################################################
# SETUP #

import folium
import folium.plugins as plugins
import json
import os
import pandas as pd
import pathlib as pl
import streamlit as st

from streamlit_folium import st_folium

# PROJECT_ROOT = find_project_root()
PROJECT_ROOT = "/Users/evancanfield/Documents/Projects/national_park_passport_stamps"

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
with open(os.path.join(PROJECT_ROOT, "config", "region_colors.json"), "r") as f:
    region_colors = json.load(f)

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

# Tabs
tab1, tab2 = st.tabs(["Map View", "Table View"])

with tab1:
    st.header("National Park Passport Stamp Locations")
    
    # Create map
    m = folium.Map(
        location=[
            df_filtered["latitude"].mean(), 
            df_filtered["longitude"].mean()
            ], zoom_start=5
            )
    
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
    st_folium(
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
    
    st.dataframe(styled_df, use_container_width=True, )
    
    # Allow sorting and filtering
    # edited_df = st.data_editor(sorted_df, num_rows="dynamic")
