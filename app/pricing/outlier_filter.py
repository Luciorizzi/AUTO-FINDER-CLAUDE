"""Filtro basico de outliers para precios de comparables.

Estrategia: IQR (Interquartile Range).

Por que IQR y no otra cosa:
- Es simple, robusto y ampliamente usado en estadistica descriptiva.
- No asume distribucion normal (a diferencia de Z-score).
- Funciona bien con muestras chicas (5-15 comparables).
- Es facil de explicar y auditar.
- El factor IQR es configurable (1.5 = estandar, 2.0 = permisivo).

Un precio se considera outlier si:
  precio < Q1 - factor * IQR
  o
  precio > Q3 + factor * IQR

donde IQR = Q3 - Q1
"""

from dataclasses import dataclass, field

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OutlierFilterResult:
    """Resultado del filtro de outliers."""
    prices_in: list[float] = field(default_factory=list)
    prices_out: list[float] = field(default_factory=list)
    outliers_removed: list[float] = field(default_factory=list)
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None


def _percentile(sorted_values: list[float], p: float) -> float:
    """Calcula percentil usando interpolacion lineal.

    Implementacion propia para no depender de numpy/scipy.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    k = (n - 1) * p
    floor_k = int(k)
    ceil_k = min(floor_k + 1, n - 1)
    fraction = k - floor_k

    return sorted_values[floor_k] + fraction * (sorted_values[ceil_k] - sorted_values[floor_k])


def filter_outliers(
    prices: list[float],
    iqr_factor: float = 1.5,
) -> OutlierFilterResult:
    """Filtra precios outliers usando IQR.

    Args:
        prices: Lista de precios de comparables.
        iqr_factor: Multiplicador del IQR para definir limites.
                    1.5 = estandar, 2.0 = permisivo.

    Returns:
        OutlierFilterResult con precios filtrados y estadisticas.
    """
    result = OutlierFilterResult(prices_in=list(prices))

    if len(prices) < 4:
        # Con menos de 4 valores, IQR no aporta. Devolver todo sin filtrar.
        result.prices_out = list(prices)
        logger.debug("Menos de 4 precios (%d), sin filtro de outliers", len(prices))
        return result

    sorted_prices = sorted(prices)

    q1 = _percentile(sorted_prices, 0.25)
    q3 = _percentile(sorted_prices, 0.75)
    iqr = q3 - q1

    lower_bound = q1 - iqr_factor * iqr
    upper_bound = q3 + iqr_factor * iqr

    result.q1 = q1
    result.q3 = q3
    result.iqr = iqr
    result.lower_bound = lower_bound
    result.upper_bound = upper_bound

    for p in prices:
        if lower_bound <= p <= upper_bound:
            result.prices_out.append(p)
        else:
            result.outliers_removed.append(p)

    if result.outliers_removed:
        logger.debug(
            "Outliers removidos: %d de %d (IQR=%.0f, bounds=[%.0f, %.0f])",
            len(result.outliers_removed), len(prices),
            iqr, lower_bound, upper_bound,
        )

    return result
