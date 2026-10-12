-- Station dimension. Seeded from config (see warehouse.py), one row per city.
CREATE OR REPLACE TABLE dim_station AS
SELECT station_id, city, state, lat, lon
FROM stations_seed;
