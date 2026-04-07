"""Script para inicializar la base de datos SQLite.

Uso:
    python -m scripts.init_db
"""

import sys
from pathlib import Path

# Agregar raiz del proyecto al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_database_path
from app.storage.database import get_tables, init_database, get_connection
from app.utils.logger import get_logger, setup_logging


def main() -> None:
    setup_logging("INFO")
    logger = get_logger("init_db")

    db_path = get_database_path()
    logger.info("Inicializando base de datos en: %s", db_path)

    init_database(db_path)

    # Verificar tablas creadas
    conn = get_connection(db_path)
    tables = get_tables(conn)
    conn.close()

    logger.info("Tablas creadas: %s", tables)
    logger.info("Base de datos lista.")


if __name__ == "__main__":
    main()
