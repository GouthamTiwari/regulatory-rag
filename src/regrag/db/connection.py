"""Opening connections to the local Postgres + pgvector database."""

import re

import psycopg
from pgvector.psycopg import register_vector

from regrag.config import Settings, get_settings

# Schema names go into a connection option, which can't use query parameters, so they are
# restricted to plain lowercase identifiers. This rules out SQL injection through the name.
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def connect(
    settings: Settings | None = None,
    *,
    schema: str | None = None,
    register_vector_type: bool = True,
    autocommit: bool = False,
) -> psycopg.Connection:
    """Open a connection, optionally scoped to `schema` (used by tests).

    `register_vector_type` teaches psycopg to send and receive pgvector values. It needs
    the vector extension to exist already, so the schema initialiser turns it off.
    """
    settings = settings or get_settings()
    options = ""
    if schema is not None:
        if not _SCHEMA_NAME.match(schema):
            raise ValueError(f"invalid schema name: {schema!r}")
        # "public" stays on the path because that's where the vector type lives.
        options = f"-c search_path={schema},public"
    try:
        conn = psycopg.connect(
            settings.database_dsn(),
            autocommit=autocommit,
            connect_timeout=5,
            options=options,
            # TCP keepalives: during a long embedding run the connection sits idle for many
            # minutes, and Docker Desktop's port forwarding drops idle connections (task 33).
            keepalives=1,
            keepalives_idle=60,
            keepalives_interval=10,
            keepalives_count=5,
        )
    except psycopg.OperationalError as exc:
        # Why not re-raise as is: psycopg's message can include connection details. This
        # message names only host and port, never the password.
        raise RuntimeError(
            f"Cannot reach Postgres on localhost:{settings.postgres_port}. "
            "Is Docker Desktop running? Try: docker compose up -d"
        ) from exc
    if register_vector_type:
        register_vector(conn)
    return conn
