"""Phase 1b: raw lake -> clean staging tables (dedupe, range checks, gap filling, AQI)."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config as C
from .aqi import compute_aqi

log = logging.getLogger("aqip.clean")

# Physical plausibility bounds; values outside become NaN rather than silently kept.
BOUNDS = {
    "pm2_5": (0, 1500), "pm10": (0, 2500), "no2": (0, 1000), "so2": (0, 2000),
    "o3": (0, 1000), "co": (0, 50000),
    "temperature_2m": (-10, 55), "relative_humidity_2m": (0, 100),
    "wind_speed_10m": (0, 150), "wind_direction_10m": (0, 360),
    "surface_pressure": (850, 1100), "precipitation": (0, 300),
}
MAX_GAP_HOURS = 6  # interpolate only short station outages; longer gaps stay NaN


def read_raw(source: str) -> pd.DataFrame:
    files = list((C.RAW / source).rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no raw data for {source}; run ingestion first")
    return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the most recently ingested record per (station, hour)."""
    df = df.sort_values(["station_id", "ts", "_ingested_at"])
    return df.drop_duplicates(["station_id", "ts"], keep="last").drop(columns="_ingested_at")


def _clean_station(g: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    g = g.set_index("ts").sort_index()
    full = pd.date_range(g.index.min(), g.index.max(), freq="h")
    g = g.reindex(full)
    g.index.name = "ts"
    g["station_id"] = g["station_id"].ffill().bfill()
    for c in cols:
        lo, hi = BOUNDS[c]
        g.loc[(g[c] < lo) | (g[c] > hi), c] = np.nan
        g[f"{c}_imputed"] = g[c].isna()
        g[c] = g[c].interpolate(limit=MAX_GAP_HOURS, limit_area="inside")
        g[f"{c}_imputed"] &= g[c].notna()
    return g.reset_index()


def run() -> dict:
    stats = {}
    C.STAGING.mkdir(parents=True, exist_ok=True)
    for source, cols in (("air_quality", C.POLLUTANTS), ("weather", C.WEATHER_VARS)):
        raw = read_raw(source)
        n_raw = len(raw)
        raw["ts"] = pd.to_datetime(raw["ts"])
        raw = _dedupe(raw)
        cleaned = pd.concat(
            (_clean_station(g, cols) for _, g in raw.groupby("station_id")), ignore_index=True
        )
        if source == "air_quality":
            # CPCB AQI uses 24h-average concentrations for the particulates.
            cleaned = cleaned.sort_values(["station_id", "ts"]).reset_index(drop=True)
            avg = cleaned.copy()
            for p in C.POLLUTANTS:
                avg[p] = avg.groupby("station_id")[p].transform(
                    lambda s: s.rolling(24 if p != "o3" and p != "co" else 8, min_periods=6).mean()
                )
            cleaned["aqi"] = compute_aqi(avg)  # same index: avg is a sorted copy of cleaned
        out = C.STAGING / f"{source}.parquet"
        cleaned.to_parquet(out, index=False)
        stats[source] = {
            "raw_rows": n_raw, "clean_rows": len(cleaned),
            "duplicates_removed": n_raw - len(raw),
            "null_rate": float(cleaned[cols].isna().mean().mean()),
        }
        log.info("%s: %s", source, stats[source])
    return stats
