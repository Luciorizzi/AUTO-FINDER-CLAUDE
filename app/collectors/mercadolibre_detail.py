"""Extraccion de detalle de publicaciones de Mercado Libre.

Entra a cada publicacion individual y extrae todos los campos
disponibles del detalle.
"""

import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from app.collectors.selectors import DETAIL, DETAIL_FALLBACK
from app.parsers.listing_parser import ListingDetail, build_listing_detail
from app.parsers.text_normalizer import clean_text
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _query_with_fallback(page: Page, selectors: list[str]) -> Optional[str]:
    """Intenta multiples selectores y retorna el texto del primero que funcione."""
    for selector in selectors:
        try:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text()
                if text and text.strip():
                    return text.strip()
        except Exception:
            continue
    return None


def _extract_specs_table(page: Page) -> dict[str, str]:
    """Extrae la tabla de especificaciones tecnicas."""
    specs: dict[str, str] = {}

    try:
        rows = page.query_selector_all(DETAIL["specs_row"])
        for row in rows:
            header = row.query_selector(DETAIL["specs_header"])
            data = row.query_selector(DETAIL["specs_data"])
            if header and data:
                key = clean_text(header.inner_text())
                value = clean_text(data.inner_text())
                if key and value:
                    specs[key] = value
    except Exception as e:
        logger.debug("No se pudo extraer tabla de specs: %s", e)

    return specs


def fetch_listing_detail(
    page: Page,
    url: str,
    delay_seconds: float = 2.0,
) -> Optional[ListingDetail]:
    """Navega a una publicacion y extrae el detalle completo."""
    logger.debug("Visitando detalle: %s", url)

    try:
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(delay_seconds)
    except PlaywrightTimeout:
        logger.warning("Timeout cargando detalle: %s", url)
        return None
    except Exception as e:
        logger.warning("Error navegando a detalle '%s': %s", url, e)
        return None

    # Titulo
    title = _query_with_fallback(page, DETAIL_FALLBACK["title"])

    # Precio
    price_text = _query_with_fallback(page, DETAIL_FALLBACK["price_amount"])

    # Moneda
    currency_el = page.query_selector(DETAIL["price_currency"])
    currency_text = currency_el.inner_text() if currency_el else None

    # Subtitulo (año | km | fecha)
    subtitle_el = page.query_selector(DETAIL["subtitle"])
    subtitle = subtitle_el.inner_text() if subtitle_el else None

    # Specs
    specs = _extract_specs_table(page)

    # Ubicacion: intentar extraer de specs primero, si no del HTML
    # (el selector location a veces trae avisos de seguridad de ML)
    location = specs.get("Ubicación") or specs.get("Ubicacion")

    # Seller info
    seller_el = page.query_selector(DETAIL["seller_info"])
    seller_info = seller_el.inner_text() if seller_el else None
    # Limpiar: extraer solo la parte relevante
    if seller_info and "particular" in seller_info.lower():
        seller_info = "particular"
    elif seller_info and ("concesionaria" in seller_info.lower() or "agencia" in seller_info.lower()):
        seller_info = "concesionaria"

    detail = build_listing_detail(
        url=url,
        title=title,
        price_text=price_text,
        currency_text=currency_text,
        location=location,
        specs=specs,
        seller_info=seller_info,
        subtitle=subtitle,
    )

    fields_found = sum(1 for v in [
        detail.title, detail.price, detail.year, detail.km, detail.location
    ] if v is not None)
    logger.debug(
        "Detalle: id=%s campos=%d/5 precio=%s year=%s km=%s",
        detail.source_id, fields_found, detail.price, detail.year, detail.km,
    )

    return detail


def fetch_multiple_details(
    page: Page,
    urls: list[str],
    max_details: int = 50,
    delay_seconds: float = 2.0,
) -> list[ListingDetail]:
    """Visita multiples publicaciones y retorna los detalles extraidos."""
    details: list[ListingDetail] = []
    errors = 0

    urls_to_visit = urls[:max_details]
    logger.info("Visitando %d detalles de %d disponibles", len(urls_to_visit), len(urls))

    for i, url in enumerate(urls_to_visit, 1):
        try:
            detail = fetch_listing_detail(page, url, delay_seconds)
            if detail and detail.source_id:
                details.append(detail)
            else:
                logger.warning("Detalle vacio o sin source_id: %s", url)
                errors += 1
        except Exception as e:
            logger.error("Error en detalle %d/%d (%s): %s", i, len(urls_to_visit), url, e)
            errors += 1

        if i % 10 == 0:
            logger.info("Progreso detalles: %d/%d (errores: %d)", i, len(urls_to_visit), errors)

    logger.info(
        "Detalles: %d exitosos, %d errores de %d intentados",
        len(details), errors, len(urls_to_visit),
    )
    return details
