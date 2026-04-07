"""Clasificacion de oportunidad por gap de precio.

Calcula el gap porcentual entre el precio publicado y el fair price
estimado, y clasifica el listing segun umbrales configurables.

gap_pct = ((precio_publicado - fair_price) / fair_price) * 100

Valores negativos indican que el precio publicado esta por debajo
del fair price (potencial oportunidad).

Regla de dominancia: un listing dominado se degrada a not_opportunity
independientemente de su gap.
"""

from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Niveles de oportunidad
STRONG_OPPORTUNITY = "strong_opportunity"
MEDIUM_OPPORTUNITY = "medium_opportunity"
NOT_OPPORTUNITY = "not_opportunity"


@dataclass
class OpportunityResult:
    """Resultado de la clasificacion de oportunidad."""
    gap_pct: Optional[float] = None
    opportunity_level: str = NOT_OPPORTUNITY
    published_price: Optional[float] = None
    fair_price: Optional[float] = None
    degraded_by_dominance: bool = False


def calculate_gap(published_price: float, fair_price: float) -> float:
    """Calcula el gap porcentual.

    Retorna negativo si el precio publicado es menor al fair price.
    Ejemplo: publicado=8M, fair=10M -> gap = -20.0
    """
    if fair_price == 0:
        return 0.0
    return ((published_price - fair_price) / fair_price) * 100


def classify_opportunity(
    published_price: Optional[float],
    fair_price: Optional[float],
    strong_gap: float = -12.0,
    medium_gap: float = -8.0,
    is_dominated: bool = False,
) -> OpportunityResult:
    """Clasifica un listing como oportunidad segun su gap de precio.

    Args:
        published_price: Precio publicado del listing.
        fair_price: Fair price calculado por mediana.
        strong_gap: Umbral para oportunidad fuerte (ej: -12).
        medium_gap: Umbral para oportunidad media (ej: -8).
        is_dominated: Si el listing esta dominado por un comparable mejor.

    Returns:
        OpportunityResult con gap_pct y nivel de oportunidad.
    """
    result = OpportunityResult(
        published_price=published_price,
        fair_price=fair_price,
    )

    if published_price is None or fair_price is None or fair_price == 0:
        return result

    gap = calculate_gap(published_price, fair_price)
    result.gap_pct = round(gap, 2)

    if gap <= strong_gap:
        result.opportunity_level = STRONG_OPPORTUNITY
    elif gap <= medium_gap:
        result.opportunity_level = MEDIUM_OPPORTUNITY
    else:
        result.opportunity_level = NOT_OPPORTUNITY

    # Dominancia degrada la oportunidad
    if is_dominated and result.opportunity_level != NOT_OPPORTUNITY:
        logger.debug(
            "Oportunidad degradada por dominancia: gap=%.2f%% %s -> not_opportunity",
            result.gap_pct, result.opportunity_level,
        )
        result.degraded_by_dominance = True
        result.opportunity_level = NOT_OPPORTUNITY

    logger.debug(
        "Gap=%.2f%% -> %s (publicado=%.0f, fair=%.0f%s)",
        result.gap_pct, result.opportunity_level,
        published_price, fair_price,
        ", dominado" if is_dominated else "",
    )

    return result
