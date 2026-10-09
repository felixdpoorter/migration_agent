import os
import json
from pathlib import Path
import re as _re
from typing import List, Dict, Any
from openai import OpenAI
import sqlglot
from sqlglot import expressions as exp
from langgraph.graph import StateGraph, START, END
from state import GraphBuilderState
from dotenv import load_dotenv
import re
from sqlglot.lineage import lineage as col_lineage
import networkx as nx



load_dotenv()
# =====================================================================
# 1. CONSTANTEN & CONFIGURATIE
# =====================================================================
# Pas deze constante bovenin aan als dat nog niet zo was:
OBJECT_TYPES = ["tables", "views", "stored_procedures", "triggers", "functions"]
TABLE_LAYER_VOCAB = ["Bronze", "Silver", "Gold"]

# =====================================================================
# 3. STAP 1: THE SQL CLASSIFIER NODE (Azure AI Foundry + OpenAI)
# =====================================================================
def sql_classifier_node(state: GraphBuilderState) -> Dict[str, Any]:
    print("STAP 1: Starten van de SQL Classifier via LLM...")
    
    raw_sql_input = state.get("raw_sql", "")
    if not raw_sql_input:
        print("WAARSCHUWING: Geen 'raw_sql' gevonden in de State!")
        return {"execution_logs": state.get("execution_logs", []) + ["Stap 1: Overgeslagen."]}

    try:
        ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        _api_key   = os.environ["AZURE_INFERENCE_CREDENTIAL"]
        RESOURCE_ROOT = _re.sub(r"/api/projects/.*$", "", ENDPOINT)

        local_client = OpenAI(
            api_key  = _api_key,
            base_url = f"{RESOURCE_ROOT}/openai/v1/",
        )

        _types_str  = ", ".join(f'"{t}"' for t in OBJECT_TYPES)
        _layers_str = ", ".join(f'"{l}"' for l in TABLE_LAYER_VOCAB)

        PROMPT_FILE = Path("skills/sql_classifier_prompt.md")
        SYSTEM_PROMPT = (PROMPT_FILE.read_text(encoding="utf-8")
            .replace("<<object_types>>", _types_str)
            .replace("<<layer_vocab>>",  _layers_str))

        response = local_client.chat.completions.create(
            model                 = DEPLOYMENT,
            messages              = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": raw_sql_input},
            ],
            max_completion_tokens = 16000,
            reasoning_effort      = "low",
            response_format       = {"type": "json_object"},
        )

        # Veilige verwerking van de response choices
        first_choice = response.choices[0]
        finish_reason = getattr(first_choice, "finish_reason", None)
        if finish_reason == "length":
            print("WAARSCHUWING: Response was truncated (finish_reason=length).")

        raw_content = first_choice.message.content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw_content)
        print(f"SUCCES: LLM succesvol uitgevoerd. Gevonden keys: {list(result.keys())}")

        # Unpack in afzonderlijke datastructuren
        SQL_INPUT = {
            "dialect": "mysql",  # Default dialect op basis van jouw notebook
            **{k: result.get(k, []) for k in OBJECT_TYPES},
        }
        TABLE_LAYERS = result.get("table_layers", {})

        # Validatie (Fail-Fast)
        missing_keys   = [k for k in OBJECT_TYPES if k not in result]
        unknown_layers = {v for v in TABLE_LAYERS.values() if v not in TABLE_LAYER_VOCAB}
        assert not missing_keys,   f"LLM output missing required keys: {missing_keys}"
        assert not unknown_layers, f"LLM used unknown layer values: {unknown_layers}"

        print("SQL_INPUT buckets:")
        for k in OBJECT_TYPES:
            print(f"  {k:20s}: {len(SQL_INPUT[k])} statement(s)")
        print("\nTABLE_LAYERS:")
        for name, layer in TABLE_LAYERS.items():
            print(f"  {name:30s} → {layer}")

        return {
            "classified_metadata": result,
            "sql_input": SQL_INPUT,
            "table_layers": TABLE_LAYERS,
            "execution_logs": state.get("execution_logs", []) + ["Stap 1: SQL geclassificeerd en gevalideerd."]
        }

    except Exception as e:
        print(f"FOUT: Fout opgetreden in Stap 1: {str(e)}")
        return {
            "errors_encountered": state.get("errors_encountered", []) + [{"step": "sql_classifier_node", "error": str(e)}],
            "execution_logs": state.get("execution_logs", []) + ["Stap 1: Gefaald wegens uitzondering."]
        }

