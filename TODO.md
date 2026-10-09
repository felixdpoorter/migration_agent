# TODO — dbt Migration Agent

---

## Infer FK relationships with the LLM (notebook 01)

**Why:** Legacy schemas often have no `FOREIGN KEY` constraints in the DDL even though the relationships exist (column naming conventions like `customer_id`, `product_id`). The sqlglot parser only extracts explicit FK constraints, so the graph gets zero FK edges from a schema like this one. Inferring them with an LLM fills that gap.

**Where to add it:** `01_knowledge_graph_from_legacy_sql.ipynb` — new Step 4c, inserted after Step 4b (foreign key extraction) and before Step 5 (views).

**Approach — Option B (separate LLM step on structured data):**

After Step 4a/4b, `parsed_tables` already contains clean column names and types for every table. Pass that structured metadata to the LLM instead of the raw SQL — it's easier to reason over and the response is easier to validate.

**Prompt idea:**
```
Given the following table definitions (name + columns + types),
identify all likely foreign key relationships based on column names,
naming conventions, and data types.

Return a JSON array:
[
  {"from_table": "...", "from_col": "...", "to_table": "...", "to_col": "..."},
  ...
]

Only return relationships you are confident about.
Do not invent relationships that are not implied by the column names.
```

**Validation to add after the LLM response:**
- Check that `from_table`, `to_table` exist in `parsed_tables`
- Check that `from_col`, `to_col` exist in their respective tables
- Check that `from_col` and `to_col` have compatible types (both INT UNSIGNED, etc.)
- Merge with any explicit FKs already found by sqlglot (deduplicate)

**Output:** append inferred FKs to the existing `foreign_keys` list — the graph builder (Step 7) and Neo4j export (Step 10) consume it unchanged.

**Prompt file:** create `skills/fk_inference_prompt.md` (same pattern as `skills/sql_classifier_prompt.md`).

---

## Other TODOs

- Add evaluation step at the end of notebook 01 (LLM check on graph quality)
- see 8b: stored procedure lineage
-- TO DO later: add evaluation steps here (check / LLM evaluation) to check GRAPH db 