"""Filtros de segmento para validar listings.

Determina si un listing pertenece al segmento objetivo
y registra el motivo de descarte si no.
"""

from dataclasses import dataclass
from typing import Optional

from app.config import SegmentConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Resultado de validacion de un listing contra el segmento."""
    is_valid: bool
    reason: Optional[str] = None


def validate_listing(
    model_normalized: Optional[str],
    year: Optional[int],
    km: Optional[int],
    price: Optional[float],
    title: Optional[str],
    segment: SegmentConfig,
) -> ValidationResult:
    """Valida un listing contra las reglas del segmento.

    Retorna ValidationResult con is_valid=True si pasa todas las reglas,
    o is_valid=False con el motivo de descarte.

    Motivos posibles:
        - missing_required_fields: faltan titulo, precio o source_id
        - unknown_model: modelo no reconocido del segmento
        - year_out_of_range: año fuera de [year_min, year_max]
        - missing_year: no se pudo determinar el año
        - mileage_out_of_range: km > km_max
        - missing_mileage: no se pudo determinar el kilometraje
        - missing_price: no tiene precio
    """
    # Campos requeridos minimos
    if not title:
        return ValidationResult(False, "missing_required_fields")

    if not price:
        return ValidationResult(False, "missing_price")

    # Modelo reconocido
    if not model_normalized:
        return ValidationResult(False, "unknown_model")

    if model_normalized not in segment.models:
        return ValidationResult(False, "unknown_model")

    # Año
    if year is None:
        return ValidationResult(False, "missing_year")

    if year < segment.year_min or year > segment.year_max:
        return ValidationResult(False, "year_out_of_range")

    # Kilometraje
    if km is None:
        return ValidationResult(False, "missing_mileage")

    if km > segment.km_max:
        return ValidationResult(False, "mileage_out_of_range")

    return ValidationResult(True)
