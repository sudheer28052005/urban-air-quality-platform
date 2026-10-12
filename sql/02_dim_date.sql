-- Calendar dimension with season and festival flags (festival days seeded from config).
CREATE OR REPLACE TABLE dim_date AS
WITH days AS (
    SELECT CAST(d AS DATE) AS date
    FROM generate_series(
        (SELECT CAST(MIN(ts) AS DATE) FROM stg_air_quality),
        (SELECT CAST(MAX(ts) AS DATE) FROM stg_air_quality),
        INTERVAL 1 DAY) t(d)
)
SELECT
    d.date,
    year(d.date)                              AS year,
    month(d.date)                             AS month,
    dayofweek(d.date)                         AS dow,          -- 0 = Sunday
    dayofweek(d.date) IN (0, 6)               AS is_weekend,
    CASE
        WHEN month(d.date) IN (11, 12, 1, 2)  THEN 'Winter'
        WHEN month(d.date) IN (3, 4, 5)       THEN 'Summer'
        WHEN month(d.date) IN (6, 7, 8, 9)    THEN 'Monsoon'
        ELSE 'Post-monsoon'
    END                                       AS season,
    f.festival                                AS festival,
    f.festival IS NOT NULL                    AS is_festival
FROM days d
LEFT JOIN festival_seed f ON d.date = f.date;
