"""Conexion y gestion de la base de datos SQLite."""

import sqlite3
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Crea una conexion a SQLite con row_factory habilitado."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database(db_path: Path) -> None:
    """Ejecuta el schema.sql para crear todas las tablas."""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema no encontrado: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection(db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
        logger.info("Base de datos inicializada en: %s", db_path)
    finally:
        conn.close()


def get_tables(conn: sqlite3.Connection) -> list[str]:
    """Retorna la lista de tablas existentes en la base."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return [row["name"] for row in cursor.fetchall()]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Verifica si una tabla existe en la base."""
    cursor = conn.execute(
        "SELECT count(*) as cnt FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone()["cnt"] > 0
