-- Models the `actor_info` view in Databricks.

WITH actor AS (
  SELECT 
    CAST(actor_id AS INT) AS actor_id,
    first_name,
    last_name,
    last_update
  FROM {{ ref('stg_actor') }}
),
film_actor AS (
  SELECT 
    CAST(actor_id AS INT) AS actor_id,
    CAST(film_id AS INT) AS film_id,
    last_update
  FROM {{ ref('stg_film_actor') }}
),
film_category AS (
  SELECT 
    CAST(film_id AS INT) AS film_id,
    CAST(category_id AS INT) AS category_id,
    last_update
  FROM {{ ref('stg_film_category') }}
),
category AS (
  SELECT 
    CAST(category_id AS INT) AS category_id,
    name AS category_name,
    last_update
  FROM {{ ref('stg_category') }}
)

SELECT 
  a.actor_id,
  a.first_name,
  a.last_name,
  c.category_name
FROM actor a
LEFT JOIN film_actor fa ON a.actor_id = fa.actor_id
LEFT JOIN film_category fc ON fa.film_id = fc.film_id
LEFT JOIN category c ON fc.category_id = c.category_id