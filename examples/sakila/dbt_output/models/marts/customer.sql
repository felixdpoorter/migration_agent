SELECT
    customer_id,
    store_id,
    first_name,
    last_name,
    email,
    active,
    create_date,
    last_update
FROM {{ ref('stg_customer') }}