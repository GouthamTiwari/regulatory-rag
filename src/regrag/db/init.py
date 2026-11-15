"""Apply the database schema. Run with: uv run python -m regrag.db.init"""

from pathlib import Path

import psycopg

from regrag.db.connection import connect

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def apply_schema(conn: psycopg.Connection) -> None:
    """Run schema.sql on `conn`. Safe to call repeatedly (everything is IF NOT EXISTS)."""
    # psycopg runs a multi-statement script in one call when there are no parameters.
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


def main() -> None:
    # The vector extension may not exist yet, so don't register the vector type here.
    with connect(register_vector_type=False) as conn:
        apply_schema(conn)
        conn.commit()
    print("Schema applied.")


if __name__ == "__main__":
    main()
