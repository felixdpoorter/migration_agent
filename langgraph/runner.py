import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app import app


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    os.chdir(PROJECT_ROOT)
    load_dotenv()

    ddl_path = PROJECT_ROOT / "legacy_schema" / "ecommerce_legacy.sql"

    print(f"Inlezen van test DDL: {ddl_path}")

    if not ddl_path.exists():
        alternate_path = ddl_path.with_suffix(".ddl")
        if alternate_path.exists():
            ddl_path = alternate_path
        else:
            raise FileNotFoundError(
                f"Kon het bestand niet vinden op {ddl_path}. Controleer de bestandsnaam."
            )

    ddl_content = ddl_path.read_text(encoding="utf-8")
    print(f"Succesvol ingeladen ({len(ddl_content)} karakters).")

    initial_input = {
        "schema_name": "legacy_schema",
        "raw_sql": ddl_content,
        "execution_logs": [],
        "errors_encountered": [],
    }

    print("Starting LangGraph Agent met jouw eigen DDL bestand...")
    final_state = app.invoke(initial_input)

    print("\n================ FINAL EXECUTION LOGS ================")
    for log in final_state.get("execution_logs", []):
        print(f"  -> {log}")

    errors = final_state.get("errors_encountered", [])
    print(f"\nAantal fouten opgetreden tijdens de run: {len(errors)}")
    if errors:
        print(json.dumps(errors, indent=2))
    print("======================================================")


if __name__ == "__main__":
    main()