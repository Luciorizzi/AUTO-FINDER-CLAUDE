"""Deduplicación de alertas enviadas.

Decide si una alerta debe enviarse o no, comparando el estado actual
del listing con la última alerta enviada exitosamente.

Fingerprint = combinación de (listing_id, price, opportunity_level, final_priority_level).
Si el fingerprint no cambió desde el último envío exitoso, no se reenvía.

Razones de reenvío:
- new_match: no hay alerta previa exitosa para este listing
- price_drop: el precio bajó respecto al último envío
- priority_upgrade: subió de final_priority_level
- opportunity_upgrade: subió de opportunity_level
"""

import hashlib
from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Orden de prioridad de mayor a menor (para comparar upgrades)
_PRIORITY_ORDER = {
    "urgent_review": 0,
    "high_priority": 1,
    "medium_priority": 2,
    "low_priority": 3,
}

_OPPORTUNITY_ORDER = {
    "strong_opportunity": 0,
    "medium_opportunity": 1,
    "not_opportunity": 2,
}


@dataclass
class DedupDecision:
    """Resultado de la evaluación de deduplicación."""
    should_send: bool
    reason: str  # new_match | price_drop | priority_upgrade | opportunity_upgrade | duplicate


def build_alert_fingerprint(
    listing_id: int,
    price: Optional[float],
    opportunity_level: Optional[str],
    final_priority_level: Optional[str],
) -> str:
    """Construye un fingerprint determinístico para una alerta.

    El fingerprint cambia si cambia cualquiera de los componentes.
    Se usa para detectar si "algo relevante cambió" entre corridas.

    Args:
        listing_id: ID del listing en la DB.
        price: Precio actual.
        opportunity_level: Nivel de oportunidad actual.
        final_priority_level: Nivel de prioridad actual.

    Returns:
        Hash SHA256 truncado a 16 chars (suficiente para dedup).
    """
    raw = f"{listing_id}|{price}|{opportunity_level}|{final_priority_level}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def evaluate_dedup(
    listing_id: int,
    current_price: Optional[float],
    current_opportunity: Optional[str],
    current_priority: Optional[str],
    last_sent: Optional[dict],
    *,
    resend_on_price_change: bool = True,
    resend_on_priority_upgrade: bool = True,
    resend_on_opportunity_upgrade: bool = True,
) -> DedupDecision:
    """Evalúa si una alerta debe enviarse o es duplicada.

    Args:
        listing_id: ID del listing.
        current_price: Precio actual del listing.
        current_opportunity: Nivel de oportunidad actual.
        current_priority: Nivel de prioridad actual.
        last_sent: Dict con la última alerta exitosa para este listing,
                   o None si no hay historial. Espera keys:
                   sent_price, sent_opportunity_level, sent_final_priority_level.
        resend_on_price_change: Reenviar si bajó el precio.
        resend_on_priority_upgrade: Reenviar si subió la prioridad.
        resend_on_opportunity_upgrade: Reenviar si subió la oportunidad.

    Returns:
        DedupDecision con should_send y reason.
    """
    # Sin historial → es nuevo
    if last_sent is None:
        return DedupDecision(should_send=True, reason="new_match")

    sent_price = last_sent.get("sent_price")
    sent_opp = last_sent.get("sent_opportunity_level")
    sent_prio = last_sent.get("sent_final_priority_level")

    # Comparar fingerprints rápidamente
    current_fp = build_alert_fingerprint(
        listing_id, current_price, current_opportunity, current_priority
    )
    sent_fp = build_alert_fingerprint(listing_id, sent_price, sent_opp, sent_prio)

    if current_fp == sent_fp:
        return DedupDecision(should_send=False, reason="duplicate")

    # Algo cambió → determinar qué
    # 1. Bajó el precio
    if (
        resend_on_price_change
        and current_price is not None
        and sent_price is not None
        and current_price < sent_price
    ):
        logger.debug(
            "listing_id=%d: price_drop %.0f -> %.0f",
            listing_id, sent_price, current_price,
        )
        return DedupDecision(should_send=True, reason="price_drop")

    # 2. Subió la prioridad
    if resend_on_priority_upgrade:
        cur_rank = _PRIORITY_ORDER.get(current_priority or "", 99)
        sent_rank = _PRIORITY_ORDER.get(sent_prio or "", 99)
        if cur_rank < sent_rank:
            logger.debug(
                "listing_id=%d: priority_upgrade %s -> %s",
                listing_id, sent_prio, current_priority,
            )
            return DedupDecision(should_send=True, reason="priority_upgrade")

    # 3. Subió la oportunidad
    if resend_on_opportunity_upgrade:
        cur_rank = _OPPORTUNITY_ORDER.get(current_opportunity or "", 99)
        sent_rank = _OPPORTUNITY_ORDER.get(sent_opp or "", 99)
        if cur_rank < sent_rank:
            logger.debug(
                "listing_id=%d: opportunity_upgrade %s -> %s",
                listing_id, sent_opp, current_opportunity,
            )
            return DedupDecision(should_send=True, reason="opportunity_upgrade")

    # Cambió algo pero no en una dirección que justifique reenvío
    # (ej: precio subió, o prioridad bajó)
    return DedupDecision(should_send=False, reason="duplicate")
