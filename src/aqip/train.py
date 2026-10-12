"""Phase 3b: train, evaluate (time-based CV + holdout), explain (SHAP) and save forecast models."""
from __future__ import annotations

import json
import logging

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config as C
from .features import add_aqi, feature_columns, make_dataset

log = logging.getLogger("aqip.train")
HOLDOUT_DAYS = 45
LGB_PARAMS = dict(n_estimators=500, learning_rate=0.04, num_leaves=48, min_child_samples=60,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                  n_jobs=-1, verbose=-1, random_state=7)


def load_frame() -> pd.DataFrame:
    aq = pd.read_parquet(C.STAGING / "air_quality.parquet", columns=["station_id", "ts", *C.POLLUTANTS])
    wx = pd.read_parquet(C.STAGING / "weather.parquet", columns=["station_id", "ts", *C.WEATHER_VARS])
    return add_aqi(aq.merge(wx, on=["station_id", "ts"], how="inner"))


def metrics(y, p) -> dict:
    return {"mae": float(mean_absolute_error(y, p)), "rmse": float(np.sqrt(mean_squared_error(y, p)))}


def _ridge():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10.0))


def _lgb(**kw):
    return lgb.LGBMRegressor(**{**LGB_PARAMS, **kw})


def evaluate_horizon(ds: pd.DataFrame, h: int) -> tuple[dict, pd.DataFrame, list[str]]:
    feats = feature_columns(ds)
    d = ds.dropna(subset=["target"]).reset_index(drop=True)
    n_st = len(C.CITIES)
    models = {"persistence": None, "ridge": _ridge, "lightgbm": _lgb}

    # --- expanding-window time-series CV (gap prevents target leakage across the split) ---
    cv = {k: [] for k in models}
    for tr, te in TimeSeriesSplit(n_splits=4, test_size=n_st * 24 * 45, gap=n_st * h).split(d):
        Xtr, ytr, Xte, yte = d.loc[tr, feats], d.loc[tr, "target"], d.loc[te, feats], d.loc[te, "target"]
        cv["persistence"].append(metrics(yte, Xte["aqi"].fillna(yte.mean())))
        for name in ("ridge", "lightgbm"):
            m = models[name]().fit(Xtr, ytr)
            cv[name].append(metrics(yte, m.predict(Xte)))
    cv_mean = {k: {m: float(np.mean([f[m] for f in v])) for m in ("mae", "rmse")} for k, v in cv.items()}

    # --- final holdout: last 45 days, trained on everything before (minus gap) ---
    cutoff = d["ts"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    tr = d["ts"] < cutoff - pd.Timedelta(hours=h)
    te = d["ts"] >= cutoff
    Xtr, ytr, Xte, yte = d.loc[tr, feats], d.loc[tr, "target"], d.loc[te, feats], d.loc[te, "target"]
    hold = {"persistence": metrics(yte, Xte["aqi"].fillna(yte.mean()))}
    preds = {}
    for name in ("ridge", "lightgbm"):
        m = models[name]().fit(Xtr, ytr)
        preds[name] = m.predict(Xte)
        hold[name] = metrics(yte, preds[name])
    # quantile models for an 80% prediction interval
    lo = _lgb(objective="quantile", alpha=0.1).fit(Xtr, ytr).predict(Xte)
    hi = _lgb(objective="quantile", alpha=0.9).fit(Xtr, ytr).predict(Xte)
    hold["interval_80_coverage"] = float(np.mean((yte.to_numpy() >= lo) & (yte.to_numpy() <= hi)))
    per_city = (pd.DataFrame({"station_id": d.loc[te, "station_id"], "err": np.abs(yte - preds["lightgbm"])})
                .groupby("station_id")["err"].mean())
    names = {s[0]: s[1] for s in C.CITIES}
    hold["lightgbm_mae_by_city"] = {names[k]: float(v) for k, v in per_city.items()}
    # category agreement: does the forecast land in the right CPCB band?
    bins = [-1, 50, 100, 200, 300, 400, 501]
    hold["category_accuracy"] = float(np.mean(
        pd.cut(yte, bins, labels=False).to_numpy() == pd.cut(pd.Series(preds["lightgbm"], index=yte.index), bins, labels=False).to_numpy()))
    return {"cv": cv_mean, "holdout": hold}, d, feats


def fit_final(d: pd.DataFrame, feats: list[str], h: int) -> dict:
    X, y = d[feats], d["target"]
    return {
        "features": feats, "horizon": h,
        "q50": _lgb().fit(X, y),
        "q10": _lgb(objective="quantile", alpha=0.1).fit(X, y),
        "q90": _lgb(objective="quantile", alpha=0.9).fit(X, y),
    }


def explain(bundle: dict, d: pd.DataFrame) -> dict:
    import shap
    sample = d[bundle["features"]].tail(60_000).sample(4000, random_state=0)
    sv = shap.TreeExplainer(bundle["q50"]).shap_values(sample)
    imp = pd.Series(np.abs(sv).mean(axis=0), index=bundle["features"]).sort_values(ascending=False)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        shap.summary_plot(sv, sample, show=False, max_display=15)
        plt.tight_layout()
        plt.savefig(C.REPORTS / "shap_summary_24h.png", dpi=130)
        plt.close()
    except Exception as exc:  # plotting is a nicety; never fail training on it
        log.warning("SHAP plot skipped: %s", exc)
    return {k: float(v) for k, v in imp.head(20).items()}


def run() -> dict:
    C.MODELS.mkdir(parents=True, exist_ok=True)
    C.REPORTS.mkdir(parents=True, exist_ok=True)
    frame = load_frame()
    report = {"trained_through": str(frame["ts"].max()), "horizons": {}}
    for h in C.HORIZONS:
        log.info("horizon %dh: building dataset", h)
        ds = make_dataset(frame, h)
        res, d, feats = evaluate_horizon(ds, h)
        log.info("h=%d holdout %s", h, {k: round(v["mae"], 1) for k, v in res["holdout"].items() if isinstance(v, dict) and "mae" in v})
        bundle = fit_final(d, feats, h)
        joblib.dump(bundle, C.MODELS / f"forecast_{h}h.joblib", compress=3)
        if h == 24:
            res["shap_top_features"] = explain(bundle, d)
        report["horizons"][str(h)] = res
    (C.REPORTS / "model_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
