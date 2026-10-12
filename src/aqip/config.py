"""Central configuration: cities, paths, festival calendar, AQI breakpoints."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql"
# AQIP_HOME re-roots all generated artefacts (data, models, reports), e.g. on Windows
# when the checkout path is too long for Parquet partition directories.
HOME = Path(os.environ.get("AQIP_HOME", ROOT))
DATA = HOME / "data"
LAKE = DATA / "lake"
RAW = LAKE / "raw"
STAGING = LAKE / "staging"
WAREHOUSE = DATA / "warehouse.duckdb"
MODELS = HOME / "models"
REPORTS = HOME / "reports"

# station_id, city, state, lat, lon
CITIES = [
    ("DEL", "Delhi", "Delhi", 28.6139, 77.2090),
    ("LKO", "Lucknow", "Uttar Pradesh", 26.8467, 80.9462),
    ("PAT", "Patna", "Bihar", 25.5941, 85.1376),
    ("KOL", "Kolkata", "West Bengal", 22.5726, 88.3639),
    ("AMD", "Ahmedabad", "Gujarat", 23.0225, 72.5714),
    ("MUM", "Mumbai", "Maharashtra", 19.0760, 72.8777),
    ("PUN", "Pune", "Maharashtra", 18.5204, 73.8567),
    ("HYD", "Hyderabad", "Telangana", 17.3850, 78.4867),
    ("BLR", "Bengaluru", "Karnataka", 12.9716, 77.5946),
    ("CHE", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
]

POLLUTANTS = ["pm2_5", "pm10", "no2", "so2", "o3", "co"]
# Open-Meteo variable names -> our short names
API_POLLUTANTS = {
    "pm2_5": "pm2_5", "pm10": "pm10", "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2", "ozone": "o3", "carbon_monoxide": "co",
}
WEATHER_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "surface_pressure",
    "precipitation",
]

HISTORY_DAYS = 730  # ~2 years: covers two Diwali seasons
HORIZONS = (24, 48, 72)

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_HIST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
WX_FCST_URL = "https://api.open-meteo.com/v1/forecast"

# Pollution-relevant festivals (date of main day). Flag window is +-1 day.
FESTIVALS = {
    "diwali": [date(2024, 11, 1), date(2025, 10, 20), date(2026, 11, 8)],
    "holi": [date(2025, 3, 14), date(2026, 3, 4)],
    "dussehra": [date(2024, 10, 12), date(2025, 10, 2), date(2026, 10, 20)],
}

# CPCB National AQI breakpoints: concentration (ug/m3, CO in mg/m3) -> sub-index.
# Index anchors shared by all pollutants.
AQI_ANCHORS = [0, 50, 100, 200, 300, 400, 500]
AQI_BREAKS = {
    "pm2_5": [0, 30, 60, 90, 120, 250, 380],
    "pm10": [0, 50, 100, 250, 350, 430, 510],
    "no2": [0, 40, 80, 180, 280, 400, 520],
    "so2": [0, 40, 80, 380, 800, 1600, 2000],
    "o3": [0, 50, 100, 168, 208, 748, 1000],
    "co": [0, 1, 2, 10, 17, 34, 50],
}
AQI_CATEGORIES = [
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
]
WHO_PM25_24H = 15.0  # WHO 2021 24-hour guideline, ug/m3
