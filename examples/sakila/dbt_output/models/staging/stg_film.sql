WITH source_data AS (
    SELECT
        film_id,
        title,
        description,
        CAST(release_year AS INT) AS release_year,
        CAST(rental_duration AS INT) AS rental_duration,
        rental_rate,
        CAST(length AS INT) AS length,
        replacement_cost,
        CAST(rating AS STRING) AS rating,
        CAST(special_features AS STRING) AS special_features,
        last_update
    FROM {{ source('legacy_mysql', 'film') }}
)
SELECT
    film_id,
    title,
    description,
    release_year,
    rental_duration,
    rental_rate,
    length,
    replacement_cost,
    rating,
    special_features,
    last_update
FROM source_data