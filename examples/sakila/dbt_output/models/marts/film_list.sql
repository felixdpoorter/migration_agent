WITH categorized_films AS (
    SELECT
        film.film_id,
        film.title,
        film.description,
        CAST(film.release_year AS INT) AS release_year,
        CAST(film.rental_duration AS INT) AS rental_duration,
        film.rental_rate,
        CAST(film.length AS INT) AS length,
        film.replacement_cost,
        CAST(film.rating AS STRING) AS rating,
        CAST(film.special_features AS STRING) AS special_features,
        film_category.category_id,
        category.name AS category_name,
        film.last_update
    FROM
        {{ ref('stg_film') }} AS film
    JOIN
        {{ ref('stg_film_category') }} AS film_category
        ON film.film_id = film_category.film_id
    JOIN
        {{ ref('stg_category') }} AS category
        ON film_category.category_id = category.category_id
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
    category_name,
    last_update
FROM categorized_films;