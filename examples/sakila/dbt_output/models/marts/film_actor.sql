SELECT 
    actor_id,
    film_id,
    last_update
FROM {{ ref('stg_film_actor') }}