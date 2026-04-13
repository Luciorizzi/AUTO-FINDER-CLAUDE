"""Ejecuta un ciclo completo de scraping una vez.

Pipeline:
1. Carga config
2. Busca publicaciones en ML por cada query del segmento
3. Prioriza y balancea resultados entre queries
4. Visita detalle de los seleccionados
5. Parsea y persiste datos en SQLite con metadata de search
6. Registra resumen de la corrida

Uso:
    python -m scripts.run_once
"""

import sys
import time
from pathlib import Path

# Agregar raiz del proyecto al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collectors.browser import BrowserManager
from app.collectors.mercadolibre_detail import fetch_multiple_details
from app.collectors.mercadolibre_search import search_all_queries
from app.collectors.search_prioritizer import prioritize_results
from app.config import get_database_path, load_env, load_scraping_config
from app.parsers.listing_parser import SearchResult
from app.storage.database import get_connection, init_database
from app.storage.repositories import (
    create_run_log,
    count_listings,
    count_snapshots,
    finish_run_log,
    get_existing_source_ids,
    persist_listing_detail,
)
from app.utils.logger import get_logger, setup_logging


def run_once() -> None:
    """Ejecuta un ciclo completo de scraping."""
    # 1. Config
    env = load_env()
    setup_logging(env.log_level)
    logger = get_logger("run_once")

    scraping_config = load_scraping_config()

    logger.info("=== AutoFinder - Run Once ===")
    logger.info(
        "Config: queries=%d, max_per_query=%d, max_details=%d, "
        "max_details_per_query=%d, min_per_query=%d, price_priority=%s, "
        "strategy=%s, deprio_fin=%s, excl_fin=%s, score=%s, headless=%s",
        len(scraping_config.search_queries),
        env.ml_max_results_per_query,
        env.ml_max_detail_pages_per_run,
        env.ml_max_details_per_query,
        env.min_details_per_query,
        env.prioritize_lowest_price_first,
        env.search_selection_strategy,
        env.deprioritize_financing_previews,
        env.exclude_financing_previews,
        env.enable_preview_priority_score,
        env.headless,
    )

    # 2. DB
    db_path = get_database_path()
    init_database(db_path)
    conn = get_connection(db_path)

    run_id = create_run_log(conn, notes="run_once")
    start_time = time.time()

    listings_before = count_listings(conn)
    total_search_results = 0
    total_details = 0
    total_persisted = 0
    total_errors = 0

    # Obtener IDs ya existentes para que el prioritizer no re-visite
    existing_ids = get_existing_source_ids(conn)
    logger.info("Listings ya en DB: %d", len(existing_ids))

    try:
        # 3. Scraping
        with BrowserManager(
            headless=env.headless,
            timeout_ms=env.browser_timeout_ms,
            user_agent=env.user_agent or None,
        ) as browser:
            page = browser.new_page()

            # 3a. Busqueda (resultados agrupados por query)
            logger.info("--- Fase: Busqueda ---")
            results_by_query = search_all_queries(
                page=page,
                queries=scraping_config.search_queries,
                max_per_query=env.ml_max_results_per_query,
                delay_seconds=env.scrape_delay_seconds,
            )
            total_search_results = sum(len(v) for v in results_by_query.values())
            logger.info("Resultados de busqueda: %d", total_search_results)

            if total_search_results == 0:
                logger.warning("No se encontraron resultados. Finalizando.")
                finish_run_log(conn, run_id, status="completed", notes="Sin resultados")
                conn.close()
                return

            # 3b. Priorizacion y balance
            logger.info("--- Fase: Priorizacion ---")
            selected, prio_stats = prioritize_results(
                results_by_query=results_by_query,
                max_details_total=env.ml_max_detail_pages_per_run,
                max_details_per_query=env.ml_max_details_per_query,
                min_details_per_query=env.min_details_per_query,
                prioritize_lowest_price=env.prioritize_lowest_price_first,
                already_seen_ids=existing_ids,
                deprioritize_financing=env.deprioritize_financing_previews,
                exclude_financing=env.exclude_financing_previews,
                enable_priority_score=env.enable_preview_priority_score,
                strategy=env.search_selection_strategy,
            )

            if not selected:
                logger.info("Todos los resultados ya estan en la DB. Finalizando.")
                finish_run_log(conn, run_id, status="completed", notes="Todo ya visitado")
                conn.close()
                return

            # Construir mapa source_id -> SearchResult para metadata
            search_meta: dict[str, SearchResult] = {}
            for r in selected:
                key = r.source_id or r.listing_url
                if key:
                    search_meta[key] = r

            # 3c. Detalle
            logger.info("--- Fase: Detalle ---")
            urls = [r.listing_url for r in selected if r.listing_url]
            details = fetch_multiple_details(
                page=page,
                urls=urls,
                max_details=len(urls),  # ya priorizados, visitar todos
                delay_seconds=env.scrape_delay_seconds,
            )
            total_details = len(details)

        # 4. Persistencia con metadata de search
        logger.info("--- Fase: Persistencia ---")
        for detail in details:
            try:
                # Buscar metadata del search para este detalle
                meta = search_meta.get(detail.source_id)
                persist_listing_detail(
                    conn, detail,
                    search_query=meta.search_query if meta else None,
                    search_position=meta.search_position if meta else None,
                    search_page=meta.search_page if meta else 1,
                    preview_price=meta.price_preview if meta else None,
                    preview_currency=meta.currency_preview if meta else None,
                    preview_financing_flag=meta.is_financing_preview if meta else False,
                    preview_priority_score=meta.preview_priority_score if meta else None,
                    selected_for_detail=meta.selected_for_detail if meta else True,
                )
                total_persisted += 1
            except Exception as e:
                logger.error("Error persistiendo %s: %s", detail.source_id, e)
                total_errors += 1

        listings_after = count_listings(conn)
        snapshots_total = count_snapshots(conn)
        new_listings = listings_after - listings_before

        # 5. Resumen
        elapsed = time.time() - start_time
        logger.info("=== Resumen de corrida ===")
        logger.info("Queries ejecutadas:    %d", len(scraping_config.search_queries))
        logger.info("Resultados busqueda:   %d", total_search_results)
        logger.info("Candidatos nuevos:     %d", prio_stats.total_candidates)
        logger.info("Con precio parseable:  %d", prio_stats.total_with_price)
        logger.info("Sin precio parseable:  %d", prio_stats.total_without_price)
        logger.info("Financieros detectados:%d", prio_stats.total_financing_detected)
        logger.info("Financieros excluidos: %d", prio_stats.total_financing_excluded)
        logger.info("Estrategia seleccion:  %s", prio_stats.strategy)
        logger.info("Seleccionados:         %d", prio_stats.total_selected)
        logger.info("Excluidos por limite:  %d", prio_stats.total_excluded_by_limit)
        logger.info("Detalles procesados:   %d", total_details)
        logger.info("Persistidos OK:        %d", total_persisted)
        logger.info("Listings nuevos:       %d", new_listings)
        logger.info("Listings totales:      %d", listings_after)
        logger.info("Snapshots totales:     %d", snapshots_total)
        logger.info("Errores:               %d", total_errors)
        logger.info("Tiempo total:          %.1f segundos", elapsed)

        finish_run_log(
            conn, run_id,
            status="completed",
            listings_found=total_persisted,
            errors=total_errors,
            notes=(
                f"search={total_search_results} selected={prio_stats.total_selected} "
                f"details={total_details} new={new_listings} time={elapsed:.0f}s"
            ),
        )

    except Exception as e:
        logger.error("Error fatal en corrida: %s", e, exc_info=True)
        finish_run_log(conn, run_id, status="failed", errors=1, notes=str(e))

    finally:
        conn.close()

    logger.info("=== Run Once finalizado ===")


if __name__ == "__main__":
    run_once()
