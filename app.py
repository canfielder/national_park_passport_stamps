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
from src.paths import PROJECT_ROOT

st.set_page_config(
    page_title = "National Parks",
    layout = "wide"
    )

st.markdown(
    """
    # National Park Tracking
    """
)
