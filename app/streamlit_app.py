"""Dashboard: streamlit run app/streamlit_app.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from aqip import config as C
from aqip.aqi import category
from aqip.forecast import forecast_city
from aqip.warehouse import connect

COLORS = {"Good": "#009865", "Satisfactory": "#9fcc3b", "Moderate": "#f5c400",
          "Poor": "#f58220", "Very Poor": "#e8262b", "Severe": "#8b1d1d", "Unknown": "#888"}

st.set_page_config(page_title="Urban Air Quality Intelligence", page_icon="🌫️", layout="wide")


@st.cache_data(ttl=3600)
def q(sql: str) -> pd.DataFrame:
    con = connect()
    try:
        return con.execute(sql).df()
    finally:
        con.close()


@st.cache_data(ttl=900, show_spinner="Fetching live data and forecasting...")
def live(city: str) -> dict:
    return forecast_city(city)


st.title("🌫️ Urban Air Quality Intelligence Platform")
st.caption("Hourly pipeline → DuckDB warehouse → LightGBM 24/48/72h forecasts. Source: Open-Meteo (CAMS model), CPCB AQI scale.")

cities = [c[1] for c in C.CITIES]
tab_live, tab_map, tab_trends, tab_insights, tab_model = st.tabs(
    ["Live forecast", "City map", "Trends", "Insights", "Model"])

with tab_live:
    city = st.selectbox("City", cities)
    try:
        res = live(city)
    except FileNotFoundError:
        st.error("Models not found. Run `python -m aqip train` first.")
        st.stop()
    cur = res["current_aqi"]
    cols = st.columns(4)
    cols[0].metric("Now", f"{cur:.0f}", res["current_category"])
    for col, f in zip(cols[1:], res["forecast"]):
        col.metric(f"+{f['horizon_h']} h", f"{f['aqi']}", f"{f['category']} (range {f['aqi_low']}–{f['aqi_high']})",
                   delta_color="off")
    worst = max(res["forecast"], key=lambda f: f["aqi"])
    if worst["aqi"] > 200:
        st.error(f"Poor air expected: AQI ~{worst['aqi']} around {worst['valid_at']}. Limit outdoor exertion.")
    elif worst["aqi"] > 100:
        st.warning(f"Moderate air expected (AQI ~{worst['aqi']}). Sensitive groups should take care.")
    else:
        st.success("Air quality is forecast to stay in the Good/Satisfactory range.")

    hist = pd.DataFrame(res["history_24h"]).assign(ts=lambda d: pd.to_datetime(d["ts"]))
    fc = pd.DataFrame(res["forecast"]).assign(valid_at=lambda d: pd.to_datetime(d["valid_at"]))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["ts"], y=hist["aqi"], name="Observed (last 48 h)", line=dict(color="#1f77b4")))
    fig.add_trace(go.Scatter(x=fc["valid_at"], y=fc["aqi_high"], mode="lines", line=dict(width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=fc["valid_at"], y=fc["aqi_low"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(214,39,40,.2)", name="80% interval"))
    fig.add_trace(go.Scatter(x=fc["valid_at"], y=fc["aqi"], mode="lines+markers", name="Forecast",
                             line=dict(color="#d62728", dash="dot")))
    fig.update_layout(height=380, yaxis_title="AQI (CPCB)", margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Forecast issued from the last observed hour: {res['issued_at']} IST.")

with tab_map:
    latest = q("""SELECT city, lat, lon, round(aqi_mean) AS aqi, round(pm2_5, 1) AS pm25
                  FROM mart_daily WHERE date = (SELECT max(date) - 1 FROM mart_daily)""")
    latest["category"] = latest["aqi"].map(category)
    fig = px.scatter_map(latest, lat="lat", lon="lon", size="aqi", color="category", hover_name="city",
                            hover_data={"aqi": True, "pm25": True, "lat": False, "lon": False},
                            color_discrete_map=COLORS, size_max=38, zoom=3.6, height=560,
                            center={"lat": 22.5, "lon": 80})
    fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Latest complete day, daily mean AQI.")

with tab_trends:
    daily = q("SELECT city, date, aqi_mean, pm2_5, season FROM mart_daily ORDER BY date")
    sel = st.multiselect("Cities", cities, default=["Delhi", "Mumbai", "Bengaluru"])
    sm = daily[daily["city"].isin(sel)]
    fig = px.line(sm, x="date", y="aqi_mean", color="city", title="Daily mean AQI")
    for y, label in ((100, "Satisfactory"), (200, "Moderate"), (300, "Poor")):
        fig.add_hline(y=y, line_dash="dot", line_color="#999", annotation_text=f"> {label}")
    st.plotly_chart(fig, use_container_width=True)
    heat = q("""SELECT city, month(date) AS month, round(avg(pm2_5), 1) AS pm25 FROM mart_daily GROUP BY ALL""")
    pivot = heat.pivot(index="city", columns="month", values="pm25").reindex(cities)
    st.plotly_chart(px.imshow(pivot, color_continuous_scale="YlOrRd", aspect="auto", text_auto=".0f",
                              title="Seasonal heatmap: mean PM2.5 (µg/m³) by month",
                              labels=dict(x="Month", y="City", color="PM2.5")), use_container_width=True)
    over = q(f"""SELECT city, count(*) FILTER (WHERE pm2_5 > {C.WHO_PM25_24H}) AS days_over_who, count(*) AS days
                 FROM mart_daily WHERE date >= (SELECT max(date) - 30 FROM mart_daily) GROUP BY city
                 ORDER BY days_over_who DESC""")
    st.subheader("Alerts: days above the WHO PM2.5 guideline (last 30 days)")
    st.dataframe(over, hide_index=True, use_container_width=True)

with tab_insights:
    p = C.REPORTS / "insights.md"
    st.markdown(p.read_text(encoding="utf-8") if p.exists() else "Run `python -m aqip insights`.")

with tab_model:
    p = C.REPORTS / "model_metrics.json"
    if p.exists():
        m = json.loads(p.read_text())
        rows = []
        for h, r in m["horizons"].items():
            for name in ("persistence", "ridge", "lightgbm"):
                rows.append({"horizon_h": int(h), "model": name, "holdout MAE": r["holdout"][name]["mae"],
                             "holdout RMSE": r["holdout"][name]["rmse"], "CV MAE": r["cv"][name]["mae"]})
        st.subheader("Model comparison (AQI points; lower is better)")
        st.dataframe(pd.DataFrame(rows).round(1), hide_index=True, use_container_width=True)
        shap_top = m["horizons"]["24"].get("shap_top_features", {})
        if shap_top:
            s = pd.Series(shap_top).sort_values()
            st.plotly_chart(px.bar(s, orientation="h", title="What drives the 24 h forecast (mean |SHAP|)",
                                   labels=dict(value="mean |SHAP| (AQI points)", index="")), use_container_width=True)
        img = C.REPORTS / "shap_summary_24h.png"
        if img.exists():
            st.image(str(img), caption="SHAP summary, 24 h model")
    else:
        st.info("Run `python -m aqip train` to generate metrics.")
