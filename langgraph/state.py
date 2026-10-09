from typing import Any, Dict, List, TypedDict

import networkx as nx


class GraphBuilderState(TypedDict, total=False):
    # Input
    schema_name: str
    raw_sql: str

    # Data van Stap 1
    classified_metadata: Dict[str, Any]
    sql_input: Dict[str, Any]
    table_layers: Dict[str, str]

    # Data van Stap 2 en 3
    parsed_tables: Dict[str, Any]
    foreign_keys: List[Dict[str, Any]]
    parsed_stored_procedures: Dict[str, Any]
    parsed_triggers: Dict[str, Any]
    parsed_functions: Dict[str, Any]
    parsed_views: Dict[str, Any]

    # Data van Stap 4 (NetworkX)
    knowledge_graph: nx.DiGraph

    # Audit & Quality Metrics
    graph_audit_report: Dict[str, Any]

    # Status & Logging
    execution_logs: List[str]
    errors_encountered: List[Dict[str, Any]]