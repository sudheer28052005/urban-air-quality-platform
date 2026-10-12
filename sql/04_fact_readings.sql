-- Grain: one row per station-hour. Pollutants and the derived 24h-basis AQI.
CREATE OR REPLACE TABLE fact_readings AS
SELECT
    station_id,
    ts,
    CAST(ts AS DATE) AS date,
    pm2_5, pm10, no2, so2, o3, co,
    aqi,
    CASE WHEN aqi IS NULL THEN NULL
         WHEN aqi <= 50  THEN 'Good'
         WHEN aqi <= 100 THEN 'Satisfactory'
         WHEN aqi <= 200 THEN 'Moderate'
         WHEN aqi <= 300 THEN 'Poor'
         WHEN aqi <= 400 THEN 'Very Poor'
         ELSE 'Severe' END AS aqi_category,
    (pm2_5_imputed OR pm10_imputed) AS was_imputed
FROM stg_air_quality
WHERE pm2_5 IS NOT NULL OR pm10 IS NOT NULL;
