"""Formato de mensajes de alerta para Telegram.

Genera mensajes concisos, legibles en móvil, con toda la información
operativa necesaria para decidir rápidamente si un auto vale la pena.
"""

from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _fmt_price(price: Optional[float], currency: str = "ARS") -> str:
    """Formatea precio con separador de miles."""
    if price is None:
        return "N/A"
    formatted = f"{price:,.0f}".replace(",", ".")
    return f"{formatted} {currency}"


def _fmt_pct(value: Optional[float]) -> str:
    """Formatea porcentaje con signo."""
    if value is None:
        return "N/A"
    return f"{value:+.1f}%"


def _fmt_km(km: Optional[int]) -> str:
    if km is None:
        return "N/A"
    return f"{km:,}".replace(",", ".")


def _priority_emoji(level: Optional[str]) -> str:
    """Emoji por nivel de prioridad."""
    mapping = {
        "urgent_review": "🔴",
        "high_priority": "🟠",
        "medium_priority": "🟡",
        "low_priority": "⚪",
    }
    return mapping.get(level or "", "❓")


def _opportunity_emoji(level: Optional[str]) -> str:
    mapping = {
        "strong_opportunity": "🟢",
        "medium_opportunity": "🟡",
        "not_opportunity": "⚪",
    }
    return mapping.get(level or "", "❓")


def _alert_reason_label(reason: str) -> str:
    """Etiqueta legible para la razón de alerta."""
    labels = {
        "new_match": "🆕 Nuevo match",
        "price_drop": "💰 Baja de precio",
        "priority_upgrade": "⬆️ Subió prioridad",
        "opportunity_upgrade": "⬆️ Subió oportunidad",
    }
    return labels.get(reason, reason)


def format_alert_message(
    listing: dict[str, Any],
    pricing: dict[str, Any],
    alert_reason: str,
) -> str:
    """Construye el mensaje de alerta de Telegram.

    Args:
        listing: Row de la tabla listings (dict).
        pricing: Row de la tabla pricing_analyses (dict).
        alert_reason: Razón del envío (new_match, price_drop, etc.).

    Returns:
        Texto del mensaje formateado (HTML).
    """
    title = listing.get("title") or listing.get("model_raw") or "Sin título"
    price = listing.get("price")
    currency = pricing.get("currency_used") or listing.get("currency", "ARS")
    year = listing.get("year")
    km = listing.get("km")
    url = listing.get("url", "")

    opp_level = pricing.get("opportunity_level", "")
    priority_level = pricing.get("final_priority_level", "")
    priority_score = pricing.get("final_priority_score")
    fair_price = pricing.get("fair_price")
    gap_pct = pricing.get("gap_pct")
    freshness = pricing.get("freshness_bucket", "")

    reason_label = _alert_reason_label(alert_reason)
    p_emoji = _priority_emoji(priority_level)
    o_emoji = _opportunity_emoji(opp_level)

    lines = [
        f"🚗 <b>AUTO FINDER</b> — {reason_label}",
        "",
        f"<b>{title}</b>",
        f"Precio: <b>{_fmt_price(price, currency)}</b>",
        f"Año: {year or 'N/A'}  |  Km: {_fmt_km(km)}",
        "",
        f"{o_emoji} Opportunity: <b>{opp_level or 'N/A'}</b>",
        f"{p_emoji} Priority: <b>{priority_level or 'N/A'}</b>",
    ]

    if priority_score is not None:
        lines.append(f"Score: {priority_score:.1f}")

    if fair_price is not None:
        lines.append(f"Fair price: {_fmt_price(fair_price, currency)}")

    if gap_pct is not None:
        lines.append(f"Gap: <b>{_fmt_pct(gap_pct)}</b>")

    if freshness:
        lines.append(f"Freshness: {freshness}")

    lines.extend(["", url])

    return "\n".join(lines)