# =====================================================================
# 4. STAP 2: THE SQLGLOT PARSER NODE (Deterministisch uit je Notebook)
# =====================================================================
def table_column_parser_node(state: GraphBuilderState) -> Dict[str, Any]:
    print("\nSTAP 2: Starten van de sqlglot AST Parser...")
    
    sql_input = state.get("sql_input", {})
    dialect = sql_input.get("dialect", "mysql")
    table_statements = sql_input.get("tables", [])
    
    if not table_statements:
        print("WAARSCHUWING: Geen tabel-statements gevonden om te parsen.")
        return {"execution_logs": state.get("execution_logs", []) + ["Stap 2: Overgeslagen (geen tabellen)."]}
        
    parsed_tables = {}
    foreign_keys = []

    try:
        # 1. Parse tabellen, kolommen, datatypes en nullability
        for sql in table_statements:
            statements = sqlglot.parse(sql, dialect=dialect)
            if not statements:
                continue
            stmt = statements[0]
            table_name = stmt.this.this.name

            columns = []
            for col_def in stmt.find_all(exp.ColumnDef):
                dtype = col_def.args.get("kind")
                nullable = not any(
                    isinstance(c.args.get("this"), exp.NotNullColumnConstraint)
                    for c in col_def.args.get("constraints", [])
                )
                columns.append({
                    "name":     col_def.name,
                    "type":     dtype.sql(dialect=dialect) if dtype else "UNKNOWN",
                    "nullable": nullable,
                })

            parsed_tables[table_name] = {"columns": columns}

        # 2. Parse Foreign Key relaties
        for sql in table_statements:
            statements = sqlglot.parse(sql, dialect=dialect)
            if not statements:
                continue
            stmt = statements[0]
            from_table = stmt.this.this.name

            for fk in stmt.find_all(exp.ForeignKey):
                from_col = fk.expressions[0].name
                ref = fk.args["reference"]
                
                if isinstance(ref.this, exp.Schema):
                    to_table = ref.this.this.name
                    to_col   = ref.this.expressions[0].name if ref.this.expressions else None
                else:
                    to_table = ref.this.name
                    to_col   = None

                foreign_keys.append({
                    "from_table": from_table,
                    "from_col":   from_col,
                    "to_table":   to_table,
                    "to_col":     to_col,
                })

        # 3. Print samenvatting in de terminal
        print("Geparseerde tabellen overzicht:")
        for table, meta in parsed_tables.items():
            print(f"  Table: {table} ({len(meta['columns'])} kolommen)")
            
        print(f"\nGevonden Foreign Keys: {len(foreign_keys)}")
        for fk in foreign_keys:
            to = f"{fk['to_table']}.{fk['to_col']}" if fk["to_col"] else fk["to_table"]
            print(f"  {fk['from_table']}.{fk['from_col']}  →  {to}")

        return {
            "parsed_tables": parsed_tables,
            "foreign_keys": foreign_keys,
            "execution_logs": state.get("execution_logs", []) + ["Stap 2: SQL succesvol geparseerd via sqlglot AST."]
        }

    except Exception as e:
        print(f"FOUT: Fout opgetreden in Stap 2: {str(e)}")
        return {
            "errors_encountered": state.get("errors_encountered", []) + [{"step": "sqlglot_parser_node", "error": str(e)}],
            "execution_logs": state.get("execution_logs", []) + ["Stap 2: Gefaald wegens parser uitzondering."]
        }




# Constante buiten de functie voor betere leesbaarheid
_SQL_KEYWORDS = {
    "EACH", "ROW", "BEGIN", "END", "SELECT", "INSERT",
    "UPDATE", "DELETE", "NULL", "SET", "VALUES",
}

def _proc_name_from_sql(sql):
    """Regex fallback to extract procedure/trigger/function name from raw SQL."""
    m = re.search(r"CREATE\s+(?:TRIGGER|PROCEDURE|FUNCTION)\s+(\w+)", sql, re.IGNORECASE)
    return m.group(1) if m else "unknown"

