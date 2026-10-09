SELECT 
    category_id,
    name,
    last_update
FROM {{ ref('stg_category') }}