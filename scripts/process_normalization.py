"""Ejecuta el pipeline de normalizacion sobre listings ya recolectados.

Lee publicaciones crudas de la DB, normaliza modelos, valida segmento,
detecta duplicados y persiste los resultados.

Uso:
    python -m scripts.process_normalization
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_database_path, load_env, load_model_aliases, load_segment_rules
from app.pipeline.normalize_listings import normalize_batch
from app.storage.database import get_connection, init_database
from app.storage.repositories import get_normalization_summary
from app.utils.logger import get_logger, setup_logging


def main() -> None:
    env = load_env()
    setup_logging(env.log_level)
    logger = get_logger("process_normalization")

    logger.info("=== AutoFinder - Normalizacion ===")

    # Config
    segment = load_segment_rules()
    aliases = load_model_aliases()

    logger.info(
        "Config: batch=%d, dedup=%s, ambiguous=%s",
        env.normalization_batch_size,
        env.enable_heuristic_dedup,
        env.allow_ambiguous_models,
    )

    # DB
    db_path = get_database_path()
    init_database(db_path)
    conn = get_connection(db_path)

    try:
        # Ejecutar normalizacion
        summary = normalize_batch(conn, segment, aliases, env)

        # Resumen del lote
        logger.info("--- Resumen del lote ---")
        logger.info("Leidos:        %d", summary.total_read)
        logger.info("Normalizados:  %d", summary.total_normalized)
        logger.info("Validos:       %d", summary.total_valid)
        logger.info("Invalidos:     %d", summary.total_invalid)
        logger.info("Duplicados:    %d", summary.total_duplicates)
        logger.info("Errores:       %d", summary.total_errors)

        if summary.invalid_reasons:
            logger.info("--- Motivos de descarte ---")
            for reason, count in sorted(summary.invalid_reasons.items(), key=lambda x: -x[1]):
                logger.info("  %-30s %d", reason, count)

        if summary.models_found:
            logger.info("--- Modelos encontrados ---")
            for model, count in sorted(summary.models_found.items(), key=lambda x: -x[1]):
                logger.info("  %-20s %d", model, count)

        # Resumen global de la DB
        global_summary = get_normalization_summary(conn)
        logger.info("--- Estado global de la DB ---")
        logger.info("Total listings:     %d", global_summary["total"])
        logger.info("Normalizados:       %d", global_summary["normalized"])
        logger.info("Validos:            %d", global_summary["valid"])
        logger.info("Invalidos:          %d", global_summary["invalid"])
        logger.info("Duplicados:         %d", global_summary["duplicates"])

    finally:
        conn.close()

    logger.info("=== Normalizacion finalizada ===")


if __name__ == "__main__":
    main()
