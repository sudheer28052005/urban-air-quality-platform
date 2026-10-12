"""Phase 1a: pull hourly air quality + weather from Open-Meteo into a Parquet data lake.

Raw files are partitioned by source/city and stamped with the ingestion time, so
runs are append-only and replayable. Cleaning happens downstream (clean.py).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from . import config as C

log = logging.getLogger("aqip.ingest")
_session = requests.Session()


def _get(url: str, params: dict, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=60)
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise RuntimeError(f"{r.status_code} from {url}: {r.text[:200]}")  # not retryable
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}: {r.text[:120]}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            wait = 2**attempt
            log.warning("GET failed (%s); retry in %ss", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def _to_frame(payload: dict, station_id: str) -> pd.DataFrame:
    hourly = payload["hourly"]
    df = pd.DataFrame(hourly).rename(columns={"time": "ts", **C.API_POLLUTANTS})
    df["ts"] = pd.to_datetime(df["ts"])
    df.insert(0, "station_id", station_id)
    return df


def fetch_air_quality(station, start: date, end: date) -> pd.DataFrame:
    sid, _, _, lat, lon = station
    payload = _get(C.AQ_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(C.API_POLLUTANTS),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "timezone": "Asia/Kolkata",
    })
    return _to_frame(payload, sid)


def fetch_weather(station, start: date, end: date) -> pd.DataFrame:
    sid, _, _, lat, lon = station
    payload = _get(C.WX_HIST_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(C.WEATHER_VARS),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "timezone": "Asia/Kolkata",
    })
    return _to_frame(payload, sid)


def _write(df: pd.DataFrame, source: str, sid: str, run_id: str) -> None:
    out = C.RAW / source / f"station_id={sid}"
    out.mkdir(parents=True, exist_ok=True)
    df = df.assign(_ingested_at=run_id)
    df.to_parquet(out / f"{run_id}.parquet", index=False)


def run(history_days: int = C.HISTORY_DAYS, incremental: bool = False) -> str:
    """Fetch every station. `incremental` pulls only the last 7 days (hourly cron)."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end = date.today()
    if incremental and not any(C.RAW.rglob("*.parquet")):
        incremental = False  # cold lake (e.g. first CI run): backfill the full history
    start = end - timedelta(days=7 if incremental else history_days)
    for st in C.CITIES:
        log.info("ingesting %s %s -> %s", st[1], start, end)
        _write(fetch_air_quality(st, start, end), "air_quality", st[0], run_id)
        _write(fetch_weather(st, start, end), "weather", st[0], run_id)
    return run_id


def fetch_live(station, past_days: int = 8) -> pd.DataFrame:
    """Recent observations plus weather forecast, used by the API and dashboard.

    Returns one hourly frame: pollutants are NaN for future hours, weather covers
    the past `past_days` and the next 4 days.
    """
    sid, _, _, lat, lon = station
    aq = _get(C.AQ_URL, {
        "latitude": lat, "longitude": lon, "hourly": ",".join(C.API_POLLUTANTS),
        "past_days": past_days, "forecast_days": 1, "timezone": "Asia/Kolkata",
    })
    wx = _get(C.WX_FCST_URL, {
        "latitude": lat, "longitude": lon, "hourly": ",".join(C.WEATHER_VARS),
        "past_days": past_days, "forecast_days": 5, "timezone": "Asia/Kolkata",
    })
    a, w = _to_frame(aq, sid), _to_frame(wx, sid)
    df = w.merge(a, on=["station_id", "ts"], how="left")
    # Air quality API includes modelled hours into "today"; keep only hours that are past.
    now = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("h")
    df.loc[df["ts"] > now, C.POLLUTANTS] = float("nan")
    return df
