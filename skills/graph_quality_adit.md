# Graph Database Quality & Integrity Audit Metrics

Dit contract definieert de minimale kwaliteitseisen waar de geparseerde Knowledge Graph aan moet voldoen.

## Gecentraliseerde Kwaliteitscontroles:
1. ORPHAN_COLUMNS: Kolom-nodes die niet zijn gekoppeld aan een tabel of view via een HAS_COLUMN relatie.
2. DISCONNECTED_ROUTINES: Stored Procedures of Functies die geen enkele READS_FROM of WRITES_TO relatie hebben (dode code).
3. STALE_REFERENCES: Foreign Key-relaties (REFERENCES) die wijzen naar een tabel- of kolomnode die niet bestaat in het ingeladen schema.
4. UNMAPPED_LAYERS: Tabel-nodes waarvan de AI-classifier de dbt-laag (Bronze, Silver, Gold) niet heeft kunnen bepalen.
5. MULTIPLE_WRITERS: Tabellen die door meerdere Stored Procedures worden beschreven (anti-pattern voor dbt models).
6. CYCLIC_DEPENDENCIES: Circulaire objectrelaties (verstoort de dbt DAG opbouw).
7. STALE_VIEWS: Views die proberen te lezen van onbekende of ontbrekende tabellen.
8. DATATYPE_MISMATCH_ON_FK: Relaties waarbij de sleutelkolommen niet dezelfde datatypes delen.
9. UNUSED_SOURCES: Brontabellen die door geen enkel ander database-object worden aangeroepen