def routines_views_parser_node(state: GraphBuilderState) -> Dict[str, Any]:
    print("\nSTAP 3: Starten van de Lineage Parser (Procedures, Triggers, Functions & Views)...")
    
    sql_input = state.get("sql_input", {})
    dialect = sql_input.get("dialect", "mysql")
    
    proc_statements = sql_input.get("stored_procedures", [])
    trigger_statements = sql_input.get("triggers", [])
    func_statements = sql_input.get("functions", [])
    view_statements = sql_input.get("views", []) # NIEUW
    
    parsed_procs = {}
    parsed_triggers = {}
    parsed_functions = {}
    parsed_views = {} # NIEUW

    try:
        # ── 1. PARSE STORED PROCEDURES ─────────────────────────────────────────
        for sql in proc_statements:
            statements = sqlglot.parse(sql, dialect=dialect)
            stmt = statements[0] if statements else None

            proc_name = _proc_name_from_sql(sql)
            if (not proc_name or proc_name == "unknown") and stmt:
                proc_name = (stmt.this.name if not isinstance(stmt, exp.Command) and stmt.this else "unknown")

            read_hits  = re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
            write_hits = re.findall(r"\b(?:INTO|UPDATE)\s+(\w+)", sql, re.IGNORECASE)
            trunc_hits = re.findall(r"\bTRUNCATE\s+(?:TABLE\s+)?(\w+)", sql, re.IGNORECASE)

            reads  = {t for t in read_hits if t.upper() not in _SQL_KEYWORDS} - {proc_name}
            writes = {t for t in write_hits + trunc_hits if t.upper() not in _SQL_KEYWORDS} - {proc_name}

            parsed_procs[proc_name] = {
                "reads_from": sorted(list(reads)),
                "writes_to":  sorted(list(writes)),
            }

        # ── 2. PARSE TRIGGERS ──────────────────────────────────────────────────
        for sql in trigger_statements:
            name = _proc_name_from_sql(sql)

            m = re.search(r"(BEFORE|AFTER)\s+(INSERT|UPDATE|DELETE)\s+ON\s+(\w+)", sql, re.IGNORECASE)
            timing   = m.group(1).upper() if m else None
            event    = m.group(2).upper() if m else None
            on_table = m.group(3)         if m else None

            read_hits  = re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
            write_hits = re.findall(r"\b(?:INTO|UPDATE)\s+(\w+)", sql, re.IGNORECASE)
            reads  = {t for t in read_hits if t.upper() not in _SQL_KEYWORDS and t != on_table}
            writes = {t for t in write_hits if t.upper() not in _SQL_KEYWORDS and t != on_table}

            parsed_triggers[name] = {
                "timing":     timing,
                "event":      event,
                "on_table":   on_table,
                "reads_from": sorted(list(reads)),
                "writes_to":  sorted(list(writes)),
            }

        # ── 3. PARSE FUNCTIONS ─────────────────────────────────────────────────
        for sql in func_statements:
            statements = sqlglot.parse(sql, dialect=dialect)
            stmt = statements[0] if statements else None

            if isinstance(stmt, exp.Command) or not stmt:
                func_name   = _proc_name_from_sql(sql)
                ret_m       = re.search(r"\bRETURNS\s+([\w()]+)", sql, re.IGNORECASE)
                return_type = ret_m.group(1) if ret_m else "UNKNOWN"
                read_hits   = re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
                write_hits  = re.findall(r"\b(?:INTO|UPDATE)\s+(\w+)", sql, re.IGNORECASE)
                reads  = {t for t in read_hits if t.upper() not in _SQL_KEYWORDS}
                writes = {t for t in write_hits if t.upper() not in _SQL_KEYWORDS}
            else:
                func_name   = (stmt.this.name if stmt.this else "") or _proc_name_from_sql(sql)
                returns     = stmt.args.get("returns")
                return_type = returns.sql(dialect=dialect) if returns else "UNKNOWN"
                reads  = {tbl.name for tbl in stmt.find_all(exp.Table) if tbl.name and tbl.name != func_name}
                writes = set()

            parsed_functions[func_name] = {
                "return_type": return_type,
                "reads_from":  sorted(list(reads)),
                "writes_to":   sorted(list(writes)),
            }

        # ── 4. PARSE VIEWS (Jouw notebook code) ─────────────────────────────────
        for sql in view_statements:
            statements = sqlglot.parse(sql, dialect=dialect)
            if not statements:
                continue
            stmt = statements[0]
            view_name = stmt.this.name

            referenced = set()
            for tbl in stmt.find_all(exp.Table):
                name = tbl.name
                if name and name != view_name:
                    referenced.add(name)

            parsed_views[view_name] = {"reads_from": sorted(list(referenced))}

        # ── 5. SAMENVATTING PRINTEN IN TERMINAL ────────────────────────────────
        print(f"Geparseerde Stored Procedures: {len(parsed_procs)}")
        for proc, meta in parsed_procs.items():
            print(f"  Procedure: {proc} (Reads: {len(meta['reads_from'])}, Writes: {len(meta['writes_to'])})")

        print(f"\nGeparseerde Triggers: {len(parsed_triggers)}")
        for name, meta in parsed_triggers.items():
            print(f"  Trigger: {name} [{meta['timing']} {meta['event']} ON {meta['on_table']}]")

        print(f"\nGeparseerde Functies: {len(parsed_functions)}")
        for name, meta in parsed_functions.items():
            print(f"  Function: {name} → returns {meta['return_type']}")

        print(f"\nGeparseerde Views: {len(parsed_views)}")
        for view, meta in parsed_views.items():
            print(f"  View: {view}")
            for dep in meta["reads_from"]:
                print(f"    reads_from → {dep}")

        return {
            "parsed_stored_procedures": parsed_procs,
            "parsed_triggers": parsed_triggers,
            "parsed_functions": parsed_functions,
            "parsed_views": parsed_views,
            "execution_logs": state.get("execution_logs", []) + ["Stap 3: Procedures, triggers, functies en views succesvol geparseerd."]
        }

    except Exception as e:
        print(f"FOUT: Fout opgetreden in Stap 3: {str(e)}")
        return {
            "errors_encountered": state.get("errors_encountered", []) + [{"step": "lineage_parser_node", "error": str(e)}],
            "execution_logs": state.get("execution_logs", []) + ["Stap 3: Gefaald wegens parser uitzondering."]
        }

