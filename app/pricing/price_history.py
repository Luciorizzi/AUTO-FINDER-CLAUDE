"""Senales del historial de precio extraidas de listing_snapshots.

Aprovecha los snapshots historicos para detectar:
- precio inicial conocido (primer snapshot)
- precio actual (ultimo snapshot o listing.price)
- cantidad de snapshots
- cambios de precio detectados
- rebaja absoluta y porcentual vs precio inicial
- days_on_market aproximado (entre primer y ultimo snapshot)

Esto permite distinguir entre:
- recien publicado y barato (alta urgencia)
- publicado hace tiempo pero con rebaja reciente (interesante)
- publicado hace mucho sin movimientos (menor prioridad)
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.pricing.freshness import _parse_timestamp
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PriceHistoryResult:
    """Senales historicas de precio para un listing."""
    initial_price: Optional[float] = None
    current_price: Optional[float] = None
    snapshot_count: int = 0
    price_change_count: int = 0
    markdown_abs: Optional[float] = None
    markdown_pct: Optional[float] = None
    history_days_on_market: Optional[int] = None
    has_markdown: bool = False


def compute_price_history(
    conn: sqlite3.Connection,
    listing_id: int,
    current_price: Optional[float] = None,
    now: Optional[datetime] = None,
) -> PriceHistoryResult:
    """Calcula senales historicas de precio desde listing_snapshots.

    Args:
        conn: Conexion SQLite.
        listing_id: ID del listing target.
        current_price: Precio actual (del listing). Si es None, se usa
            el ultimo snapshot.
        now: Timestamp actual (para tests reproducibles).

    Returns:
        PriceHistoryResult con senales historicas.
    """
    result = PriceHistoryResult()

    try:
        cursor = conn.execute(
            """SELECT price, captured_at
               FROM listing_snapshots
               WHERE listing_id = ?
               ORDER BY captured_at ASC""",
            (listing_id,),
        )
        snapshots = [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.debug("Error leyendo snapshots de listing %d: %s", listing_id, e)
        return result

    result.snapshot_count = len(snapshots)

    if not snapshots:
        result.current_price = current_price
        return result

    # Precios validos para comparacion
    priced = [s for s in snapshots if s.get("price") is not None]
    if not priced:
        result.current_price = current_price
        return result

    result.initial_price = priced[0]["price"]
    result.current_price = current_price if current_price is not None else priced[-1]["price"]

    # Contar cambios de precio (entre snapshots consecutivos)
    changes = 0
    prev_price = None
    for snap in priced:
        p = snap["price"]
        if prev_price is not None and p != prev_price:
            changes += 1
        prev_price = p
    result.price_change_count = changes

    # Markdown vs inicial
    if result.initial_price and result.initial_price > 0 and result.current_price is not None:
        abs_change = result.current_price - result.initial_price
        pct_change = (abs_change / result.initial_price) * 100
        result.markdown_abs = round(abs_change, 2)
        result.markdown_pct = round(pct_change, 2)
        # Solo contamos rebaja (negativo)
        result.has_markdown = pct_change < 0

    # Days on market segun snapshots
    first_ts = _parse_timestamp(snapshots[0].get("captured_at"))
    if first_ts is not None:
        current = now or datetime.now(timezone.utc)
        delta_days = (current - first_ts).total_seconds() / 86400.0
        result.history_days_on_market = max(0, int(delta_days))

    logger.debug(
        "History listing=%d: snaps=%d changes=%d markdown_pct=%s dom=%s",
        listing_id, result.snapshot_count, result.price_change_count,
        result.markdown_pct, result.history_days_on_market,
    )

    return result
