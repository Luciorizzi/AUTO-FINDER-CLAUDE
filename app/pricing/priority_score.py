"""Score final de prioridad operativa (Fase 4.2).

Separa dos conceptos distintos:

A) VALORACION ECONOMICA (opportunity_level):
   - fair_price (mediana de comparables)
   - gap_pct vs fair_price
   - clasifica: strong_opportunity / medium_opportunity / not_opportunity
   - responde: "este auto es barato vs el mercado?"

B) PRIORIDAD OPERATIVA (final_priority_level):
   - combina gap con senales de contexto:
     - ranking local dentro del microgrupo real
     - frescura de la publicacion
     - rebajas recientes de precio
     - penalizacion por dominancia
     - penalizacion por riesgo alto de anomalia
   - clasifica: urgent_review / high_priority / medium_priority / low_priority
   - responde: "cual conviene mirar primero?"

Formula (reglas claras, auditables):

    price_edge_score   = clamp(-gap_pct, 0, price_edge_cap)
    local_rank_bonus   = top1_bonus si is_top1
                         else top3_bonus si is_top3
                         else 0
    freshness_boost    = boost del bucket de freshness
    markdown_bonus     = bonus si hay rebaja >= significant_pct
    dominance_penalty  = penalty si is_dominated
    anomaly_penalty    = penalty si anomaly_risk == "alto"

    final_priority_score =
        price_edge_score
      + local_rank_bonus
      + freshness_boost
      + markdown_bonus
      - dominance_penalty
      - anomaly_penalty

Luego se mapea a niveles:
    urgent_review   si score >= urgent_threshold
                    Y no esta dominado
                    Y anomaly_risk != "alto"
    high_priority   si score >= high_threshold
    medium_priority si score >= medium_threshold
    low_priority    si no

Notas de diseno:
- Un listing dominado NUNCA puede ser urgent_review, aunque el score lo permita.
- Un listing con riesgo alto NUNCA puede ser urgent_review.
- medium_opportunity + recien publicado + top local = puede ser urgent_review.
- strong_opportunity + dominado = max high_priority, probablemente medium/low.
- Si fair_price o gap son None, price_edge_score = 0 (no rompe).
"""

from dataclasses import dataclass
from typing import Optional

from app.risk.anomaly_detector import RISK_HIGH
from app.utils.logger import get_logger

logger = get_logger(__name__)

URGENT_REVIEW = "urgent_review"
HIGH_PRIORITY = "high_priority"
MEDIUM_PRIORITY = "medium_priority"
LOW_PRIORITY = "low_priority"


@dataclass
class PriorityScoreResult:
    """Desglose completo del score de prioridad operativa."""
    price_edge_score: float = 0.0
    local_rank_bonus: float = 0.0
    freshness_boost: float = 0.0
    markdown_bonus: float = 0.0
    dominance_penalty: float = 0.0
    anomaly_penalty: float = 0.0
    final_priority_score: float = 0.0
    final_priority_level: str = LOW_PRIORITY


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_priority_score(
    gap_pct: Optional[float],
    is_top_local_price_1: bool,
    is_top_local_price_3: bool,
    freshness_boost: float,
    markdown_pct: Optional[float],
    is_dominated: bool,
    anomaly_risk: Optional[str],
    *,
    price_edge_cap: float = 40.0,
    local_top1_bonus: float = 30.0,
    local_top3_bonus: float = 15.0,
    markdown_significant_pct: float = 3.0,
    markdown_bonus: float = 20.0,
    dominance_penalty: float = 40.0,
    anomaly_high_penalty: float = 25.0,
    urgent_review_threshold: float = 70.0,
    high_priority_threshold: float = 45.0,
    medium_priority_threshold: float = 20.0,
) -> PriorityScoreResult:
    """Calcula el score final de prioridad operativa y su nivel.

    Ver docstring del modulo para la formula completa.

    Args:
        gap_pct: Gap porcentual (negativo = barato). Si es None, price_edge = 0.
        is_top_local_price_1: Es el mas barato del microgrupo.
        is_top_local_price_3: Esta entre los 3 mas baratos del microgrupo.
        freshness_boost: Boost ya calculado por el modulo freshness.
        markdown_pct: % de cambio de precio vs inicial (negativo = rebaja).
        is_dominated: Si esta dominado por otro comparable.
        anomaly_risk: Nivel de riesgo ("bajo", "medio", "alto").
        **thresholds y bonuses**: Parametros configurables.

    Returns:
        PriorityScoreResult con todos los componentes y el nivel final.
    """
    result = PriorityScoreResult()

    # --- 1. Price edge ---
    if gap_pct is not None:
        # gap_pct negativo = descuento. price_edge = magnitud del descuento capada.
        result.price_edge_score = _clamp(-gap_pct, 0.0, price_edge_cap)

    # --- 2. Local rank bonus ---
    if is_top_local_price_1:
        result.local_rank_bonus = local_top1_bonus
    elif is_top_local_price_3:
        result.local_rank_bonus = local_top3_bonus

    # --- 3. Freshness ---
    result.freshness_boost = max(0.0, freshness_boost)

    # --- 4. Markdown ---
    if markdown_pct is not None and markdown_pct <= -markdown_significant_pct:
        # Rebaja significativa (markdown_pct es negativo)
        result.markdown_bonus = markdown_bonus

    # --- 5. Penalizaciones ---
    if is_dominated:
        result.dominance_penalty = dominance_penalty

    if anomaly_risk == RISK_HIGH:
        result.anomaly_penalty = anomaly_high_penalty

    # --- Score final ---
    score = (
        result.price_edge_score
        + result.local_rank_bonus
        + result.freshness_boost
        + result.markdown_bonus
        - result.dominance_penalty
        - result.anomaly_penalty
    )
    result.final_priority_score = round(score, 2)

    # --- Mapeo a nivel con gates de seguridad ---
    level = _score_to_level(
        score,
        urgent_review_threshold,
        high_priority_threshold,
        medium_priority_threshold,
    )

    # Gates: dominado o riesgo alto NUNCA pueden ser urgent_review
    if level == URGENT_REVIEW and (is_dominated or anomaly_risk == RISK_HIGH):
        level = HIGH_PRIORITY

    # Dominado con score bajo, bajarlo un escalon extra para asegurar que
    # un auto objetivamente peor no quede arriba
    if is_dominated and level == HIGH_PRIORITY and score < high_priority_threshold + 10:
        level = MEDIUM_PRIORITY

    result.final_priority_level = level

    logger.debug(
        "Priority: edge=%.1f local=%.1f fresh=%.1f md=%.1f "
        "dom=-%.1f anom=-%.1f => score=%.1f level=%s",
        result.price_edge_score, result.local_rank_bonus,
        result.freshness_boost, result.markdown_bonus,
        result.dominance_penalty, result.anomaly_penalty,
        result.final_priority_score, result.final_priority_level,
    )

    return result


def _score_to_level(
    score: float,
    urgent: float,
    high: float,
    medium: float,
) -> str:
    """Mapea score numerico a nivel operativo."""
    if score >= urgent:
        return URGENT_REVIEW
    if score >= high:
        return HIGH_PRIORITY
    if score >= medium:
        return MEDIUM_PRIORITY
    return LOW_PRIORITY
