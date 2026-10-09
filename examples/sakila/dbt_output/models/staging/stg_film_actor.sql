SELECT 
    CAST(actor_id AS INT) AS actor_id,
    CAST(film_id AS INT) AS film_id,
    last_update
FROM {{ source('legacy_mysql', 'film_actor') }}