"""Deteccion de duplicados entre listings.

Dos niveles:
1. Deduplicacion dura: mismo source_id (ya manejado por upsert en DB)
2. Deduplicacion heuristica: listings distintos que probablemente son el mismo auto

La heuristica es CONSERVADORA: solo marca duplicados cuando hay
alta coincidencia en modelo + año + km + precio.
"""

from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DuplicateCheck:
    """Resultado de verificacion de duplicado."""
    is_duplicate: bool = False
    duplicate_of_id: Optional[int] = None
    reason: str = ""


def check_heuristic_duplicate(
    listing_id: int,
    model_normalized: Optional[str],
    year: Optional[int],
    km: Optional[int],
    price: Optional[float],
    candidates: list[dict],
    price_tolerance_pct: float = 5.0,
    mileage_tolerance: int = 2000,
) -> DuplicateCheck:
    """Verifica si un listing es duplicado heuristico de alguno existente.

    Para considerarse duplicado, debe coincidir en TODOS estos criterios:
    - mismo modelo normalizado
    - mismo año
    - km dentro del rango de tolerancia
    - precio dentro del rango de tolerancia

    Args:
        listing_id: ID del listing a verificar.
        model_normalized: Modelo normalizado del listing.
        year: Año del listing.
        km: Kilometraje del listing.
        price: Precio del listing.
        candidates: Lista de dicts con listings existentes del mismo modelo.
        price_tolerance_pct: Tolerancia de precio en porcentaje.
        mileage_tolerance: Tolerancia de km en valor absoluto.

    Returns:
        DuplicateCheck indicando si es duplicado y de cuál.
    """
    if not all([model_normalized, year, km, price]):
        return DuplicateCheck()

    for cand in candidates:
        cand_id = cand["id"]
        if cand_id == listing_id:
            continue

        # Mismo modelo
        if cand.get("model_normalized") != model_normalized:
            continue

        # Mismo año
        if cand.get("year") != year:
            continue

        # Km dentro de tolerancia
        cand_km = cand.get("km")
        if cand_km is None or km is None:
            continue
        if abs(cand_km - km) > mileage_tolerance:
            continue

        # Precio dentro de tolerancia
        cand_price = cand.get("price")
        if cand_price is None or price is None or cand_price == 0:
            continue
        price_diff_pct = abs(price - cand_price) / cand_price * 100
        if price_diff_pct > price_tolerance_pct:
            continue

        # Todas las condiciones cumplidas -> duplicado
        logger.debug(
            "Duplicado heuristico: id=%d es duplicado de id=%d "
            "(model=%s, year=%d, km_diff=%d, price_diff=%.1f%%)",
            listing_id, cand_id, model_normalized, year,
            abs(cand_km - km), price_diff_pct,
        )
        return DuplicateCheck(
            is_duplicate=True,
            duplicate_of_id=cand_id,
            reason=f"heuristic_match:id={cand_id}",
        )

    return DuplicateCheck()
