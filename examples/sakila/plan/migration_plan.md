# MySQL → Databricks dbt Migration Plan

> **Agent instructions:** Execute tasks wave by wave. All tasks within the same wave can run in parallel. Do not start a wave until every task in the previous wave is complete. Each task lists its required actions and migration flags to handle.

---

## Wave 0 — Base Objects (no dependencies) · run all in parallel

These objects have no dependencies. Migrate them simultaneously.

---

### TASK 0.1 · `film_text` · manual_review ⚠️

**Type:** `REFERENCED` — DDL unknown

**Actions:**
1. Locate the DDL for `film_text` in the source MySQL system (check information_schema, backups, or application code).
2. Determine what columns and types it contains.
3. Decide whether it becomes a dbt source, a dbt model, or is deprecated.
4. Document findings before proceeding — Wave 1 (`ins_film`) is blocked on this object.

**Flags:** `no_ddl` — do not proceed to Wave 1 until DDL is resolved.

---

### TASK 0.2 · `actor` · dbt_model

**Type:** `TABLE` → dbt model (Delta table, mart/gold layer)

**Actions:**
1. Create `models/actor.sql` with `SELECT` from source.
2. Add to `schema.yml`.

**Migration flags to handle in SQL:**

| Flag | Column | Action |
|------|--------|--------|
| `unsigned_int` | `actor_id` | `CAST(actor_id AS INT)` — SMALLINT UNSIGNED exceeds signed SMALLINT range |

---

### TASK 0.3 · `category` · dbt_model

**Type:** `TABLE` → dbt model (Delta table, mart/gold layer)

**Actions:**
1. Create `models/category.sql` with `SELECT` from source.
2. Add to `schema.yml`.

**Migration flags to handle in SQL:**

| Flag | Column | Action |
|------|--------|--------|
| `unsigned_int` | `category_id` | `CAST(category_id AS SMALLINT)` — TINYINT UNSIGNED exceeds signed TINYINT range |

---

### TASK 0.4 · `film` · dbt_model

**Type:** `TABLE` → dbt model (Delta table, mart/gold layer)

**Actions:**
1. Create `models/film.sql` with `SELECT` from source.
2. Add to `schema.yml`.

**Migration flags to handle in SQL:**

| Flag | Column | Action |
|------|--------|--------|
| `unsigned_int` | `film_id` | `CAST(film_id AS INT)` — SMALLINT UNSIGNED |
| `unsigned_int` | `rental_duration` | `CAST(rental_duration AS SMALLINT)` — TINYINT UNSIGNED |
| `unsigned_int` | `length` | `CAST(length AS INT)` — SMALLINT UNSIGNED |
| `year_type` | `release_year` | `CAST(release_year AS INT)` — YEAR type not supported in Databricks |
| `enum_column` | `rating` | `CAST(rating AS STRING)` in SQL; add `accepted_values` test in schema.yml with values `['G','PG','PG-13','R','NC-17']` |
| `set_column` | `special_features` | `CAST(special_features AS STRING)` or split into `ARRAY<STRING>` using `split(special_features, ',')` |

---

### TASK 0.5 · `customer` · dbt_model

**Type:** `TABLE` → dbt model (Delta table, mart/gold layer)

**Actions:**
1. Create `models/customer.sql` with `SELECT` from source.
2. Add to `schema.yml`.

**Migration flags to handle in SQL:**

| Flag | Column | Action |
|------|--------|--------|
| `unsigned_int` | `customer_id` | `CAST(customer_id AS INT)` — SMALLINT UNSIGNED |
| `unsigned_int` | `store_id` | `CAST(store_id AS SMALLINT)` — TINYINT UNSIGNED |

---

## Wave 1 — Depends on Wave 0 · run all in parallel

> **Prerequisite:** All Wave 0 tasks must be complete, including DDL resolution for `film_text`.

---

### TASK 1.1 · `film_actor` · dbt_model

**Type:** `TABLE` → dbt model (Delta table, mart/gold layer)

**Depends on:** `actor` (T0.2), `film` (T0.4)

**Actions:**
1. Create `models/film_actor.sql` referencing `{{ ref('actor') }}` and `{{ ref('film') }}`.
2. Add to `schema.yml`.

**Migration flags to handle in SQL:**

| Flag | Column | Action |
|------|--------|--------|
| `unsigned_int` | `actor_id` | `CAST(actor_id AS INT)` |
| `unsigned_int` | `film_id` | `CAST(film_id AS INT)` |
| `composite_pk` | `actor_id, film_id` | Add `dbt_utils.unique_combination_of_columns` test in schema.yml |
| `fk_constraint` | `actor_id` | Add `relationships` test → `actor.actor_id` in schema.yml (note: not enforced on Delta) |
| `fk_constraint` | `film_id` | Add `relationships` test → `film.film_id` in schema.yml (note: not enforced on Delta) |