from sqlglot.lineage import lineage as col_lineage

def networkx_graph_node(state: GraphBuilderState) -> Dict[str, Any]:
    print("\nSTAP 4: Samenstellen en verrijken van de NetworkX Knowledge Graph...")
    
    # 1. Metadata ophalen uit de State
    table_layers = state.get("table_layers", {})
    parsed_tables = state.get("parsed_tables", {})
    parsed_views = state.get("parsed_views", {})
    parsed_procs = state.get("parsed_stored_procedures", {})
    parsed_triggers = state.get("parsed_triggers", {})
    parsed_functions = state.get("parsed_functions", {})
    foreign_keys = state.get("foreign_keys", [])
    sql_input = state.get("sql_input", {})
    dialect = sql_input.get("dialect", "mysql")
    
    LAYER_NODE_TYPE = {
        "Bronze": "bronze_table",
        "Silver": "silver_table",
        "Gold": "gold_table",
        "source": "source_table"
    }

    G = nx.DiGraph()

    # ── OBJECT-LEVEL NODES TOEVOEGEN ─────────────────────────────────────
    for table_name, meta in parsed_tables.items():
        layer = table_layers.get(table_name, "source")
        node_type = LAYER_NODE_TYPE.get(layer, "table")
        G.add_node(table_name, node_type=node_type, columns=meta["columns"])

    for view_name, meta in parsed_views.items():
        G.add_node(view_name, node_type="view", reads_from=meta["reads_from"])

    for proc_name, meta in parsed_procs.items():
        G.add_node(proc_name, node_type="procedure", reads_from=meta["reads_from"], writes_to=meta["writes_to"])

    for trig_name, meta in parsed_triggers.items():
        G.add_node(trig_name, node_type="trigger", timing=meta["timing"], event=meta["event"], on_table=meta["on_table"], reads_from=meta["reads_from"], writes_to=meta["writes_to"])

    for func_name, meta in parsed_functions.items():
        G.add_node(func_name, node_type="function", return_type=meta["return_type"], reads_from=meta["reads_from"], writes_to=meta["writes_to"])

    # ── BASIS KOLOM-LEVEL NODES EN EDGES TOEVOEGEN ───────────────────────
    for table_name, meta in parsed_tables.items():
        for col in meta["columns"]:
            col_node = f"{table_name}.{col['name']}"
            G.add_node(col_node, node_type="column", table=table_name,
                       col_name=col["name"], col_type=col["type"], nullable=col["nullable"])
            G.add_edge(table_name, col_node, edge_type="has_column")

    # ── ENRICH COLUMN CONSTRAINTS & PKs ──────────────────────────────────
    for sql in sql_input.get("tables", []):
        statements = sqlglot.parse(sql, dialect=dialect)
        if not statements:
            continue
        stmt = statements[0] if isinstance(statements, list) else statements
        
        if not hasattr(stmt, "this") or not stmt.this:
            continue
        table_name = stmt.this.this.name

        pk_cols = set()
        for pk in stmt.find_all(exp.PrimaryKey):
            for col in pk.expressions:
                pk_cols.add(col.name)

        col_constraints = {}
        for col_def in stmt.find_all(exp.ColumnDef):
            info = {"auto_increment": False, "default": None, "is_unique": False}
            for constraint in col_def.args.get("constraints", []):
                c = constraint.args.get("this")
                if isinstance(c, exp.AutoIncrementColumnConstraint):
                    info["auto_increment"] = True
                elif isinstance(c, exp.DefaultColumnConstraint):
                    info["default"] = c.this.sql(dialect=dialect) if c.this else None
                elif isinstance(c, exp.UniqueColumnConstraint):
                    info["is_unique"] = True
            col_constraints[col_def.name] = info

        if table_name in parsed_tables:
            for col in parsed_tables[table_name]["columns"]:
                col_name = col["name"]
                node_id = f"{table_name}.{col_name}"
                extra = col_constraints.get(col_name, {})

                if node_id in G:
                    G.nodes[node_id]["is_pk"]          = col_name in pk_cols
                    G.nodes[node_id]["auto_increment"] = extra.get("auto_increment", False)
                    G.nodes[node_id]["default"]        = extra.get("default")
                    G.nodes[node_id]["is_unique"]      = extra.get("is_unique", False) or col_name in pk_cols

    # ── ENUM & SET ACCEPTED VALUES ───────────────────────────────────────
    for sql in sql_input.get("tables", []):
        statements = sqlglot.parse(sql, dialect=dialect)
        if not statements:
            continue
        stmt = statements[0] if isinstance(statements, list) else statements
        
        if not hasattr(stmt, "this") or not stmt.this:
            continue
        table_name = stmt.this.this.name

        for col_def in stmt.find_all(exp.ColumnDef):
            dtype = col_def.args.get("kind")
            if not dtype:
                continue

            node_id = f"{table_name}.{col_def.name}"
            if node_id not in G:
                continue

            type_name = dtype.this.value if hasattr(dtype.this, "value") else str(dtype.this)
            if type_name.upper() in ("ENUM", "SET"):
                accepted = [lit.name for lit in dtype.expressions if isinstance(lit, exp.Literal)]
                G.nodes[node_id]["accepted_values"] = accepted
                G.nodes[node_id]["mysql_type"]      = type_name.upper()

    # ── OBJECT & KOLOM LEVEL REFERENCES EDGES ────────────────────────────
    for fk in foreign_keys:
        G.add_edge(fk["from_table"], fk["to_table"], edge_type="references", from_col=fk["from_col"], to_col=fk["to_col"])
        
        if fk["to_col"]:
            src_col_node = f"{fk['from_table']}.{fk['from_col']}"
            dst_col_node = f"{fk['to_table']}.{fk['to_col']}"
            if src_col_node in G and dst_col_node in G:
                G.add_edge(src_col_node, dst_col_node, edge_type="references")

    # ── OBJECT-LEVEL LOGIC EDGES TOEVOEGEN ───────────────────────────────
    for view_name, meta in parsed_views.items():
        for tbl in meta["reads_from"]:
            G.add_edge(view_name, tbl, edge_type="reads_from")

    for proc_name, meta in parsed_procs.items():
        for tbl in meta["reads_from"]:
            G.add_edge(proc_name, tbl, edge_type="reads_from")
        for tbl in meta["writes_to"]:
            G.add_edge(proc_name, tbl, edge_type="writes_to")

    for trig_name, meta in parsed_triggers.items():
        if meta["on_table"]:
            G.add_edge(trig_name, meta["on_table"], edge_type="fires_on")
        for tbl in meta["reads_from"]:
            G.add_edge(trig_name, tbl, edge_type="reads_from")
        for tbl in meta["writes_to"]:
            G.add_edge(trig_name, tbl, edge_type="writes_to")

    for func_name, meta in parsed_functions.items():
        for tbl in meta["reads_from"]:
            G.add_edge(func_name, tbl, edge_type="reads_from")
        for tbl in meta["writes_to"]:
            G.add_edge(func_name, tbl, edge_type="writes_to")

    # ── VIEW COLUMN LINEAGE (DERIVED_FROM) VIA SQLGLOT TRACE ─────────────
    column_lineage = []
    for sql in sql_input.get("views", []):
        statements = sqlglot.parse(sql, dialect=dialect)
        if not statements:
            continue
        stmt = statements[0] if isinstance(statements, list) else statements
        view_name = stmt.this.name
        select_expr = stmt.expression

        for col_expr in select_expr.expressions:
            out_col = col_expr.alias_or_name
            if not out_col:
                continue
            
            try:
                root = col_lineage(column=out_col, sql=select_expr, dialect=dialect)
                for node in root.walk():
                    if node.downstream:
                        continue
                    src_table = node.source.name if isinstance(node.source, exp.Table) else node.source_name
                    src_col = node.name.split(".")[-1]
                    if src_table and src_table != view_name:
                        column_lineage.append({
                            "from_col":  f"{view_name}.{out_col}",
                            "to_col":    f"{src_table}.{src_col}",
                            "view":      view_name,
                            "out_col":   out_col,
                            "src_table": src_table,
                            "src_col":   src_col,
                        })
            except Exception as inner_e:
                print(f"  Could not trace {view_name}.{out_col}: {inner_e}")

    # Gecorrigeerde verwerking van de lineages en toevoeging van edges
    for entry in column_lineage:
        from_node, to_node = entry["from_col"], entry["to_col"]
        if from_node not in G: 
            G.add_node(from_node, node_type="column", table=entry["view"], col_name=entry["out_col"])
        if to_node not in G: 
            G.add_node(to_node, node_type="column", table=entry["src_table"], col_name=entry["src_col"])
        if entry["view"] in G: 
            G.add_edge(entry["view"], from_node, edge_type="has_column")
        if entry["src_table"] in G: 
            G.add_edge(entry["src_table"], to_node, edge_type="has_column")
        G.add_edge(from_node, to_node, edge_type="derived_from")

    # Auto-created nodes taggen
    for node, attrs in G.nodes(data=True):
        if "node_type" not in attrs:
            G.nodes[node]["node_type"] = "referenced"

    # TERMINAL LOGS PRINTEN
    print(f"Nodes samengesteld : {G.number_of_nodes()}")

    # FINALE RETURN: Sla het NetworkX object op in de State
    return {
        "knowledge_graph": G,
        "execution_logs": state.get("execution_logs", []) + ["Stap 4: NetworkX Graph succesvol opgebouwd en verrijkt."]
    }



