SELECT 
    CAST(category_id AS INT) AS category_id,
    name,
    CAST(last_update AS TIMESTAMP) AS last_update
FROM {{ source('legacy_mysql', 'category') }}