"""Clasificacion de riesgo de anomalia.

Evalua si un resultado de pricing es confiable o sospechoso
usando reglas simples y explicitas.

Niveles de riesgo:
- bajo: datos suficientes y consistentes
- medio: datos parciales o alguna inconsistencia menor
- alto: datos insuficientes, gap extremo o inconsistencias fuertes

Razones posibles:
- insufficient_comparables: menos del minimo de comparables
- extreme_gap: gap sospechosamente bajo (posible error de precio)
- wide_price_dispersion: CV alto indica mercado inconsistente
- missing_key_fields: faltan datos criticos para el analisis
- too_few_after_outlier: muchos outliers removidos
"""

from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Niveles
RISK_LOW = "bajo"
RISK_MEDIUM = "medio"
RISK_HIGH = "alto"


@dataclass
class AnomalyResult:
    """Resultado de la evaluacion de riesgo."""
    risk_level: str = RISK_HIGH
    reasons: list[str] = field(default_factory=list)


def assess_anomaly_risk(
    comparables_found: int,
    comparables_used: int,
    gap_pct: Optional[float],
    cv: Optional[float],
    pricing_status: str,
    published_price: Optional[float] = None,
    km: Optional[int] = None,
    low_min_comparables: int = 8,
    medium_min_comparables: int = 5,
    extreme_gap_pct: float = -30.0,
    max_cv: float = 0.40,
) -> AnomalyResult:
    """Evalua el riesgo de anomalia de un analisis de pricing.

    Criterios:
    1. Cantidad de comparables (bajo/medio/alto)
    2. Gap extremamente negativo (sospechoso)
    3. Dispersion alta de precios (mercado inconsistente)
    4. Datos faltantes criticos
    5. Muchos outliers removidos (señal de heterogeneidad)

    Args:
        comparables_found: Comparables encontrados antes de filtrar.
        comparables_used: Comparables usados despues de filtrar outliers.
        gap_pct: Gap porcentual calculado.
        cv: Coeficiente de variacion de los precios.
        pricing_status: Estado del pricing (enough_data/insufficient_data/no_data).
        published_price: Precio publicado (para validar existencia).
        km: Kilometraje (para validar existencia).
        low_min_comparables: Minimo para riesgo bajo.
        medium_min_comparables: Minimo para riesgo medio.
        extreme_gap_pct: Gap debajo del cual se sospecha anomalia.
        max_cv: CV maximo aceptable sin levantar alerta.

    Returns:
        AnomalyResult con nivel de riesgo y razones.
    """
    result = AnomalyResult()
    risk_score = 0  # Acumulador: 0=bajo, 1-2=medio, 3+=alto

    # 1. Datos faltantes criticos
    if published_price is None or km is None:
        result.reasons.append("missing_key_fields")
        risk_score += 3

    # 2. Estado del pricing
    if pricing_status == "no_data":
        result.reasons.append("insufficient_comparables")
        risk_score += 3
    elif pricing_status == "insufficient_data":
        result.reasons.append("insufficient_comparables")
        risk_score += 2

    # 3. Cantidad de comparables
    if comparables_used < medium_min_comparables:
        if "insufficient_comparables" not in result.reasons:
            result.reasons.append("insufficient_comparables")
        risk_score += 2
    elif comparables_used < low_min_comparables:
        risk_score += 1

    # 4. Gap extremo sospechoso
    if gap_pct is not None and gap_pct < extreme_gap_pct:
        result.reasons.append("extreme_gap")
        risk_score += 2

    # 5. Dispersion alta
    if cv is not None and cv > max_cv:
        result.reasons.append("wide_price_dispersion")
        risk_score += 1

    # 6. Muchos outliers removidos (> 30% de los encontrados)
    if comparables_found > 0:
        outlier_ratio = (comparables_found - comparables_used) / comparables_found
        if outlier_ratio > 0.30 and comparables_found >= 4:
            result.reasons.append("too_few_after_outlier")
            risk_score += 1

    # Clasificar
    if risk_score >= 3:
        result.risk_level = RISK_HIGH
    elif risk_score >= 1:
        result.risk_level = RISK_MEDIUM
    else:
        result.risk_level = RISK_LOW

    logger.debug(
        "Riesgo: %s (score=%d, reasons=%s, comparables=%d/%d, gap=%s, cv=%s)",
        result.risk_level, risk_score, result.reasons,
        comparables_used, comparables_found,
        f"{gap_pct:.1f}%" if gap_pct else "N/A",
        f"{cv:.3f}" if cv else "N/A",
    )

    return result
