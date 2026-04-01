import os

import psycopg


def get_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/traffic",
    )


def connection_ctx():
    return psycopg.connect(get_dsn(), autocommit=True)
