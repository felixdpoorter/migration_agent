SELECT
    CAST(film_id AS INT) AS film_id,
    CAST(category_id AS INT) AS category_id,
    last_update
FROM {{ source('legacy_mysql', 'film_category') }}