"""Live inference: fetch recent observations + weather forecast, predict AQI at +24/48/72h."""
from __future__ import annotations

from functools import lru_cache

import joblib
import numpy as np
import pandas as pd

from . import config as C
from .aqi import category
from .features import add_aqi, make_dataset
from .ingest import fetch_live


@lru_cache(maxsize=None)
def load_bundle(h: int) -> dict:
    return joblib.load(C.MODELS / f"forecast_{h}h.joblib")


def station_by_city(name: str):
    for s in C.CITIES:
        if s[1].lower() == name.lower() or s[0].lower() == name.lower():
            return s
    raise KeyError(name)


def forecast_city(name: str, live: pd.DataFrame | None = None) -> dict:
    st = station_by_city(name)
    live = fetch_live(st, past_days=14) if live is None else live
    frame = add_aqi(live)
    observed = frame.dropna(subset=["aqi"])
    t0 = observed["ts"].max()
    out = {"city": st[1], "issued_at": str(t0), "current_aqi": float(observed["aqi"].iloc[-1]),
           "current_category": category(observed["aqi"].iloc[-1]), "forecast": []}
    for h in C.HORIZONS:
        b = load_bundle(h)
        ds = make_dataset(frame, h)
        row = ds[ds["ts"] == t0][b["features"]]
        lo, mid, hi = (float(np.clip(b[q].predict(row)[0], 0, 500)) for q in ("q10", "q50", "q90"))
        lo, hi = min(lo, mid), max(hi, mid)  # quantile models can cross; keep the band valid
        out["forecast"].append({
            "horizon_h": h, "valid_at": str(t0 + pd.Timedelta(hours=h)),
            "aqi": round(mid), "aqi_low": round(lo), "aqi_high": round(hi), "category": category(mid)})
    out["history_24h"] = [
        {"ts": str(r.ts), "aqi": None if pd.isna(r.aqi) else round(float(r.aqi), 1)}
        for r in observed.tail(48).itertuples()]
    return out
