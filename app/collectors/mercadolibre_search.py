"""Busqueda de publicaciones en Mercado Libre.

Ejecuta queries de busqueda, navega paginas de resultados
y extrae datos basicos de cada publicacion encontrada.
"""

import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from app.collectors.selectors import SEARCH, SEARCH_FALLBACK
from app.parsers.listing_parser import SearchResult, parse_search_result
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_search_url(query: str) -> str:
    """Construye la URL de busqueda de ML en la categoria Autos.

    Usa autos.mercadolibre.com.ar para filtrar solo vehiculos
    (no repuestos ni accesorios).
    Si la query contiene un rango de años (ej: "2010 2015"),
    lo convierte al formato _YearRange de ML.
    """
    import re
    # Detectar rango de años en la query
    year_match = re.search(r"(\d{4})\s+(\d{4})", query)
    # Remover los años de la query base
    clean_query = query
    if year_match:
        clean_query = query[:year_match.start()].strip()
        year_range = f"{year_match.group(1)}-{year_match.group(2)}"
    else:
        year_range = None

    slug = clean_query.replace(" ", "-")

    if year_range:
        return f"https://autos.mercadolibre.com.ar/{slug}_YearRange_{year_range}_NoIndex_True"
    return f"https://autos.mercadolibre.com.ar/{slug}_NoIndex_True"


def _query_selector_with_fallback(element, selectors: list[str]):
    """Prueba multiples selectores y retorna el primer match."""
    for sel in selectors:
        el = element.query_selector(sel)
        if el:
            return el
    return None


def _query_selector_all_with_fallback(element, selectors: list[str]) -> list:
    """Prueba multiples selectores y retorna el primer grupo con resultados."""
    for sel in selectors:
        els = element.query_selector_all(sel)
        if els:
            return els
    return []


def extract_results_from_page(
    page: Page,
    search_query: str,
    max_results: int,
) -> list[SearchResult]:
    """Extrae resultados de una pagina de busqueda ya cargada."""
    results: list[SearchResult] = []

    try:
        page.wait_for_selector(SEARCH["result_item"], timeout=15_000)
    except PlaywrightTimeout:
        logger.warning("No se encontraron resultados para: %s", search_query)
        return results

    items = page.query_selector_all(SEARCH["result_item"])
    logger.debug("Items encontrados en pagina: %d", len(items))

    for position, item in enumerate(items, 1):
        if len(results) >= max_results:
            break

        try:
            # Link + titulo (con fallback)
            link_el = _query_selector_with_fallback(item, SEARCH_FALLBACK["result_link"])
            if not link_el:
                continue
            url = link_el.get_attribute("href") or ""
            if not url or "mercadolibre" not in url:
                continue
            title = link_el.inner_text()

            # Precio
            price_el = item.query_selector(SEARCH["result_price_amount"])
            price_text = price_el.inner_text() if price_el else None

            currency_el = item.query_selector(SEARCH["result_price_currency"])
            currency_text = currency_el.inner_text() if currency_el else None

            # Ubicacion (con fallback)
            location_el = _query_selector_with_fallback(item, SEARCH_FALLBACK["result_location"])
            location = location_el.inner_text() if location_el else None

            # Atributos: año, km (con fallback)
            attr_elements = _query_selector_all_with_fallback(item, SEARCH_FALLBACK["result_attrs"])
            attrs = [el.inner_text() for el in attr_elements]

            result = parse_search_result(
                url=url,
                title=title,
                price_text=price_text,
                currency_text=currency_text,
                location=location,
                attrs=attrs,
                search_query=search_query,
            )
            result.search_position = position
            results.append(result)

        except Exception as e:
            logger.warning("Error extrayendo resultado: %s", e)
            continue

    return results


def search_mercadolibre(
    page: Page,
    query: str,
    max_results: int = 20,
    delay_seconds: float = 2.0,
) -> list[SearchResult]:
    """Ejecuta una busqueda en ML y retorna los resultados."""
    url = build_search_url(query)
    logger.info("Buscando: '%s' -> %s", query, url)

    all_results: list[SearchResult] = []
    seen_ids: set[str] = set()

    try:
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(delay_seconds)
    except PlaywrightTimeout:
        logger.error("Timeout cargando busqueda: %s", url)
        return all_results
    except Exception as e:
        logger.error("Error navegando a busqueda '%s': %s", query, e)
        return all_results

    results = extract_results_from_page(page, query, max_results)
    for r in results:
        dedup_key = r.source_id or r.listing_url
        if dedup_key and dedup_key not in seen_ids:
            seen_ids.add(dedup_key)
            all_results.append(r)

    logger.info("Query '%s': %d resultados extraidos", query, len(all_results))
    return all_results


def search_all_queries(
    page: Page,
    queries: list[str],
    max_per_query: int = 48,
    delay_seconds: float = 2.0,
) -> dict[str, list[SearchResult]]:
    """Ejecuta multiples queries y retorna resultados agrupados por query.

    Deduplica dentro de cada query pero NO entre queries
    (la dedup global la hace el prioritizer).

    Returns:
        Dict de query -> lista de SearchResults.
    """
    results_by_query: dict[str, list[SearchResult]] = {}

    for query in queries:
        results = search_mercadolibre(page, query, max_per_query, delay_seconds)
        # Dedup dentro de la query
        seen_ids: set[str] = set()
        unique: list[SearchResult] = []
        for r in results:
            dedup_key = r.source_id or r.listing_url
            if dedup_key and dedup_key not in seen_ids:
                seen_ids.add(dedup_key)
                unique.append(r)
        results_by_query[query] = unique

        if query != queries[-1]:
            time.sleep(delay_seconds)

    total = sum(len(v) for v in results_by_query.values())
    logger.info("Total resultados unicos: %d (de %d queries)", total, len(queries))
    return results_by_query
