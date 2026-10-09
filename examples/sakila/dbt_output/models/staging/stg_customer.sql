WITH source_data AS (
    SELECT
        CAST(customer_id AS INT) AS customer_id,
        CAST(store_id AS INT) AS store_id,
        first_name,
        last_name,
        email,
        CAST(active AS BOOLEAN) AS active,
        create_date,
        last_update
    FROM {{ source('legacy_mysql', 'customer') }}
)

SELECT *
FROM source_data