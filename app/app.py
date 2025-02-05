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
    page_title = "National Parks",
    layout = "wide"
    )

st.markdown(
    """
    # National Park Tracking
    """
)
