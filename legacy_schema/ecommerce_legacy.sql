-- ============================================================
-- Synthetic legacy e-commerce schema (MySQL)
-- Represents a real application DB + nightly ETL pipeline.
--
-- Structure:
--   Layer 1 — Source tables  : orders, customers, products
--   Layer 2 — Silver tables  : slv_orders, slv_customers, slv_products
--   Layer 3 — Gold tables    : gold_fct_orders, gold_dim_customer
--   Reporting view           : v_segment_revenue
--   ETL procedures (x5)      : load_slv_* → load_gold_fct_* / load_gold_dim_*
-- ============================================================


-- ============================================================
-- LAYER 1: SOURCE TABLES  (live application database)
-- Owned by the application; ETL team reads but does not write.
-- Data arrives with real-world messiness in the values.
-- ============================================================

CREATE TABLE orders (
  order_id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
  customer_id  INT UNSIGNED NOT NULL,
  product_id   INT UNSIGNED NOT NULL,
  quantity     SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  unit_price   DECIMAL(10,2) NOT NULL,
  order_date   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status_code  TINYINT NOT NULL DEFAULT 1,   -- 1=pending 2=shipped 3=delivered 4=cancelled
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id),
  KEY idx_orders_customer (customer_id),
  KEY idx_orders_date (order_date),
  CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
  CONSTRAINT fk_orders_product  FOREIGN KEY (product_id)  REFERENCES products  (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE customers (
  customer_id  INT UNSIGNED NOT NULL AUTO_INCREMENT,
  first_name   VARCHAR(100) NOT NULL,         -- values like '  john ', 'MARY'
  last_name    VARCHAR(100) NOT NULL,
  email        VARCHAR(200) DEFAULT NULL,     -- NULLs possible
  country_code CHAR(3) DEFAULT NULL,          -- 'BEL', 'be', 'FRA' -- inconsistent length & case
  is_active    TINYINT(1) NOT NULL DEFAULT 1,
  signup_date  DATE NOT NULL,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (customer_id),
  UNIQUE KEY uk_customers_email (email),
  KEY idx_customers_country (country_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE products (
  product_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  product_name VARCHAR(200) NOT NULL,
  category     VARCHAR(100) DEFAULT NULL,     -- 'Electronics', 'electronics ', 'ELECTRONICS'
  cost_price   DECIMAL(10,2) NOT NULL,
  list_price   DECIMAL(10,2) NOT NULL,
  is_active    TINYINT(1) NOT NULL DEFAULT 1,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (product_id),
  KEY idx_products_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- LAYER 2: SILVER TABLES  (physical tables, ETL-owned)
-- Populated nightly by stored procedures.
-- Clean, typed, normalized copy of source data.
-- ============================================================

CREATE TABLE slv_orders (
  order_id      INT UNSIGNED NOT NULL,
  customer_id   INT UNSIGNED NOT NULL,
  product_id    INT UNSIGNED NOT NULL,
  quantity      SMALLINT UNSIGNED NOT NULL,
  unit_price    DECIMAL(10,2) NOT NULL,
  order_date    DATE NOT NULL,               -- stripped to DATE (was DATETIME)
  order_status  VARCHAR(20) NOT NULL,        -- decoded: 'pending','shipped','delivered','cancelled'
  etl_load_ts   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE slv_customers (
  customer_id   INT UNSIGNED NOT NULL,
  first_name    VARCHAR(100) NOT NULL,       -- TRIMmed
  last_name     VARCHAR(100) NOT NULL,
  email         VARCHAR(200) DEFAULT NULL,   -- lowercased
  country_code  CHAR(2) DEFAULT NULL,        -- normalized to 2-char ISO ('BEL' -> 'BE')
  is_active     TINYINT(1) NOT NULL,
  signup_date   DATE NOT NULL,
  etl_load_ts   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE slv_products (
  product_id    INT UNSIGNED NOT NULL,
  product_name  VARCHAR(200) NOT NULL,
  category      VARCHAR(100) NOT NULL,       -- lowercased, TRIMmed
  cost_price    DECIMAL(10,2) NOT NULL,
  list_price    DECIMAL(10,2) NOT NULL,
  is_active     TINYINT(1) NOT NULL,
  etl_load_ts   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- LAYER 3: GOLD TABLES  (physical tables, ETL-owned)
-- Populated nightly after bronze is complete.
-- Contains computed measures and business enrichments.
-- ============================================================

CREATE TABLE gold_fct_orders (
  order_id           INT UNSIGNED NOT NULL,
  customer_id        INT UNSIGNED NOT NULL,
  product_id         INT UNSIGNED NOT NULL,
  order_date         DATE NOT NULL,
  order_status       VARCHAR(20) NOT NULL,
  quantity           SMALLINT UNSIGNED NOT NULL,
  unit_price         DECIMAL(10,2) NOT NULL,
  gross_revenue      DECIMAL(12,2) NOT NULL,   -- quantity * unit_price
  gross_margin       DECIMAL(12,2) NOT NULL,   -- quantity * (unit_price - cost_price)
  days_since_order   INT NOT NULL,             -- DATEDIFF(TODAY, order_date)
  etl_load_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id),
  KEY idx_gold_fct_orders_customer (customer_id),
  KEY idx_gold_fct_orders_date (order_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE gold_dim_customer (
  customer_id           INT UNSIGNED NOT NULL,
  first_name            VARCHAR(100) NOT NULL,
  last_name             VARCHAR(100) NOT NULL,
  email                 VARCHAR(200) DEFAULT NULL,
  country_code          CHAR(2) DEFAULT NULL,
  is_active             TINYINT(1) NOT NULL,
  signup_date           DATE NOT NULL,
  total_orders          INT UNSIGNED NOT NULL DEFAULT 0,
  lifetime_revenue      DECIMAL(14,2) NOT NULL DEFAULT 0.00,
  avg_order_value       DECIMAL(10,2) DEFAULT NULL,
  last_order_date       DATE DEFAULT NULL,
  days_since_last_order INT DEFAULT NULL,
  customer_segment      VARCHAR(20) NOT NULL DEFAULT 'no_orders',
  etl_load_ts           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- REPORTING VIEW  (on top of the mart layer)
-- ============================================================

CREATE VIEW v_segment_revenue AS
SELECT
  dc.customer_segment,
  dc.country_code,
  COUNT(DISTINCT dc.customer_id)  AS customer_count,
  SUM(fo.gross_revenue)           AS total_revenue,
  AVG(fo.gross_revenue)           AS avg_order_value,
  SUM(fo.gross_margin)            AS total_margin
FROM gold_dim_customer dc
JOIN gold_fct_orders fo ON dc.customer_id = fo.customer_id
WHERE dc.is_active = 1
GROUP BY dc.customer_segment, dc.country_code;


-- ============================================================
-- STORED PROCEDURES  (the nightly ETL pipeline)
-- Execution order: silver procs first, then gold_fct / gold_dim.
-- ============================================================

CREATE PROCEDURE load_slv_orders()
BEGIN
  TRUNCATE TABLE slv_orders;
  INSERT INTO slv_orders
    (order_id, customer_id, product_id, quantity, unit_price,
     order_date, order_status, etl_load_ts)
  SELECT
    order_id,
    customer_id,
    product_id,
    quantity,
    unit_price,
    DATE(order_date)    AS order_date,
    CASE status_code
      WHEN 1 THEN 'pending'
      WHEN 2 THEN 'shipped'
      WHEN 3 THEN 'delivered'
      WHEN 4 THEN 'cancelled'
      ELSE        'unknown'
    END                 AS order_status,
    NOW()               AS etl_load_ts
  FROM orders;
END;


CREATE PROCEDURE load_slv_customers()
BEGIN
  TRUNCATE TABLE slv_customers;
  INSERT INTO slv_customers
    (customer_id, first_name, last_name, email, country_code,
     is_active, signup_date, etl_load_ts)
  SELECT
    customer_id,
    TRIM(first_name)                    AS first_name,
    TRIM(last_name)                     AS last_name,
    LOWER(TRIM(email))                  AS email,
    UPPER(LEFT(TRIM(country_code), 2))  AS country_code,
    is_active,
    signup_date,
    NOW()                               AS etl_load_ts
  FROM customers;
END;


CREATE PROCEDURE load_slv_products()
BEGIN
  TRUNCATE TABLE slv_products;
  INSERT INTO slv_products
    (product_id, product_name, category, cost_price, list_price,
     is_active, etl_load_ts)
  SELECT
    product_id,
    TRIM(product_name)      AS product_name,
    LOWER(TRIM(category))   AS category,
    cost_price,
    list_price,
    is_active,
    NOW()                   AS etl_load_ts
  FROM products;
END;


CREATE PROCEDURE load_gold_fct_orders()
BEGIN
  TRUNCATE TABLE gold_fct_orders;
  INSERT INTO gold_fct_orders
    (order_id, customer_id, product_id, order_date, order_status,
     quantity, unit_price, gross_revenue, gross_margin,
     days_since_order, etl_load_ts)
  SELECT
    o.order_id,
    o.customer_id,
    o.product_id,
    o.order_date,
    o.order_status,
    o.quantity,
    o.unit_price,
    o.quantity * o.unit_price                   AS gross_revenue,
    o.quantity * (o.unit_price - p.cost_price)  AS gross_margin,
    DATEDIFF(CURRENT_DATE, o.order_date)        AS days_since_order,
    NOW()                                       AS etl_load_ts
  FROM slv_orders o
  JOIN slv_products p ON o.product_id = p.product_id
  WHERE o.order_status != 'cancelled';
END;


CREATE PROCEDURE load_gold_dim_customer()
BEGIN
  TRUNCATE TABLE gold_dim_customer;
  INSERT INTO gold_dim_customer
    (customer_id, first_name, last_name, email, country_code,
     is_active, signup_date, total_orders, lifetime_revenue,
     avg_order_value, last_order_date, days_since_last_order,
     customer_segment, etl_load_ts)
  SELECT
    c.customer_id,
    c.first_name,
    c.last_name,
    c.email,
    c.country_code,
    c.is_active,
    c.signup_date,
    COUNT(o.order_id)                           AS total_orders,
    COALESCE(SUM(o.gross_revenue), 0.00)        AS lifetime_revenue,
    AVG(o.gross_revenue)                        AS avg_order_value,
    MAX(o.order_date)                           AS last_order_date,
    DATEDIFF(CURRENT_DATE, MAX(o.order_date))   AS days_since_last_order,
    CASE
      WHEN COUNT(o.order_id) = 0        THEN 'no_orders'
      WHEN SUM(o.gross_revenue) >= 1000 THEN 'high_value'
      WHEN SUM(o.gross_revenue) >= 200  THEN 'mid_value'
      ELSE                                   'low_value'
    END                                         AS customer_segment,
    NOW()                                       AS etl_load_ts
  FROM slv_customers c
  LEFT JOIN gold_fct_orders o ON c.customer_id = o.customer_id
  GROUP BY
    c.customer_id, c.first_name, c.last_name, c.email,
    c.country_code, c.is_active, c.signup_date;
END;