---

### TASK 1.2 · `film_category` · dbt_model

**Type:** `TABLE` → dbt model (Delta table, mart/gold layer)

**Depends on:** `category` (T0.3), `film` (T0.4)

**Actions:**
1. Create `models/film_category.sql` referencing `{{ ref('category') }}` and `{{ ref('film') }}`.
2. Add to `schema.yml`.

**Migration flags to handle in SQL:**

| Flag | Column | Action |
|------|--------|--------|
| `unsigned_int` | `film_id` | `CAST(film_id AS INT)` |
| `unsigned_int` | `category_id` | `CAST(category_id AS SMALLINT)` |
| `composite_pk` | `film_id, category_id` | Add `dbt_utils.unique_combination_of_columns` test in schema.yml |
| `fk_constraint` | `film_id` | Add `relationships` test → `film.film_id` in schema.yml |
| `fk_constraint` | `category_id` | Add `relationships` test → `category.category_id` in schema.yml |

---

### TASK 1.3 · `ins_film` · manual_review ⚠️

**Type:** `PROCEDURE` → rewrite as dbt model(s)

**Depends on:** `film` (T0.4), `film_text` (T0.1 — DDL must be resolved first)

**Actions:**
1. Review the stored procedure logic for `ins_film`.
2. Determine target layer by asking: does this write to something other objects consume (→ staging/intermediate) or does it produce the final output (→ mart/gold)?
3. Rewrite the INSERT/UPDATE logic as a dbt `SELECT` transformation.
4. Replace any `film_text` references with the resolved model from T0.1.
5. Add tests for the rewritten model.

---

### TASK 1.4 · `list_active_customers` · manual_review ⚠️

**Type:** `PROCEDURE` → rewrite as dbt model(s)

**Depends on:** `customer` (T0.5)

**Actions:**
1. Review the stored procedure logic for `list_active_customers`.
2. Determine target layer by asking: does this write to something other objects consume (→ staging/intermediate) or does it produce the final output (→ mart/gold)?
3. Rewrite the logic as a dbt `SELECT` transformation referencing `{{ ref('customer') }}`.
4. Add tests for the rewritten model.

---

## Wave 2 — Depends on Wave 1 · run both in parallel

> **Prerequisite:** All Wave 1 tasks must be complete (`film_actor`, `film_category`, `ins_film`, `list_active_customers`).

---

### TASK 2.1 · `actor_info` · dbt_view

**Type:** `VIEW` → dbt view (transformation layer, assess bronze→silver or silver→gold)

**Depends on:** `actor` (T0.2), `category` (T0.3), `film_actor` (T1.1), `film_category` (T1.2)

**Actions:**
1. Determine target layer: are other objects consuming this view (→ intermediate) or is this the final consumer-facing output (→ mart/gold)? Given it aggregates actor + film data, likely mart/gold.
2. Create `models/actor_info.sql` with `{{ config(materialized='view') }}`.
3. Rewrite SELECT logic using `{{ ref('actor') }}`, `{{ ref('category') }}`, `{{ ref('film_actor') }}`, `{{ ref('film_category') }}`.
4. Add to `schema.yml`.

---

### TASK 2.2 · `film_list` · dbt_view

**Type:** `VIEW` → dbt view (transformation layer, assess bronze→silver or silver→gold)

**Depends on:** `category` (T0.3), `film` (T0.4), `film_category` (T1.2)

**Actions:**
1. Determine target layer: are other objects consuming this view (→ intermediate) or is this the final consumer-facing output (→ mart/gold)? Given it aggregates film + category data, likely mart/gold.
2. Create `models/film_list.sql` with `{{ config(materialized='view') }}`.
3. Rewrite SELECT logic using `{{ ref('category') }}`, `{{ ref('film') }}`, `{{ ref('film_category') }}`.
4. Add to `schema.yml`.

---

## Summary

| Wave | Tasks | Parallelisable | Blocker |
|------|-------|---------------|---------|
| 0 | `film_text`, `actor`, `category`, `film`, `customer` | ✅ All 5 in parallel | None |
| 1 | `film_actor`, `film_category`, `ins_film`, `list_active_customers` | ✅ All 4 in parallel | Wave 0 complete + `film_text` DDL resolved |
| 2 | `actor_info`, `film_list` | ✅ Both in parallel | Wave 1 complete |

**Critical path:** `film_text` (manual DDL lookup) → `ins_film` (procedure rewrite) → Wave 2 unblocked.
