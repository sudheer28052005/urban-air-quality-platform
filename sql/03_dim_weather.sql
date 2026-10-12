-- Hourly weather per station, with a wind-regime bucket used in analysis.
CREATE OR REPLACE TABLE dim_weather AS
SELECT
    station_id,
    ts,
    temperature_2m          AS temp_c,
    relative_humidity_2m    AS humidity_pct,
    wind_speed_10m          AS wind_kmh,
    wind_direction_10m      AS wind_dir_deg,
    surface_pressure        AS pressure_hpa,
    precipitation           AS rain_mm,
    CASE WHEN wind_speed_10m < 5  THEN 'Calm (<5 km/h)'
         WHEN wind_speed_10m < 12 THEN 'Light (5-12)'
         ELSE 'Breezy (12+)' END AS wind_regime
FROM stg_weather;
