"""Ranking local dentro del microgrupo comparable.

Complementa al fair price (mediana global de comparables) con una
medida de posicion relativa dentro del grupo mas cercano. La idea es:
si un auto esta entre los mas baratos de su microgrupo real, eso es
una senal fuerte aunque el gap contra la mediana general no sea extremo.

Microgrupo = comparables nivel A:
- mismo model_normalized
- misma currency
- year ± local_group_max_year_diff (por defecto 1)
- km ± local_group_max_km_diff (por defecto 15000)

Se calculan:
- local_price_rank: posicion 1-based del target en el grupo ordenado por precio
- local_group_size: cantidad total de listings en el microgrupo (incluye target)
- local_price_percentile: percentil del target (0 = mas barato, 1 = mas caro)
- is_top_local_price_1: true si es el mas barato del grupo
- is_top_local_price_3: true si esta entre los 3 mas baratos
"""

from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LocalRankResult:
    """Resultado del ranking local dentro del microgrupo."""
    local_price_rank: Optional[int] = None
    local_group_size: int = 0
    local_price_percentile: Optional[float] = None
    is_top_local_price_1: bool = False
    is_top_local_price_3: bool = False
    has_enough_data: bool = False


def compute_local_rank(
    target_price: Optional[float],
    comparables: list[dict],
    target_year: Optional[int],
    target_km: Optional[int],
    local_group_max_year_diff: int = 1,
    local_group_max_km_diff: int = 15000,
    local_min_group_size: int = 3,
) -> LocalRankResult:
    """Calcula el ranking del target dentro de su microgrupo local.

    Args:
        target_price: Precio del listing objetivo.
        comparables: Lista de comparables ya filtrados por modelo/moneda
            (los que devuelve comparable_finder). Cada dict con 'price',
            'year', 'km'.
        target_year: Anio del target.
        target_km: Km del target.
        local_group_max_year_diff: Delta maximo de anio para microgrupo.
        local_group_max_km_diff: Delta maximo de km para microgrupo.
        local_min_group_size: Tamano minimo del grupo para que el rank
            sea significativo (incluye al target).

    Returns:
        LocalRankResult con posicion, tamano y flags top1/top3.
    """
    result = LocalRankResult()

    if target_price is None or target_year is None or target_km is None:
        return result

    # Filtrar comparables al microgrupo estricto
    local_prices: list[float] = []
    for comp in comparables:
        comp_price = comp.get("price")
        comp_year = comp.get("year")
        comp_km = comp.get("km")
        if comp_price is None or comp_year is None or comp_km is None:
            continue
        if abs(comp_year - target_year) > local_group_max_year_diff:
            continue
        if abs(comp_km - target_km) > local_group_max_km_diff:
            continue
        local_prices.append(comp_price)

    # El grupo incluye al target
    group_size = len(local_prices) + 1
    result.local_group_size = group_size

    if group_size < local_min_group_size:
        logger.debug(
            "Microgrupo muy chico (%d < %d) para ranking local",
            group_size, local_min_group_size,
        )
        return result

    result.has_enough_data = True

    # Posicion del target: cuantos comparables tienen precio <= target
    # (rank 1-based, menor precio = rank 1)
    cheaper_or_equal_count = sum(1 for p in local_prices if p < target_price)
    rank = cheaper_or_equal_count + 1  # 1-based

    result.local_price_rank = rank
    result.is_top_local_price_1 = (rank == 1)
    result.is_top_local_price_3 = (rank <= 3)

    # Percentil: 0 = mas barato, 1 = mas caro
    if group_size > 1:
        result.local_price_percentile = round((rank - 1) / (group_size - 1), 3)
    else:
        result.local_price_percentile = 0.0

    logger.debug(
        "Ranking local: rank=%d/%d percentile=%.2f top1=%s top3=%s",
        rank, group_size, result.local_price_percentile,
        result.is_top_local_price_1, result.is_top_local_price_3,
    )

    return result
