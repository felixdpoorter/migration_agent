SELECT 
    actor_id,
    first_name,
    last_name,
    last_update
FROM {{ ref('stg_actor') }}