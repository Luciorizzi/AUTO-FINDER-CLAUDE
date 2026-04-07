"""Tests de inicializacion y operaciones de base de datos."""

import sqlite3

from app.storage.database import get_tables, table_exists
from app.storage.repositories import (
    count_listings,
    create_run_log,
    finish_run_log,
    get_run_log,
)

EXPECTED_TABLES = ["listing_snapshots", "listings", "opportunity_alerts", "run_logs"]


def test_tables_created(db_conn: sqlite3.Connection):
    tables = get_tables(db_conn)
    for table in EXPECTED_TABLES:
        assert table in tables, f"Tabla '{table}' no encontrada"


def test_table_exists_true(db_conn: sqlite3.Connection):
    assert table_exists(db_conn, "listings") is True


def test_table_exists_false(db_conn: sqlite3.Connection):
    assert table_exists(db_conn, "tabla_inexistente") is False


def test_count_listings_empty(db_conn: sqlite3.Connection):
    assert count_listings(db_conn) == 0


def test_create_and_finish_run_log(db_conn: sqlite3.Connection):
    run_id = create_run_log(db_conn, notes="test run")
    assert run_id > 0

    run = get_run_log(db_conn, run_id)
    assert run is not None
    assert run["status"] == "running"
    assert run["notes"] == "test run"

    finish_run_log(db_conn, run_id, status="completed", listings_found=5)

    run = get_run_log(db_conn, run_id)
    assert run["status"] == "completed"
    assert run["listings_found"] == 5
    assert run["finished_at"] is not None


def test_multiple_run_logs(db_conn: sqlite3.Connection):
    id1 = create_run_log(db_conn, notes="run 1")
    id2 = create_run_log(db_conn, notes="run 2")
    assert id2 > id1
