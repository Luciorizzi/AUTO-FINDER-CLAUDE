"""Busqueda de comparables para pricing con niveles A/B.

Dado un listing normalizado y valido, encuentra otros listings del mismo
modelo normalizado con anio y kilometraje similar, en la misma moneda,
excluyendo publicaciones de financiamiento.

Niveles de comparables:
- Nivel A (estricto): mismo modelo, misma moneda, anio +-1, km +-15000
- Nivel B (ampliado): mismo modelo, misma moneda, anio +-2, km +-20000

Se intenta Nivel A primero. Si no alcanza el minimo configurable,
se abre a Nivel B.
"""

import sqlite3
from dataclasses import dataclass, field

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ComparableResult:
    """Resultado de la busqueda de comparables."""
    listing_id: int
    comparables: list[dict] = field(default_factory=list)
    level_used: str = "A"
    total_same_model: int = 0
    level_a_count: int = 0
    level_b_count: int = 0
    excluded_self: int = 0
    excluded_no_price: int = 0
    excluded_no_km: int = 0
    excluded_no_year: int = 0
    excluded_currency_mismatch: int = 0
    excluded_financing: int = 0
    excluded_year_delta: int = 0
    excluded_km_delta: int = 0


def find_comparables(
    conn: sqlite3.Connection,
    listing_id: int,
    model_normalized: str,
    km: int,
    year: int,
    currency: str,
    level_a_max_year_diff: int = 1,
    level_a_max_km_diff: int = 15000,
    level_b_max_year_diff: int = 2,
    level_b_max_km_diff: int = 20000,
    min_comparables_level_a: int = 3,
) -> ComparableResult:
    """Busca comparables validos con niveles A/B.

    Criterios de exclusion (aplicados antes de niveles):
    - Self-match
    - Sin precio, km o anio
    - Moneda distinta al target
    - Marcado como financiamiento/anticipo
    - Invalido o duplicado

    Luego aplica filtros de nivel:
    - Nivel A: |anio_diff| <= level_a_max_year_diff AND |km_diff| <= level_a_max_km_diff
    - Nivel B: |anio_diff| <= level_b_max_year_diff AND |km_diff| <= level_b_max_km_diff

    Si Nivel A tiene >= min_comparables_level_a, usa solo A.
    Si no, usa A + B combinados.
    """
    result = ComparableResult(listing_id=listing_id)

    # Buscar todos los del mismo modelo validos y no duplicados
    cursor = conn.execute(
        """SELECT id, price, km, year, title, currency,
                  is_financing, is_down_payment, is_total_price_confident
           FROM listings
           WHERE model_normalized = ?
             AND is_valid_segment = 1
             AND duplicate_of IS NULL
           ORDER BY id""",
        (model_normalized,),
    )
    candidates = cursor.fetchall()
    result.total_same_model = len(candidates)

    level_a: list[dict] = []
    level_b_only: list[dict] = []

    for row in candidates:
        row_dict = dict(row)
        cid = row_dict["id"]

        # --- Exclusiones absolutas ---

        if cid == listing_id:
            result.excluded_self += 1
            continue

        if row_dict.get("price") is None:
            result.excluded_no_price += 1
            continue

        if row_dict.get("km") is None:
            result.excluded_no_km += 1
            continue

        if row_dict.get("year") is None:
            result.excluded_no_year += 1
            continue

        # Moneda debe coincidir
        row_currency = row_dict.get("currency") or "ARS"
        if row_currency != currency:
            result.excluded_currency_mismatch += 1
            continue

        # Excluir financiamiento/anticipo
        if row_dict.get("is_financing") or row_dict.get("is_down_payment"):
            result.excluded_financing += 1
            continue

        # Precio no confiable
        if not row_dict.get("is_total_price_confident", True):
            result.excluded_financing += 1
            continue

        # --- Clasificar por nivel ---
        year_diff = abs(row_dict["year"] - year)
        km_diff = abs(row_dict["km"] - km)
        row_dict["year_diff"] = year_diff
        row_dict["km_delta"] = km_diff

        is_level_a = (year_diff <= level_a_max_year_diff and km_diff <= level_a_max_km_diff)
        is_level_b = (year_diff <= level_b_max_year_diff and km_diff <= level_b_max_km_diff)

        if is_level_a:
            level_a.append(row_dict)
        elif is_level_b:
            level_b_only.append(row_dict)
        else:
            # Fuera de ambos niveles: contar motivo principal
            if year_diff > level_b_max_year_diff:
                result.excluded_year_delta += 1
            else:
                result.excluded_km_delta += 1

    result.level_a_count = len(level_a)
    result.level_b_count = len(level_b_only)

    # Decidir que nivel usar
    if len(level_a) >= min_comparables_level_a:
        result.comparables = level_a
        result.level_used = "A"
    else:
        result.comparables = level_a + level_b_only
        result.level_used = "B" if level_b_only else "A"

    logger.debug(
        "Comparables listing=%d model=%s currency=%s: "
        "A=%d B=%d (usando=%s, total=%d) | "
        "excl: self=%d, moneda=%d, financ=%d, anio=%d, km=%d",
        listing_id, model_normalized, currency,
        result.level_a_count, result.level_b_count,
        result.level_used, len(result.comparables),
        result.excluded_self, result.excluded_currency_mismatch,
        result.excluded_financing, result.excluded_year_delta,
        result.excluded_km_delta,
    )

    return result
