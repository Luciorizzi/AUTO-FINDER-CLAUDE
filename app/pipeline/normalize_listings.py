"""Pipeline de normalizacion de listings.

Flujo:
1. Leer listings crudos pendientes de normalizar
2. Por cada listing:
   a. Mapear modelo con ModelMapper
   b. Validar contra reglas del segmento
   c. Verificar duplicados heuristicos (si esta habilitado)
   d. Persistir resultado de normalizacion
3. Generar resumen

Este pipeline es idempotente: se puede correr multiples veces
y solo procesa listings que no fueron normalizados previamente.
"""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from app.config import EnvSettings, SegmentConfig, ModelAliasesConfig
from app.filters.duplicate_filter import check_heuristic_duplicate
from app.filters.segment_filter import validate_listing
from app.parsers.model_mapper import ModelMapper
from app.storage.repositories import (
    get_all_normalized_valid,
    get_listings_pending_normalization,
    update_normalization,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class NormalizationSummary:
    """Resumen de una corrida de normalizacion."""
    total_read: int = 0
    total_normalized: int = 0
    total_valid: int = 0
    total_invalid: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    invalid_reasons: dict[str, int] = field(default_factory=dict)
    models_found: dict[str, int] = field(default_factory=dict)


def normalize_batch(
    conn: sqlite3.Connection,
    segment: SegmentConfig,
    aliases_config: ModelAliasesConfig,
    env: EnvSettings,
) -> NormalizationSummary:
    """Procesa un lote de listings pendientes de normalizacion."""
    summary = NormalizationSummary()

    # Inicializar mapper
    mapper = ModelMapper(aliases_config, allow_ambiguous=env.allow_ambiguous_models)

    # Leer pendientes
    listings = get_listings_pending_normalization(conn, limit=env.normalization_batch_size)
    summary.total_read = len(listings)

    if not listings:
        logger.info("No hay listings pendientes de normalizar")
        return summary

    logger.info("Procesando %d listings pendientes", len(listings))

    # Cargar validos existentes para dedup
    existing_valid = get_all_normalized_valid(conn) if env.enable_heuristic_dedup else []

    reason_counter: Counter = Counter()
    model_counter: Counter = Counter()

    for listing in listings:
        listing_id = listing["id"]

        try:
            # 1. Mapear modelo
            match = mapper.match(
                title=listing.get("title"),
                model_raw=listing.get("model_raw"),
                brand=listing.get("brand"),
            )

            model_normalized = match.model_normalized
            brand = match.brand

            # 2. Validar segmento
            validation = validate_listing(
                model_normalized=model_normalized,
                year=listing.get("year"),
                km=listing.get("km"),
                price=listing.get("price"),
                title=listing.get("title"),
                segment=segment,
            )

            if not validation.is_valid:
                update_normalization(
                    conn, listing_id,
                    model_normalized=model_normalized,
                    brand=brand,
                    is_valid_segment=False,
                    invalid_reason=validation.reason,
                )
                summary.total_invalid += 1
                reason_counter[validation.reason] += 1
                continue

            # 3. Dedup heuristico (solo para validos)
            duplicate_of = None
            if env.enable_heuristic_dedup and existing_valid:
                dedup = check_heuristic_duplicate(
                    listing_id=listing_id,
                    model_normalized=model_normalized,
                    year=listing.get("year"),
                    km=listing.get("km"),
                    price=listing.get("price"),
                    candidates=existing_valid,
                    price_tolerance_pct=env.duplicate_price_tolerance_pct,
                    mileage_tolerance=env.duplicate_mileage_tolerance,
                )
                if dedup.is_duplicate:
                    duplicate_of = dedup.duplicate_of_id
                    summary.total_duplicates += 1

            # 4. Persistir
            update_normalization(
                conn, listing_id,
                model_normalized=model_normalized,
                brand=brand,
                is_valid_segment=True,
                duplicate_of=duplicate_of,
            )
            summary.total_valid += 1
            model_counter[model_normalized] += 1

            # Agregar a candidatos para dedup de los siguientes
            if env.enable_heuristic_dedup and not duplicate_of:
                existing_valid.append({
                    "id": listing_id,
                    "model_normalized": model_normalized,
                    "year": listing.get("year"),
                    "km": listing.get("km"),
                    "price": listing.get("price"),
                    "title": listing.get("title"),
                })

        except Exception as e:
            logger.error("Error normalizando listing id=%d: %s", listing_id, e)
            summary.total_errors += 1

    summary.total_normalized = summary.total_valid + summary.total_invalid
    summary.invalid_reasons = dict(reason_counter)
    summary.models_found = dict(model_counter)

    return summary
