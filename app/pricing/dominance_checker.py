"""Regla de dominancia para evitar oportunidades falsas.

Un listing esta "dominado" si existe otro comparable del mismo modelo
y misma moneda que lo supera claramente en atributos clave sin costar
mas de forma material.

Criterio conservador: un comparable domina al target si cumple TODOS:
1. Mismo model_normalized
2. Misma currency
3. Anio >= target (igual o mas nuevo)
4. km <= target - min_km_advantage (menos km por un margen relevante)
5. Precio <= target * (1 + price_tolerance_pct/100)

La regla es conservadora: requiere ventaja en TODOS los ejes para evitar
matar oportunidades reales. Un auto solo es dominado si hay otro
objetivamente mejor y no mas caro.

Efecto: un listing dominado se degrada a not_opportunity.
"""

from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DominanceResult:
    """Resultado del chequeo de dominancia."""
    is_dominated: bool = False
    dominated_by_id: Optional[int] = None
    dominance_reason: str = ""


def check_dominance(
    listing_id: int,
    year: int,
    km: int,
    price: float,
    comparables: list[dict],
    price_tolerance_pct: float = 5.0,
    min_km_advantage: int = 3000,
) -> DominanceResult:
    """Verifica si un listing esta dominado por algun comparable.

    Args:
        listing_id: ID del listing target.
        year: Anio del target.
        km: Kilometraje del target.
        price: Precio del target.
        comparables: Lista de comparables validos (ya filtrados por modelo/moneda).
        price_tolerance_pct: % de tolerancia de precio del dominador.
        min_km_advantage: Ventaja minima de km que el dominador debe tener.

    Returns:
        DominanceResult indicando si esta dominado y por quien.
    """
    max_price = price * (1 + price_tolerance_pct / 100)
    max_km = km - min_km_advantage

    for comp in comparables:
        cid = comp.get("id")
        if cid == listing_id:
            continue

        comp_year = comp.get("year")
        comp_km = comp.get("km")
        comp_price = comp.get("price")

        if comp_year is None or comp_km is None or comp_price is None:
            continue

        # Debe ser igual o mas nuevo
        if comp_year < year:
            continue

        # Debe tener menos km por un margen relevante
        if comp_km > max_km:
            continue

        # Debe no costar mas (con tolerancia)
        if comp_price > max_price:
            continue

        # Dominado: este comparable es mejor en todo
        reason_parts = []
        if comp_year > year:
            reason_parts.append(f"anio {comp_year}>{year}")
        if comp_km < km:
            reason_parts.append(f"km {comp_km:,}<{km:,}")
        if comp_price <= price:
            reason_parts.append(f"precio {comp_price:,.0f}<={price:,.0f}")
        elif comp_price <= max_price:
            reason_parts.append(f"precio {comp_price:,.0f}~={price:,.0f}")

        reason = f"dominado por id={cid}: " + ", ".join(reason_parts)

        logger.debug(
            "Listing %d dominado por %d (%s)",
            listing_id, cid, reason,
        )

        return DominanceResult(
            is_dominated=True,
            dominated_by_id=cid,
            dominance_reason=reason,
        )

    return DominanceResult()
