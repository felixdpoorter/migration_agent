# sakila-dbt — Project Setup Instructions for GitHub Copilot

## Context

This is a **dbt project** for the Sakila MySQL → Databricks migration.
It receives generated dbt models from a separate migration agent project (`dbt-migration-agent`)
and exposes an **MCP server** so other tools (Copilot, notebooks) can push files and trigger dbt commands.

---

## What to build

Please scaffold the full project. Here is the target structure:

```
sakila-dbt/
  .venv/                        ← Python virtual environment
  .vscode/
    mcp.json                    ← MCP server registrations
  .env                          ← secrets (never commit)
  dbt_project.yml
  profiles.yml
  packages.yml
  models/
    staging/                    ← stg_*.sql files live here
    marts/                      ← mart .sql files live here
  requirements.txt
  .gitignore
```

---

## Step 1 — Python environment

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install dbt-databricks python-dotenv
```

`requirements.txt` should contain:
```
dbt-databricks
python-dotenv
```

---

## Step 2 — dbt project files

### `dbt_project.yml`

```yaml
name: sakila_dbt
version: '1.0.0'
config-version: 2

profile: sakila

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]

target-path: "target"
clean-targets: ["target", "dbt_packages"]

models:
  sakila_dbt:
    staging:
      +materialized: view
    marts:
      +materialized: table
```

### `profiles.yml`

Place this in the project root (or `~/.dbt/profiles.yml`):

```yaml
sakila:
  target: dev
  outputs:
    dev:
      type: databricks
      host: "{{ env_var('DATABRICKS_HOST') }}"
      http_path: "{{ env_var('DATABRICKS_HTTP_PATH') }}"
      token: "{{ env_var('DATABRICKS_TOKEN') }}"
      catalog: hive_metastore        # or your Unity Catalog name
      schema: sakila_dev
      threads: 4
```

### `packages.yml`

```yaml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.0.0", "<2.0.0"]
```

### `.env`

```
DATABRICKS_HOST=<your-workspace>.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<warehouse-id>
DATABRICKS_TOKEN=<your-pat>
```

### `.gitignore`

```
.venv/
target/
dbt_packages/
logs/
.env
```

---

## Step 3 — MCP servers (no custom code needed)

Two official servers cover everything — no custom Python needed.

### 3a — File operations: `@modelcontextprotocol/server-filesystem`

Gives Copilot read/write access to the models folder.
Requires Node.js (`node --version` to check).

### 3b — dbt commands: official `dbt-mcp` by dbt Labs

[`dbt-mcp`](https://github.com/dbt-labs/dbt-mcp) is the official dbt MCP server.
It exposes `run`, `test`, `compile`, `build`, `parse`, `list`, and codegen tools
(`generate_staging_model`, `generate_model_yaml`).

Requires `uv` (fast Python package manager). Install once:
```bash
pip install uv
```

Then `uvx dbt-mcp` runs the server on demand — no manual install of dbt-mcp needed.

You can remove `mcp_server/` from the project structure. The `requirements.txt` only needs:
```
dbt-databricks
python-dotenv
```

---

## Step 4 — Register MCP servers in VS Code

Create `.vscode/mcp.json` in the sakila-dbt workspace:

```json
{
  "servers": {
    "sakila-dbt-files": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "${workspaceFolder}/models"
      ]
    },
    "dbt-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["dbt-mcp"],
      "env": {
        "DBT_PROJECT_DIR": "${workspaceFolder}",
        "DBT_PROFILES_DIR": "${workspaceFolder}"
      }
    }
  }
}
```

The `dbt-mcp` server provides these tools to Copilot:
- **CLI**: `run`, `test`, `compile`, `build`, `parse`, `list`
- **Codegen**: `generate_staging_model`, `generate_model_yaml`, `generate_source`
- **Lineage**: `get_lineage_dev`, `get_node_details_dev`

> Official VS Code setup guide: https://docs.getdbt.com/docs/dbt-ai/integrate-mcp-vscode

---

## Step 5 — Verify

After setup, confirm both MCP servers are active in VS Code (bottom status bar or Copilot chat panel → MCP servers).

Then ask Copilot in this workspace:
> "Use the dbt-mcp tool to parse the project and list all models"

It should parse cleanly (no models yet, but no errors). Once the migration agent syncs files across, try:
> "Compile all staging models and show any errors"

---

## How the migration agent pushes files

The `dbt-migration-agent` notebook writes generated `.sql` and `schema.yml` files
directly into this project's `models/` folder via the **filesystem MCP server**.
Copilot (in the migration agent workspace) uses the filesystem tools to create/overwrite files here.

Once files are synced, ask Copilot in **this** workspace to run dbt:

```
"Compile all dbt models and show me any errors"
"Run the staging layer"
"Run dbt test and show me the results"
"Show me the lineage for the film model"
```

Copilot will call the `dbt-mcp` tools (`compile`, `run`, `test`, `get_lineage_dev`) automatically.
