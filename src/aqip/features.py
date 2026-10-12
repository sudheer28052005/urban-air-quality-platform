"""Phase 3a: feature engineering shared by training and live inference.

For a forecast issued at hour t for horizon h, features are:
  * state at t       - pollutants, AQI, lags, rolling stats, current weather
  * future known     - weather at t+h (a forecast at inference time) and the
                       calendar of t+h (hour, weekday, season, festival flag)
No pollutant information after t is ever used. Weather at t+h is the historical
analysis in training and the NWP forecast at inference (a mild optimism, noted in README).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .aqi import compute_aqi

LAGS = (1, 3, 6, 12, 24, 48, 168)
FUTURE_WX = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precipitation", "surface_pressure"]


def add_aqi(df: pd.DataFrame) -> pd.DataFrame:
    """Hourly CPCB-style AQI from trailing 24h (8h for O3/CO) means, per station."""
    df = df.sort_values(["station_id", "ts"]).reset_index(drop=True)
    avg = df[["station_id", *C.POLLUTANTS]].copy()
    for p in C.POLLUTANTS:
        w = 8 if p in ("o3", "co") else 24
        avg[p] = df.groupby("station_id")[p].transform(lambda s, w=w: s.rolling(w, min_periods=6).mean())
    df["aqi"] = compute_aqi(avg)
    # A trailing mean keeps producing values after the last observation; AQI only exists
    # for hours where a particulate reading actually exists.
    df.loc[df[["pm2_5", "pm10"]].isna().all(axis=1), "aqi"] = np.nan
    return df


def festival_flag(ts: pd.Series) -> pd.Series:
    days = set()
    for dates in C.FESTIVALS.values():
        for d in dates:
            for off in (-1, 0, 1):
                days.add((pd.Timestamp(d) + pd.Timedelta(days=off)).normalize())
    return ts.dt.normalize().isin(days).astype(int)


def _city_features(g: pd.DataFrame, h: int) -> pd.DataFrame:
    g = g.sort_values("ts").reset_index(drop=True)
    out = pd.DataFrame({"station_id": g["station_id"], "ts": g["ts"]})
    for c in (*C.POLLUTANTS, "aqi"):
        out[c] = g[c]
    for k in LAGS:
        out[f"aqi_lag{k}"] = g["aqi"].shift(k)
    for w in (24, 72, 168):
        out[f"aqi_roll{w}"] = g["aqi"].rolling(w, min_periods=w // 2).mean()
    out["aqi_std24"] = g["aqi"].rolling(24, min_periods=12).std()
    out["aqi_diff24"] = g["aqi"] - g["aqi"].shift(24)
    out["pm_ratio"] = g["pm2_5"] / g["pm10"].replace(0, np.nan)
    for c in FUTURE_WX:
        out[f"{c}_now"] = g[c]
    out["wind_roll24"] = g["wind_speed_10m"].rolling(24, min_periods=12).mean()
    out["rain_72h"] = g["precipitation"].rolling(72, min_periods=24).sum()
    # target-time covariates (weather known/forecast at t+h)
    for c in FUTURE_WX:
        out[f"{c}_fut"] = g[c].shift(-h)
    out["wind_fut_roll24"] = g["wind_speed_10m"].rolling(24, min_periods=12).mean().shift(-h)
    out["rain_fut_24h"] = g["precipitation"].rolling(24, min_periods=12).sum().shift(-h)
    tt = g["ts"] + pd.Timedelta(hours=h)
    out["tgt_hour"] = tt.dt.hour
    out["tgt_dow"] = tt.dt.dayofweek
    out["tgt_month"] = tt.dt.month
    out["tgt_doy_sin"] = np.sin(2 * np.pi * tt.dt.dayofyear / 366)
    out["tgt_doy_cos"] = np.cos(2 * np.pi * tt.dt.dayofyear / 366)
    out["tgt_festival"] = festival_flag(tt).to_numpy()
    out["target"] = g["aqi"].shift(-h)
    return out


def make_dataset(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """Rows for every (station, t). `target` is NaN where t+h is unobserved."""
    df = df.merge(
        pd.DataFrame(C.CITIES, columns=["station_id", "city", "state", "lat", "lon"]),
        on="station_id", how="left")
    parts = [_city_features(g, h).assign(lat=g["lat"].iloc[0], lon=g["lon"].iloc[0])
             for _, g in df.groupby("station_id")]
    ds = pd.concat(parts, ignore_index=True)
    ids = {s[0]: i for i, s in enumerate(C.CITIES)}
    ds["city_id"] = ds["station_id"].map(ids)
    return ds.sort_values(["ts", "station_id"]).reset_index(drop=True)


NON_FEATURES = {"station_id", "ts", "target"}


def feature_columns(ds: pd.DataFrame) -> list[str]:
    return [c for c in ds.columns if c not in NON_FEATURES]
