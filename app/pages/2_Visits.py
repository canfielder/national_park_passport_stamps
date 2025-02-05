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
    page_title = "National Park Visiting",
    layout = "wide"
    )

###############################################################################
# FUNCTIONS #
def park_status(row):
    '''
    Assign status of park.
    '''
    if row['Evan'] and row['Kelsey']:
        output = 'Evan And Kelsey'
    elif row['Evan'] and not row['Kelsey']:
        output = 'Evan'
    elif not row['Evan'] and row['Kelsey']:
        output = 'Kelsey'
    else:
        output = 'Not Visited'
    
    return output


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
        'national_park_visited_records.csv'
    )
    df = pd.read_csv(table_path)

    # Define status
    df['status'] = df.apply(park_status, axis=1)

    return df

df = load_data()

# Load config for region colors
with open(os.path.join(PROJECT_ROOT, "config", "visit_colors.json"), "r") as f:
    visit_colors = json.load(f)

###############################################################################
# APP #

# Sidebar filters
st.sidebar.header("Filter Visit")
status = sorted(df["status"].dropna().unique())

status_filter = st.sidebar.multiselect("Select Status", status, default=status)

# Apply filters
df_filtered = df[
    (df["status"].isin(status_filter))
]

st.header("National Park Visiting Records")

# Create map
m = folium.Map(
    location=[
        df_filtered["latitude"].mean(), 
        df_filtered["longitude"].mean()
        ], zoom_start=5
        )

for _, row in df_filtered.iterrows():
    color = visit_colors.get(row["status"], "blue")
    msg = f"{row['name']}"

    folium.Marker(
        location = [row["latitude"], row["longitude"]],
        popup = msg,
        tooltip = msg,
        icon = plugins.BeautifyIcon(
            icon = "star", 
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
