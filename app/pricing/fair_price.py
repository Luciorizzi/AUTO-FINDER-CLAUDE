"""Calculo de fair price por mediana de comparables.

El fair price es la mediana de los precios de comparables validos
despues de excluir outliers. Representa el "precio justo de mercado"
estimado para un auto con caracteristicas similares.
"""

from dataclasses import dataclass
from typing import Optional

from app.pricing.outlier_filter import filter_outliers
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FairPriceResult:
    """Resultado del calculo de fair price."""
    fair_price: Optional[float] = None
    median_price: Optional[float] = None
    p25_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    comparables_found: int = 0
    comparables_used: int = 0
    outliers_removed: int = 0
    pricing_status: str = "pending"
    cv: Optional[float] = None  # Coeficiente de variacion


def _median(sorted_values: list[float]) -> float:
    """Calcula mediana de una lista ya ordenada."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("No se puede calcular mediana de lista vacia")
    mid = n // 2
    if n % 2 == 0:
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2
    return sorted_values[mid]


def _percentile(sorted_values: list[float], p: float) -> float:
    """Calcula percentil por interpolacion lineal."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * p
    floor_k = int(k)
    ceil_k = min(floor_k + 1, n - 1)
    fraction = k - floor_k
    return sorted_values[floor_k] + fraction * (sorted_values[ceil_k] - sorted_values[floor_k])


def _coefficient_of_variation(values: list[float]) -> Optional[float]:
    """Calcula coeficiente de variacion (stddev / mean).

    Mide la dispersion relativa. Un CV > 0.40 indica alta variabilidad.
    """
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    stddev = variance ** 0.5
    return stddev / mean


def calculate_fair_price(
    comparable_prices: list[float],
    min_comparables: int = 3,
    enable_outlier_filtering: bool = True,
    iqr_factor: float = 1.5,
) -> FairPriceResult:
    """Calcula el fair price a partir de precios de comparables.

    Flujo:
    1. Verificar cantidad minima de comparables
    2. Filtrar outliers (si habilitado y hay suficientes datos)
    3. Calcular mediana como fair price
    4. Calcular estadisticas complementarias

    Args:
        comparable_prices: Precios de los comparables encontrados.
        min_comparables: Minimo de comparables para un analisis confiable.
        enable_outlier_filtering: Si filtrar outliers con IQR.
        iqr_factor: Factor IQR para el filtro de outliers.

    Returns:
        FairPriceResult con fair_price y estadisticas.
    """
    result = FairPriceResult()
    result.comparables_found = len(comparable_prices)

    if not comparable_prices:
        result.pricing_status = "no_data"
        return result

    if len(comparable_prices) < min_comparables:
        result.pricing_status = "insufficient_data"
        # Igual calculamos lo que podemos, pero marcamos como insuficiente
        sorted_prices = sorted(comparable_prices)
        result.comparables_used = len(sorted_prices)
        result.median_price = _median(sorted_prices)
        result.fair_price = result.median_price
        result.min_price = sorted_prices[0]
        result.max_price = sorted_prices[-1]
        if len(sorted_prices) >= 2:
            result.p25_price = _percentile(sorted_prices, 0.25)
        result.cv = _coefficient_of_variation(sorted_prices)
        return result

    # Filtrar outliers
    if enable_outlier_filtering:
        outlier_result = filter_outliers(comparable_prices, iqr_factor=iqr_factor)
        clean_prices = outlier_result.prices_out
        result.outliers_removed = len(outlier_result.outliers_removed)
    else:
        clean_prices = list(comparable_prices)

    # Si despues del filtro quedan menos del minimo, usar todos
    if len(clean_prices) < min_comparables:
        logger.debug(
            "Despues del filtro de outliers quedan %d (< %d minimo), usando todos",
            len(clean_prices), min_comparables,
        )
        clean_prices = list(comparable_prices)
        result.outliers_removed = 0

    sorted_prices = sorted(clean_prices)
    result.comparables_used = len(sorted_prices)

    # Calcular estadisticas
    result.median_price = _median(sorted_prices)
    result.fair_price = result.median_price
    result.min_price = sorted_prices[0]
    result.max_price = sorted_prices[-1]
    result.p25_price = _percentile(sorted_prices, 0.25)
    result.cv = _coefficient_of_variation(sorted_prices)
    result.pricing_status = "enough_data"

    logger.debug(
        "Fair price calculado: %.0f (mediana de %d comparables, cv=%.3f)",
        result.fair_price, result.comparables_used,
        result.cv if result.cv else 0,
    )

    return result
