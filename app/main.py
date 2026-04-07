"""Punto de entrada principal de AutoFinder.

Ejecuta un smoke test que verifica:
1. Carga de configuracion (.env + YAMLs)
2. Inicializacion del logger
3. Conexion a SQLite
4. Existencia de tablas principales
"""

import sys

from app.config import (
    get_database_path,
    load_env,
    load_model_aliases,
    load_segment_rules,
    load_thresholds,
)
from app.storage.database import get_connection, get_tables, init_database
from app.storage.repositories import count_listings, create_run_log, finish_run_log
from app.utils.logger import get_logger, setup_logging

EXPECTED_TABLES = {"listings", "listing_snapshots", "opportunity_alerts", "run_logs"}


def smoke_test() -> bool:
    """Ejecuta verificaciones basicas del sistema. Retorna True si todo ok."""
    # 1. Config
    env = load_env()
    setup_logging(env.log_level)
    logger = get_logger("main")

    logger.info("=== AutoFinder - Smoke Test ===")

    # Cargar configs YAML
    try:
        segment = load_segment_rules()
        thresholds = load_thresholds()
        aliases = load_model_aliases()
        logger.info("Config cargada: segmento=%s, modelos=%d, aliases=%d",
                     segment.name, len(segment.models), len(aliases.aliases))
        logger.info("Thresholds: strong=%.1f%%, medium=%.1f%%",
                     thresholds.strong_gap, thresholds.medium_gap)
    except Exception as e:
        logger.error("Error cargando configs: %s", e)
        return False

    # 2. Base de datos
    db_path = get_database_path()
    try:
        init_database(db_path)
        conn = get_connection(db_path)
    except Exception as e:
        logger.error("Error inicializando DB: %s", e)
        return False

    # 3. Verificar tablas
    try:
        tables = set(get_tables(conn))
        missing = EXPECTED_TABLES - tables
        if missing:
            logger.error("Tablas faltantes: %s", missing)
            conn.close()
            return False
        logger.info("Tablas verificadas: %s", sorted(tables & EXPECTED_TABLES))
    except Exception as e:
        logger.error("Error verificando tablas: %s", e)
        conn.close()
        return False

    # 4. Test basico de repositorio
    try:
        run_id = create_run_log(conn, notes="smoke_test")
        finish_run_log(conn, run_id, status="completed")
        total = count_listings(conn)
        logger.info("Repositorio OK: run_log=%d, listings=%d", run_id, total)
    except Exception as e:
        logger.error("Error en repositorio: %s", e)
        conn.close()
        return False

    conn.close()
    logger.info("=== Smoke Test PASSED ===")
    return True


def main() -> None:
    ok = smoke_test()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
