SELECT 
    CAST(actor_id AS INT) AS actor_id,
    first_name,
    last_name,
    CAST(last_update AS TIMESTAMP) AS last_update
FROM {{ source('legacy_mysql', 'actor') }}