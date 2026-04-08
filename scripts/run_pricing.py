"""Ejecuta el pipeline de pricing sobre listings normalizados y validos.

Uso:
    python -m scripts.run_pricing
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (
    get_database_path,
    load_comparable_levels,
    load_dominance_config,
    load_env,
    load_priority_config,
    load_pricing_config,
    load_risk_config,
    load_thresholds,
)
from app.pipeline.run_pricing import run_pricing_batch
from app.storage.database import get_connection, init_database
from app.storage.repositories import get_pricing_summary
from app.utils.logger import get_logger, setup_logging


def main() -> None:
    env = load_env()
    setup_logging(env.log_level)
    logger = get_logger("run_pricing")

    logger.info("=== AutoFinder - Pricing v2 + Fase 4.2 ===")

    # Cargar configs
    thresholds = load_thresholds()
    risk_config = load_risk_config()
    pricing_config = load_pricing_config()
    comp_levels = load_comparable_levels()
    dominance_config = load_dominance_config()
    priority_config = load_priority_config()

    logger.info(
        "Config: batch=%d, outlier=%s, financing=%s, dominance=%s",
        env.pricing_batch_size, env.enable_outlier_filtering,
        env.enable_financing_filter, env.enable_dominance_rule,
    )
    logger.info(
        "Niveles: A(anio+-%d, km+-%d) B(anio+-%d, km+-%d) min_A=%d",
        comp_levels.level_a_max_year_diff, comp_levels.level_a_max_km_diff,
        comp_levels.level_b_max_year_diff, comp_levels.level_b_max_km_diff,
        comp_levels.min_comparables_level_a,
    )
    logger.info(
        "Umbrales: strong=%.0f%%, medium=%.0f%%, extreme=%.0f%%",
        thresholds.strong_gap, thresholds.medium_gap, pricing_config.extreme_gap_pct,
    )

    # DB
    db_path = get_database_path()
    init_database(db_path)
    conn = get_connection(db_path)

    try:
        summary = run_pricing_batch(
            conn=conn,
            thresholds=thresholds,
            risk_config=risk_config,
            pricing_config=pricing_config,
            comp_levels=comp_levels,
            dominance_config=dominance_config,
            priority_config=priority_config,
            env=env,
        )

        logger.info("--- Resumen del lote ---")
        logger.info("Leidos:                %d", summary.total_read)
        logger.info("Analizados:            %d", summary.total_analyzed)
        logger.info("Skipped financiacion:  %d", summary.total_skipped_financing)
        logger.info("Con datos suficientes: %d", summary.total_enough_data)
        logger.info("Datos insuficientes:   %d", summary.total_insufficient_data)
        logger.info("Sin datos:             %d", summary.total_no_data)
        logger.info("Strong opportunity:    %d", summary.total_strong)
        logger.info("Medium opportunity:    %d", summary.total_medium)
        logger.info("Not opportunity:       %d", summary.total_not_opportunity)
        logger.info("Dominados:             %d", summary.total_dominated)
        logger.info("Riesgo alto:           %d", summary.total_high_risk)
        logger.info("--- Prioridad operativa (Fase 4.2) ---")
        logger.info("Urgent review:         %d", summary.total_urgent_review)
        logger.info("High priority:         %d", summary.total_high_priority)
        logger.info("Medium priority:       %d", summary.total_medium_priority)
        logger.info("Low priority:          %d", summary.total_low_priority)
        logger.info("Top 1 local microgrupo:%d", summary.total_top_local_1)
        logger.info("Con rebaja (markdown): %d", summary.total_markdown)
        logger.info("Errores:               %d", summary.total_errors)

        if summary.models_analyzed:
            logger.info("--- Modelos analizados ---")
            for model, count in sorted(
                summary.models_analyzed.items(), key=lambda x: -x[1]
            ):
                logger.info("  %-20s %d", model, count)

        global_summary = get_pricing_summary(conn)
        logger.info("--- Estado global de pricing ---")
        logger.info("Total analizados:      %d", global_summary["total_analyzed"])
        logger.info("Con datos suficientes: %d", global_summary["enough_data"])
        logger.info("Datos insuficientes:   %d", global_summary["insufficient_data"])
        logger.info("Strong opportunity:    %d", global_summary["strong_opportunities"])
        logger.info("Medium opportunity:    %d", global_summary["medium_opportunities"])
        logger.info("Dominados:             %d", global_summary["dominated"])
        logger.info("Financiamiento excl:   %d", global_summary["financing_excluded"])
        logger.info("Riesgo alto:           %d", global_summary["high_risk"])
        logger.info("Urgent review:         %d", global_summary.get("urgent_review", 0))
        logger.info("High priority:         %d", global_summary.get("high_priority", 0))
        logger.info("Top 1 local:           %d", global_summary.get("top_local_1", 0))
        logger.info("Errores:               %d", global_summary["errors"])

    finally:
        conn.close()

    logger.info("=== Pricing finalizado ===")


if __name__ == "__main__":
    main()
