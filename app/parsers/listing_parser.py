"""Parser de datos de publicaciones.

Transforma datos crudos extraidos del HTML en estructuras limpias
para persistir en la base de datos.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.filters.financing_detector import detect_financing
from app.parsers.text_normalizer import (
    clean_text,
    detect_currency,
    parse_km,
    parse_price,
    parse_year,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Resultado individual de una pagina de busqueda."""
    source: str = "mercadolibre"
    listing_url: str = ""
    source_id: str = ""
    title_preview: Optional[str] = None
    price_preview: Optional[float] = None
    currency_preview: str = "ARS"
    location_preview: Optional[str] = None
    year_preview: Optional[int] = None
    km_preview: Optional[int] = None
    search_query: str = ""
    search_position: int = 0
    search_page: int = 1
    # Seniales detectadas sobre el preview (Fase 2 v3)
    is_financing_preview: bool = False
    financing_pattern: Optional[str] = None
    # Score de priorizacion (seteado por el prioritizer)
    preview_priority_score: Optional[float] = None
    selected_for_detail: bool = False


@dataclass
class ListingDetail:
    """Datos completos extraidos del detalle de una publicacion."""
    source: str = "mercadolibre"
    source_id: str = ""
    url: str = ""
    title: Optional[str] = None
    price: Optional[float] = None
    currency: str = "ARS"
    location: Optional[str] = None
    model_raw: Optional[str] = None
    year: Optional[int] = None
    km: Optional[int] = None
    seller_type: Optional[str] = None
    brand: Optional[str] = None
    doors: Optional[int] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    raw_specs: dict[str, str] = field(default_factory=dict)


def extract_source_id(url: str) -> str:
    """Extrae el ID de ML desde la URL.

    URLs tipicas:
        https://auto.mercadolibre.com.ar/MLA-1234567-titulo-...
        https://www.mercadolibre.com.ar/titulo.../p/MLA1234567
    """
    # Patron MLA-NNNNNNN o MLA NNNNNNN
    match = re.search(r"MLA-?(\d+)", url)
    if match:
        return f"MLA{match.group(1)}"
    return ""


def parse_search_result(
    url: str,
    title: Optional[str],
    price_text: Optional[str],
    currency_text: Optional[str],
    location: Optional[str],
    attrs: list[str],
    search_query: str,
) -> SearchResult:
    """Parsea un resultado de busqueda crudo en un SearchResult."""
    cleaned_title = clean_text(title)
    # Deteccion temprana de financiamiento/anticipo sobre el titulo preview
    financing = detect_financing(cleaned_title)

    result = SearchResult(
        listing_url=url,
        source_id=extract_source_id(url),
        title_preview=cleaned_title,
        price_preview=parse_price(price_text),
        currency_preview=detect_currency(currency_text),
        location_preview=clean_text(location),
        search_query=search_query,
        is_financing_preview=financing.is_financing or financing.is_down_payment,
        financing_pattern=financing.matched_pattern or None,
    )

    # Intentar extraer año y km de los atributos del resultado
    for attr in attrs:
        attr_clean = attr.strip()
        year = parse_year(attr_clean)
        if year and not result.year_preview:
            result.year_preview = year
            continue
        if "km" in attr_clean.lower() and not result.km_preview:
            result.km_preview = parse_km(attr_clean)

    return result


def parse_specs_table(specs: dict[str, str]) -> dict[str, Any]:
    """Extrae campos tipados de la tabla de especificaciones."""
    parsed: dict[str, Any] = {}

    for key, value in specs.items():
        key_lower = key.lower().strip()

        if "año" in key_lower or "año" in key_lower:
            parsed["year"] = parse_year(value)
        elif "kilómetro" in key_lower or "kilometro" in key_lower or "km" in key_lower:
            parsed["km"] = parse_km(value)
        elif "puerta" in key_lower:
            from app.parsers.text_normalizer import extract_number
            parsed["doors"] = extract_number(value)
        elif "combustible" in key_lower or "tipo de combustible" in key_lower:
            parsed["fuel_type"] = clean_text(value)
        elif "transmisión" in key_lower or "transmision" in key_lower:
            parsed["transmission"] = clean_text(value)

    return parsed


def build_listing_detail(
    url: str,
    title: Optional[str],
    price_text: Optional[str],
    currency_text: Optional[str],
    location: Optional[str],
    specs: dict[str, str],
    seller_info: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> ListingDetail:
    """Construye un ListingDetail a partir de datos crudos del HTML."""
    parsed_specs = parse_specs_table(specs)

    detail = ListingDetail(
        source_id=extract_source_id(url),
        url=url,
        title=clean_text(title),
        price=parse_price(price_text),
        currency=detect_currency(currency_text),
        location=clean_text(location),
        model_raw=clean_text(title),
        year=parsed_specs.get("year") or parse_year(subtitle),
        km=parsed_specs.get("km"),
        seller_type=clean_text(seller_info),
        doors=parsed_specs.get("doors"),
        fuel_type=parsed_specs.get("fuel_type"),
        transmission=parsed_specs.get("transmission"),
        raw_specs=specs,
    )

    return detail
