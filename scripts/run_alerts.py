"""Ejecuta el pipeline de alertas por Telegram.

Lee listings priorizados desde la DB, evalúa deduplicación,
envía alertas nuevas/actualizadas y persiste resultados.

Uso:
    python -m scripts.run_alerts
    python -m scripts.run_alerts --dry-run
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_database_path, load_env
from app.pipeline.run_alerts import run_alerts_pipeline
from app.storage.database import get_connection, init_database
from app.utils.logger import get_logger, setup_logging


def main() -> None:
    env = load_env()

    # Soporte --dry-run desde CLI
    if "--dry-run" in sys.argv:
        env.alert_dry_run = True

    setup_logging(env.log_level)
    logger = get_logger("run_alerts")

    logger.info("=== AutoFinder - Run Alerts ===")
    logger.info(
        "Config: telegram_enabled=%s, dry_run=%s, levels=%s, "
        "resend_price=%s, resend_priority=%s, resend_opportunity=%s",
        env.telegram_enabled,
        env.alert_dry_run,
        env.alert_priority_levels,
        env.alert_resend_on_price_change,
        env.alert_resend_on_priority_upgrade,
        env.alert_resend_on_opportunity_upgrade,
    )

    db_path = get_database_path()
    init_database(db_path)
    conn = get_connection(db_path)

    try:
        summary = run_alerts_pipeline(conn, env)

        logger.info("=== Resumen de alertas ===")
        logger.info("Total elegibles:            %d", summary.total_eligible)
        logger.info("Nuevos (new_match):         %d", summary.total_new)
        logger.info("Reenviados (price_drop):    %d", summary.total_resent_price_drop)
        logger.info("Reenviados (priority_up):   %d", summary.total_resent_priority_upgrade)
        logger.info("Reenviados (opportunity_up):%d", summary.total_resent_opportunity_upgrade)
        logger.info("Omitidos (duplicados):      %d", summary.total_skipped_duplicate)
        logger.info("Enviados OK:                %d", summary.total_sent_ok)
        logger.info("Fallidos:                   %d", summary.total_failed)
        logger.info("Dry run:                    %d", summary.total_dry_run)

        if summary.errors:
            logger.warning("Errores individuales: %d", len(summary.errors))
            for err in summary.errors[:5]:
                logger.warning("  %s", err)

    finally:
        conn.close()

    logger.info("=== Run Alerts finalizado ===")


if __name__ == "__main__":
    main()
