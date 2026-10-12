"""FastAPI service: GET /forecast/{city}. Run: uvicorn aqip.api:app --reload"""
from __future__ import annotations

import json
import time

from fastapi import FastAPI, HTTPException

from . import config as C
from .forecast import forecast_city

app = FastAPI(title="Urban Air Quality Intelligence API", version="1.0")
_cache: dict[str, tuple[float, dict]] = {}
TTL = 900  # upstream data is hourly; 15 min cache keeps us polite to Open-Meteo


@app.get("/health")
def health():
    return {"status": "ok", "models": sorted(p.name for p in C.MODELS.glob("forecast_*h.joblib"))}


@app.get("/cities")
def cities():
    return [{"station_id": s[0], "city": s[1], "state": s[2], "lat": s[3], "lon": s[4]} for s in C.CITIES]


@app.get("/forecast/{city}")
def forecast(city: str):
    key = city.lower()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        res = forecast_city(city)
    except KeyError:
        raise HTTPException(404, f"unknown city '{city}'")
    except FileNotFoundError:
        raise HTTPException(503, "models not trained; run `python -m aqip train`")
    _cache[key] = (time.time(), res)
    return res


@app.get("/metrics")
def metrics():
    p = C.REPORTS / "model_metrics.json"
    if not p.exists():
        raise HTTPException(404, "no metrics yet")
    return json.loads(p.read_text())
