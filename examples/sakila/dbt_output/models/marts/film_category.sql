SELECT
    film_id,
    category_id,
    last_update
FROM {{ ref('stg_film_category') }}