-- Analytics marts consumed by the dashboard and the insights report.
CREATE OR REPLACE VIEW mart_hourly AS
SELECT f.*, s.city, s.state, s.lat, s.lon, w.temp_c, w.humidity_pct, w.wind_kmh,
       w.wind_dir_deg, w.pressure_hpa, w.rain_mm, w.wind_regime,
       d.season, d.is_weekend, d.festival, d.is_festival
FROM fact_readings f
JOIN dim_station s USING (station_id)
LEFT JOIN dim_weather w USING (station_id, ts)
LEFT JOIN dim_date d ON f.date = d.date;

CREATE OR REPLACE VIEW mart_daily AS
SELECT station_id, city, state, lat, lon, date, season, is_weekend, festival, is_festival,
       avg(pm2_5) AS pm2_5, avg(pm10) AS pm10, avg(no2) AS no2, avg(o3) AS o3,
       max(aqi) AS aqi_max, avg(aqi) AS aqi_mean,
       avg(wind_kmh) AS wind_kmh, avg(temp_c) AS temp_c, avg(humidity_pct) AS humidity_pct,
       sum(rain_mm) AS rain_mm, count(*) AS hours
FROM mart_hourly
GROUP BY ALL
HAVING count(*) >= 18;   -- require near-complete days
