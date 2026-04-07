"""Fixtures compartidos para tests."""

import sqlite3
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT
from app.storage.database import get_connection, init_database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Crea una DB temporal inicializada con el schema."""
    db_path = tmp_path / "test.db"
    init_database(db_path)
    return db_path


@pytest.fixture
def db_conn(tmp_db: Path) -> sqlite3.Connection:
    """Retorna una conexion a la DB temporal."""
    conn = get_connection(tmp_db)
    yield conn
    conn.close()
