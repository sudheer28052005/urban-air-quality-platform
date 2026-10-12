"""Phase 1c: build the DuckDB warehouse from staging Parquet using the SQL models, then test it."""
from __future__ import annotations

import logging
from datetime import timedelta

import duckdb
import pandas as pd

from . import config as C

log = logging.getLogger("aqip.warehouse")

# Each check returns the number of offending rows; 0 = pass.
DATA_TESTS = {
    "fact_readings has no duplicate (station_id, ts)":
        "SELECT count(*) FROM (SELECT station_id, ts FROM fact_readings GROUP BY 1,2 HAVING count(*) > 1)",
    "every fact row has a station":
        "SELECT count(*) FROM fact_readings f LEFT JOIN dim_station s USING (station_id) WHERE s.station_id IS NULL",
    "AQI within 0-500":
        "SELECT count(*) FROM fact_readings WHERE aqi < 0 OR aqi > 500",
    "PM2.5 never exceeds PM10 by >50%":
        "SELECT count(*) FROM fact_readings WHERE pm2_5 > pm10 * 1.5 AND pm10 > 20",
    "no station-day gap > 12h in last 90 days":
        """SELECT count(*) FROM (SELECT station_id, date, count(*) c FROM fact_readings
           WHERE date >= (SELECT max(date) - 90 FROM fact_readings) GROUP BY 1,2 HAVING c < 12)""",
}


def build(path=C.WAREHOUSE) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.register("stations_seed", pd.DataFrame(
        [(s[0], s[1], s[2], s[3], s[4]) for s in C.CITIES],
        columns=["station_id", "city", "state", "lat", "lon"]))
    fest = []
    for name, days in C.FESTIVALS.items():
        for d in days:
            for off in (-1, 0, 1):  # +-1 day window
                fest.append((d + timedelta(days=off), name))
    con.register("festival_seed", pd.DataFrame(fest, columns=["date", "festival"])
                 .assign(date=lambda x: pd.to_datetime(x["date"]).dt.date))
    for name in ("air_quality", "weather"):
        con.execute(f"CREATE OR REPLACE TABLE stg_{name} AS "
                    f"SELECT * FROM read_parquet('{(C.STAGING / (name + '.parquet')).as_posix()}')")
    for f in sorted(C.SQL_DIR.glob("*.sql")):
        log.info("running %s", f.name)
        con.execute(f.read_text())
    results = run_tests(con)
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("dim_station", "dim_date", "dim_weather", "fact_readings")}
    con.close()
    return {"rows": counts, "tests": results}


def run_tests(con) -> dict:
    out = {}
    for name, sql in DATA_TESTS.items():
        bad = con.execute(sql).fetchone()[0]
        out[name] = bad
        (log.info if bad == 0 else log.warning)("test %-52s %s", name, "PASS" if bad == 0 else f"FAIL ({bad})")
    return out


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(C.WAREHOUSE), read_only=read_only)
