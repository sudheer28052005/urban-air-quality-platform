import numpy as np
import pandas as pd
import pytest

from aqip import config as C
from aqip.aqi import category, compute_aqi, sub_index
from aqip.clean import _clean_station, _dedupe
from aqip.features import add_aqi, feature_columns, make_dataset


def test_pm25_subindex_breakpoints():
    assert sub_index([0, 30, 60, 90, 120, 250], "pm2_5").tolist() == [0, 50, 100, 200, 300, 400]
    assert sub_index([45], "pm2_5")[0] == pytest.approx(75)
    assert sub_index([10_000], "pm2_5")[0] == 500


def test_aqi_takes_max_and_requires_particulates():
    df = pd.DataFrame({"pm2_5": [30.0, np.nan], "pm10": [50.0, np.nan], "no2": [80.0, 80.0],
                       "so2": [0.0, 0.0], "o3": [0.0, 0.0], "co": [0.0, 0.0]})
    aqi = compute_aqi(df)
    assert aqi.iloc[0] == pytest.approx(100)   # NO2 80 dominates PM
    assert np.isnan(aqi.iloc[1])               # no PM reading -> no AQI


def test_category_bands():
    assert category(50) == "Good" and category(51) == "Satisfactory" and category(450) == "Severe"
    assert category(float("nan")) == "Unknown"


def test_dedupe_keeps_latest_ingest():
    ts = pd.Timestamp("2025-01-01")
    df = pd.DataFrame({"station_id": ["DEL"] * 2, "ts": [ts, ts], "pm2_5": [1.0, 2.0],
                       "_ingested_at": ["20250101", "20250102"]})
    out = _dedupe(df)
    assert len(out) == 1 and out["pm2_5"].iloc[0] == 2.0


def test_short_gaps_filled_long_gaps_left_and_outliers_dropped():
    idx = pd.date_range("2025-01-01", periods=30, freq="h").delete(list(range(5, 8)) + list(range(15, 25)))
    g = pd.DataFrame({"station_id": "DEL", "ts": idx, "pm2_5": np.linspace(10, 40, len(idx))})
    g.loc[0, "pm2_5"] = 99999  # impossible reading
    out = _clean_station(g, ["pm2_5"]).set_index("ts")["pm2_5"]
    assert len(out) == 30
    assert out.iloc[5:8].notna().all()      # 3h gap interpolated
    assert out.iloc[15:25].isna().sum() >= 4  # 10h gap mostly left missing
    assert np.isnan(out.iloc[0])            # outlier removed


def _synthetic(hours=24 * 20):
    ts = pd.date_range("2025-01-01", periods=hours, freq="h")
    rng = np.random.default_rng(0)
    d = pd.DataFrame({"station_id": "DEL", "ts": ts})
    for p in C.POLLUTANTS:
        d[p] = rng.uniform(10, 100, hours)
    for w in C.WEATHER_VARS:
        d[w] = rng.uniform(1, 10, hours)
    return add_aqi(d)


def test_features_never_use_pollutants_after_t():
    """Perturbing future pollutant values must not change features at time t."""
    base = _synthetic()
    h, t = 24, 24 * 10
    f1 = make_dataset(base, h)
    pert = base.copy()
    pert.loc[pert.index > t, C.POLLUTANTS] += 500
    pert = add_aqi(pert.drop(columns="aqi"))
    f2 = make_dataset(pert, h)
    cols = [c for c in feature_columns(f1) if c not in ("target",)]
    a, b = f1.iloc[t][cols].astype(float), f2.iloc[t][cols].astype(float)
    pd.testing.assert_series_equal(a, b)


def test_target_is_aqi_h_hours_ahead():
    base = _synthetic()
    ds = make_dataset(base, 24).sort_values("ts").reset_index(drop=True)
    i = 100
    assert ds.loc[i, "target"] == pytest.approx(base.loc[i + 24, "aqi"])