from collections import defaultdict
from pathlib import Path
from neo4j import GraphDatabase

def neo4j_export_node(state: GraphBuilderState) -> Dict[str, Any]:
    print("\nSTAP 5: Exporteren van de Knowledge Graph naar Neo4j...")
    
    # Haal de NetworkX graaf op uit de State
    G = state.get("knowledge_graph")
    if G is None:
        print("FOUT: Geen 'knowledge_graph' gevonden in de State!")
        return {"execution_logs": state.get("execution_logs", []) + ["Stap 5: Overgeslagen (geen graaf)."]}

    # Mappings van NetworkX naar Neo4j (overeenkomstig met jouw contract)
    NODE_LABEL = {
        "source_table": "SOURCE_TABLE",
        "silver_table": "SILVER_TABLE",
        "gold_table":   "GOLD_TABLE",
        "view":         "VIEW",
        "procedure":    "PROCEDURE",
        "trigger":      "TRIGGER",
        "function":     "FUNCTION",
        "column":       "COLUMN",
        "referenced":   "REFERENCED",
    }

    REL_TYPE = {
        "references":   "REFERENCES",
        "reads_from":   "READS_FROM",
        "writes_to":    "WRITES_TO",
        "fires_on":     "FIRES_ON",
        "derived_from": "DERIVED_FROM",
        "has_column":   "HAS_COLUMN",
    }

    # Haal database credentials op uit de omgevingsvariabelen
    NEO4J_URI      = "bolt://127.0.0.1:7687"
    NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    
    if not NEO4J_PASSWORD:
        raise ValueError("NEO4J_PASSWORD niet ingesteld in je .env bestand!")

    try:
        # Initialiseer de officiële Neo4j driver
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print(f"Succesvol verbonden met Neo4j op {NEO4J_URI}")

        # ── 1. FULL RESET: DROP CONSTRAINTS & DETACH DELETE ─────────────────
        with driver.session() as session:
            old_constraints = [r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name")]
            for name in old_constraints:
                session.run(f"DROP CONSTRAINT `{name}` IF EXISTS")

            session.run("MATCH (n) DETACH DELETE n")

            for label in NODE_LABEL.values():
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.node_id IS UNIQUE")

        print(f"  Opruimen gereed: {len(old_constraints)} oude constraints gedropt, data gewist.")
        print(f"  Nieuwe unieke constraints aangemaakt voor {len(set(NODE_LABEL.values()))} labels.")

        # ── 2. BATCH-WRITE NODES (UNWIND) ───────────────────────────────────
        node_batches = defaultdict(list)
        for node_id, attrs in G.nodes(data=True):
            label = NODE_LABEL.get(attrs.get("node_type", ""), "NODE")
            props = {"node_id": node_id}
            for k, v in attrs.items():
                props[k] = json.dumps(v) if isinstance(v, (list, dict)) else v
            node_batches[label].append(props)

        print("\n  Nodes wegschrijven in bulk...")
        with driver.session() as session:
            for label, rows in node_batches.items():
                session.run(
                    f"UNWIND $rows AS row MERGE (n:{label} {{node_id: row.node_id}}) SET n += row",
                    rows=rows
                )
                print(f"    {label:14s}: {len(rows)} nodes geladen.")

        # ── 3. BATCH-WRITE EDGES (UNWIND) ───────────────────────────────────
        edge_batches = defaultdict(list)
        for src, dst, attrs in G.edges(data=True):
            rel_type = REL_TYPE.get(attrs.get("edge_type", ""), "RELATED")
            props = {k: v for k, v in attrs.items() if v is not None}
            edge_batches[rel_type].append({"src": src, "dst": dst, "props": props})

        print("\n  Relaties wegschrijven in bulk...")
        with driver.session() as session:
            for rel_type, rows in edge_batches.items():
                session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (a {{node_id: row.src}}), (b {{node_id: row.dst}}) "
                    f"CREATE (a)-[r:{rel_type}]->(b) SET r += row.props",
                    rows=rows
                )
                print(f"    {rel_type:16s}: {len(rows)} relaties gelegd.")

        # ── 4. PATCH: HAS_COLUMN SAFETY NET QUERY ───────────────────────────
        with driver.session() as session:
            result = session.run(
                "MATCH (t), (c:COLUMN) "
                "WHERE (t:SOURCE_TABLE OR t:SILVER_TABLE OR t:GOLD_TABLE OR t:VIEW) AND c.table = t.node_id "
                "MERGE (t)-[r:HAS_COLUMN]->(c) "
                "RETURN count(r) AS created"
            )
            print(f"\n  HAS_COLUMN patch check: {result.single()['created']} relaties geverifieerd.")

        # ── 5. BACKUP: LIGHTWEIGHT NETWORKX JSON OVERZICHT ───────────────────
        OUTPUT_DIR = Path("knowledge_graph")
        OUTPUT_DIR.mkdir(exist_ok=True)
        nx_data = nx.node_link_data(G)
        with open(OUTPUT_DIR / "kg_graph.json", "w") as f:
            json.dump(nx_data, f, default=str)
        print(f"  Backup gereed: NetworkX JSON opgeslagen in {OUTPUT_DIR / 'kg_graph.json'}")

        # ── 6. GRAPH VALIDATION LOGS ─────────────────────────────────────────
        hc_edges = [ (u, v) for u, v, d in G.edges(data=True) if d.get('edge_type') == 'has_column' ]
        col_nodes_all = [ n for n, d in G.nodes(data=True) if d.get('node_type') == 'column' ]
        col_with_parent = { v for _, v, d in G.edges(data=True) if d.get('edge_type') == 'has_column' }
        orphans = [ n for n in col_nodes_all if n not in col_with_parent ]
        
        print(f"\n  Validatie overzicht lokaal object:")
        print(f"    HAS_COLUMN edges in G : {len(hc_edges)}")
        print(f"    Kolom-nodes totaal    : {len(col_nodes_all)}")
        print(f"    Wees-kolommen (orphans): {orphans}")

        # Sluit de driver netjes af
        driver.close()

        return {
            "execution_logs": state.get("execution_logs", []) + ["Stap 5: Complete Knowledge Graph succesvol live geëxporteerd naar Neo4j."]
        }

    except Exception as e:
        print(f"FOUT: Fout opgetreden in Stap 5: {str(e)}")
        return {
            "errors_encountered": state.get("errors_encountered", []) + [{"step": "neo4j_export_node", "error": str(e)}],
            "execution_logs": state.get("execution_logs", []) + ["Stap 5: Gefaald wegens Neo4j export uitzondering."]
        }

