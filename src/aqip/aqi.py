"""CPCB National AQI computation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import AQI_ANCHORS, AQI_BREAKS, AQI_CATEGORIES


def sub_index(conc: pd.Series | np.ndarray, pollutant: str) -> np.ndarray:
    """Piecewise-linear sub-index for one pollutant (NaN-safe, capped at 500)."""
    x = np.asarray(conc, dtype=float)
    return np.interp(x, AQI_BREAKS[pollutant], AQI_ANCHORS, right=500.0)


def compute_aqi(df: pd.DataFrame) -> pd.Series:
    """AQI = max sub-index, requiring PM2.5 or PM10 (CPCB rule). CO expected in ug/m3."""
    cols = {}
    for p in AQI_BREAKS:
        if p not in df:
            continue
        v = df[p].to_numpy(dtype=float)
        if p == "co":
            v = v / 1000.0  # ug/m3 -> mg/m3
        si = sub_index(v, p)
        si[np.isnan(df[p].to_numpy(dtype=float))] = np.nan
        cols[p] = si
    si_df = pd.DataFrame(cols, index=df.index)
    aqi = si_df.max(axis=1, skipna=True)
    has_pm = si_df[["pm2_5", "pm10"]].notna().any(axis=1)
    return aqi.where(has_pm)


def category(aqi: float) -> str:
    if aqi is None or np.isnan(aqi):
        return "Unknown"
    for upper, name in AQI_CATEGORIES:
        if aqi <= upper:
            return name
    return "Severe"