def graph_quality_audit_node(state: GraphBuilderState) -> Dict[str, Any]:
    print("\nSTAP 6: Starten van de Uitgebreide Graph Quality & Integrity Audit...")
    
    NEO4J_URI      = "bolt://127.0.0.1:7687"
    NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    
    report = {
        "orphan_columns": [],
        "disconnected_routines": [],
        "stale_references": [],
        "unmapped_layers": [],
        "multiple_writers": [],      
        "cyclic_dependencies": [],  
        "stale_views": [],          
        "datatype_mismatches": [],  
        "unused_sources": []        
    }
    
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        
        with driver.session() as session:
            # 1. Wees-kolommen
            q1 = "MATCH (c:COLUMN) WHERE NOT ()-[:HAS_COLUMN]->(c) RETURN c.node_id AS id"
            report["orphan_columns"] = [r["id"] for r in session.run(q1)]
            
            # 2. Dode routines
            q2 = """
            MATCH (r) 
            WHERE (r:PROCEDURE OR r:FUNCTION) 
              AND NOT (r)-[:READS_FROM]->() 
              AND NOT (r)-[:WRITES_TO]->() 
            RETURN r.node_id AS id
            """
            report["disconnected_routines"] = [r["id"] for r in session.run(q2)]
            
            # 3. Missende FK Doeltabellen
            q3 = "MATCH (a)-[:REFERENCES]->(b:REFERENCED) RETURN DISTINCT b.node_id AS id"
            report["stale_references"] = [r["id"] for r in session.run(q3)]
            
            # 4. Niet-gemapte dbt-lagen
            q4 = "MATCH (n:table) RETURN n.node_id AS id"
            report["unmapped_layers"] = [r["id"] for r in session.run(q4)]
            
            # 5. Meerdere schrijvers (Gevaarlijk voor dbt)
            q5 = """
            MATCH (p:PROCEDURE)-[:WRITES_TO]->(t)
            WITH t, count(p) AS writers, collect(p.node_id) AS procs
            WHERE writers > 1
            RETURN t.node_id AS target, procs
            """
            report["multiple_writers"] = [{"target": r["target"], "procedures": r["procs"]} for r in session.run(q5)]
            
            # 6. Circulaire Afhankelijkheden (Oneindige lussen)
            q6 = """
            MATCH (a)-[:READS_FROM|WRITES_TO|REFERENCES*2..5]->(a)
            RETURN DISTINCT a.node_id AS id
            """
            report["cyclic_dependencies"] = [r["id"] for r in session.run(q6)]
            
            # 7. Gebroken / Stale Views
            q7 = "MATCH (v:VIEW)-[:READS_FROM]->(t:REFERENCED) RETURN DISTINCT v.node_id AS id"
            report["stale_views"] = [r["id"] for r in session.run(q7)]
            
            # 8. Datatype Mismatch op Foreign Keys
            q8 = """
            MATCH (c1:COLUMN)-[r:REFERENCES]->(c2:COLUMN)
            WHERE c1.col_type <> c2.col_type
            RETURN c1.node_id AS from_col, c1.col_type AS from_type, c2.node_id AS to_col, c2.col_type AS to_type
            """
            report["datatype_mismatches"] = [
                {
                    "from": f"{r['from_col']} ({r['from_type']})", 
                    "to": f"{r['to_col']} ({r['to_type']})"
                } for r in session.run(q8)
            ]
            
            # 9. Ongebruikte brontabellen (Dode tabellen)
            q9 = """
            MATCH (t:SOURCE_TABLE)
            WHERE NOT ()-[:READS_FROM]->(t)
            RETURN t.node_id AS id
            """
            report["unused_sources"] = [r["id"] for r in session.run(q9)]

        driver.close()

        # Print het uitgebreide rapport overzichtelijk in de terminal
        print("=================== NEO4J GRAPH AUDIT REPORT ===================")
        print(f"  Wees-kolommen gevonden          : {len(report['orphan_columns'])}")
        print(f"  Dode routines (SP/Func)         : {len(report['disconnected_routines'])}")
        print(f"  Missende FK Doeltabellen (Stale): {len(report['stale_references'])}")
        print(f"  Niet-gemapte dbt-lagen          : {len(report['unmapped_layers'])}")
        print(f"  Tabellen met MULTIPLE WRITERS   : {len(report['multiple_writers'])}")
        print(f"  Circulaire lussen (CYCLIC)     : {len(report['cyclic_dependencies'])}")
        print(f"  Gebroken Views (STALE)          : {len(report['stale_views'])}")
        print(f"  Datatype Join Mismatches        : {len(report['datatype_mismatches'])}")
        print(f"  Ongebruikte legacy bron-tabellen: {len(report['unused_sources'])}")
        print("================================================================")

        # Log details als er kritieke dbt blokkades zijn gevonden
        if report["multiple_writers"] or report["cyclic_dependencies"]:
            print("\nKRITIEKE DBT BLOKKADES GEVONDEN:")
            for item in report["multiple_writers"]:
                print(f"  → Tabel '{item['target']}' wordt door meerdere SPs gevuld: {item['procedures']}")
            for cycle_id in report["cyclic_dependencies"]:
                print(f"  → Circulaire lus ontdekt bij object: {cycle_id}")
            print("================================================================")

        return {
            "graph_audit_report": report,
            "execution_logs": state.get("execution_logs", []) + ["Stap 6: Uitgebreide Kwaliteits- en dbt-compatibiliteitsaudit afgerond."]
        }

    except Exception as e:
        print(f"FOUT: Fout opgetreden tijdens de Graph Audit: {str(e)}")
        return {
            "errors_encountered": state.get("errors_encountered", []) + [{"step": "graph_quality_audit_node", "error": str(e)}],
            "execution_logs": state.get("execution_logs", []) + ["Stap 6: Audit gefaald wegens uitzondering."]
        }


# =====================================================================
# 5. BOUW EN COMPILEER DE LANGGRAPH WORKFLOW
# =====================================================================

workflow = StateGraph(GraphBuilderState)

# 1. Registreer de nodes (Zorg dat deze namen EXACT zo staan)
workflow.add_node("classify_sql", sql_classifier_node)
workflow.add_node("parse_sqlglot", table_column_parser_node)
workflow.add_node("parse_routines_and_views", routines_views_parser_node) 
workflow.add_node("build_networkx", networkx_graph_node)
workflow.add_node("export_neo4j", neo4j_export_node) 
workflow.add_node("audit_graph", graph_quality_audit_node) 



# 2. Knoop de pijplijn aan elkaar met exact dezelfde namen
workflow.add_edge(START, "classify_sql")
workflow.add_edge("classify_sql", "parse_sqlglot")
workflow.add_edge("parse_sqlglot", "parse_routines_and_views") 
workflow.add_edge("parse_routines_and_views", "build_networkx") 
workflow.add_edge("build_networkx", "export_neo4j") # 
workflow.add_edge("export_neo4j", "audit_graph") 
workflow.add_edge("audit_graph", END)            
app = workflow.compile()
