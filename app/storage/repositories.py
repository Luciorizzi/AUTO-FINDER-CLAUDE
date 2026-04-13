"""Repositorios con operaciones sobre las tablas principales.

Contiene upsert de listings, creacion de snapshots, gestion de run_logs
y operaciones de normalizacion (Fase 3).
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.parsers.listing_parser import ListingDetail
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Run Logs ---

def create_run_log(conn: sqlite3.Connection, notes: Optional[str] = None) -> int:
    """Crea un registro de ejecucion y retorna su ID."""
    cursor = conn.execute(
        "INSERT INTO run_logs (notes) VALUES (?)",
        (notes,),
    )
    conn.commit()
    run_id = cursor.lastrowid
    logger.debug("Run log creado: id=%d", run_id)
    return run_id


def finish_run_log(
    conn: sqlite3.Connection,
    run_id: int,
    status: str = "completed",
    listings_found: int = 0,
    opportunities_found: int = 0,
    errors: int = 0,
    notes: Optional[str] = None,
) -> None:
    """Marca un run log como finalizado."""
    if notes:
        conn.execute(
            """UPDATE run_logs
               SET finished_at = ?, status = ?,
                   listings_found = ?, opportunities_found = ?, errors = ?,
                   notes = COALESCE(notes || ' | ', '') || ?
               WHERE id = ?""",
            (_now_utc(), status, listings_found, opportunities_found, errors, notes, run_id),
        )
    else:
        conn.execute(
            """UPDATE run_logs
               SET finished_at = ?, status = ?,
                   listings_found = ?, opportunities_found = ?, errors = ?
               WHERE id = ?""",
            (_now_utc(), status, listings_found, opportunities_found, errors, run_id),
        )
    conn.commit()
    logger.debug("Run log finalizado: id=%d status=%s", run_id, status)


def get_run_log(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    """Retorna un run log por ID."""
    cursor = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


# --- Listings ---

def count_listings(conn: sqlite3.Connection) -> int:
    """Retorna la cantidad total de listings."""
    cursor = conn.execute("SELECT count(*) as cnt FROM listings")
    return cursor.fetchone()["cnt"]


def count_active_listings(conn: sqlite3.Connection) -> int:
    """Retorna la cantidad de listings activos."""
    cursor = conn.execute("SELECT count(*) as cnt FROM listings WHERE is_active = 1")
    return cursor.fetchone()["cnt"]


def get_listing_by_source_id(conn: sqlite3.Connection, source_id: str) -> Optional[dict]:
    """Busca un listing por su source_id (ej: MLA1234567)."""
    cursor = conn.execute("SELECT * FROM listings WHERE source_id = ?", (source_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def upsert_listing(
    conn: sqlite3.Connection,
    detail: ListingDetail,
    search_query: Optional[str] = None,
    search_position: Optional[int] = None,
    search_page: int = 1,
    preview_price: Optional[float] = None,
    preview_currency: Optional[str] = None,
    preview_financing_flag: bool = False,
    preview_priority_score: Optional[float] = None,
    selected_for_detail: bool = False,
) -> int:
    """Inserta o actualiza un listing. Retorna el ID del registro."""
    existing = get_listing_by_source_id(conn, detail.source_id)

    if existing:
        # Los campos de search_* se setean solo la primera vez.
        # Actualizamos el score de prioridad del preview porque puede cambiar
        # entre corridas y sirve para auditar la ultima decision.
        conn.execute(
            """UPDATE listings
               SET price = COALESCE(?, price),
                   currency = COALESCE(?, currency),
                   km = COALESCE(?, km),
                   location = COALESCE(?, location),
                   seller_type = COALESCE(?, seller_type),
                   preview_priority_score = COALESCE(?, preview_priority_score),
                   selected_for_detail = CASE WHEN ? = 1 THEN 1 ELSE selected_for_detail END,
                   last_seen_at = datetime('now'),
                   is_active = 1
               WHERE source_id = ?""",
            (
                detail.price,
                detail.currency,
                detail.km,
                detail.location,
                detail.seller_type,
                preview_priority_score,
                1 if selected_for_detail else 0,
                detail.source_id,
            ),
        )
        conn.commit()
        listing_id = existing["id"]
        logger.debug("Listing actualizado: source_id=%s, id=%d", detail.source_id, listing_id)
    else:
        cursor = conn.execute(
            """INSERT INTO listings
               (source_id, source, url, title, model_raw, year, km,
                price, currency, location, seller_type,
                search_query, search_position, search_page,
                preview_price, preview_currency,
                preview_financing_flag, preview_priority_score, selected_for_detail,
                extraction_timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                detail.source_id,
                detail.source,
                detail.url,
                detail.title or "",
                detail.model_raw,
                detail.year,
                detail.km,
                detail.price,
                detail.currency,
                detail.location,
                detail.seller_type,
                search_query,
                search_position,
                search_page,
                preview_price,
                preview_currency,
                1 if preview_financing_flag else 0,
                preview_priority_score,
                1 if selected_for_detail else 0,
            ),
        )
        conn.commit()
        listing_id = cursor.lastrowid
        logger.debug("Listing insertado: source_id=%s, id=%d", detail.source_id, listing_id)

    return listing_id


def get_existing_source_ids(conn: sqlite3.Connection) -> set[str]:
    """Retorna el set de source_ids ya existentes en la DB."""
    cursor = conn.execute("SELECT source_id FROM listings")
    return {row["source_id"] for row in cursor.fetchall()}


# --- Snapshots ---

def create_snapshot(
    conn: sqlite3.Connection,
    listing_id: int,
    price: Optional[float],
    currency: str = "ARS",
    km: Optional[int] = None,
) -> int:
    """Crea un snapshot historico de precio/km para un listing."""
    cursor = conn.execute(
        "INSERT INTO listing_snapshots (listing_id, price, currency, km) VALUES (?, ?, ?, ?)",
        (listing_id, price, currency, km),
    )
    conn.commit()
    return cursor.lastrowid


def get_snapshots_for_listing(conn: sqlite3.Connection, listing_id: int) -> list[dict]:
    """Retorna todos los snapshots de un listing ordenados por fecha."""
    cursor = conn.execute(
        "SELECT * FROM listing_snapshots WHERE listing_id = ? ORDER BY captured_at",
        (listing_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def count_snapshots(conn: sqlite3.Connection) -> int:
    """Retorna la cantidad total de snapshots."""
    cursor = conn.execute("SELECT count(*) as cnt FROM listing_snapshots")
    return cursor.fetchone()["cnt"]


def persist_listing_detail(
    conn: sqlite3.Connection,
    detail: ListingDetail,
    search_query: Optional[str] = None,
    search_position: Optional[int] = None,
    search_page: int = 1,
    preview_price: Optional[float] = None,
    preview_currency: Optional[str] = None,
    preview_financing_flag: bool = False,
    preview_priority_score: Optional[float] = None,
    selected_for_detail: bool = False,
) -> int:
    """Persiste un listing y crea su snapshot en una operacion."""
    listing_id = upsert_listing(
        conn, detail,
        search_query=search_query,
        search_position=search_position,
        search_page=search_page,
        preview_price=preview_price,
        preview_currency=preview_currency,
        preview_financing_flag=preview_financing_flag,
        preview_priority_score=preview_priority_score,
        selected_for_detail=selected_for_detail,
    )
    create_snapshot(conn, listing_id, detail.price, detail.currency, detail.km)
    return listing_id


# --- Normalizacion (Fase 3) ---

def get_listings_pending_normalization(
    conn: sqlite3.Connection,
    limit: int = 200,
) -> list[dict]:
    """Retorna listings activos que no fueron normalizados todavia."""
    cursor = conn.execute(
        """SELECT * FROM listings
           WHERE is_active = 1 AND normalized_at IS NULL
           ORDER BY id
           LIMIT ?""",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_all_normalized_valid(conn: sqlite3.Connection) -> list[dict]:
    """Retorna todos los listings validos ya normalizados (para dedup)."""
    cursor = conn.execute(
        """SELECT id, model_normalized, year, km, price, title
           FROM listings
           WHERE is_valid_segment = 1
             AND duplicate_of IS NULL
           ORDER BY id"""
    )
    return [dict(row) for row in cursor.fetchall()]


def update_normalization(
    conn: sqlite3.Connection,
    listing_id: int,
    model_normalized: Optional[str],
    brand: Optional[str],
    is_valid_segment: bool,
    invalid_reason: Optional[str] = None,
    duplicate_of: Optional[int] = None,
) -> None:
    """Actualiza los campos de normalizacion de un listing."""
    conn.execute(
        """UPDATE listings
           SET model_normalized = ?,
               brand = ?,
               is_valid_segment = ?,
               invalid_reason = ?,
               duplicate_of = ?,
               normalized_at = datetime('now')
           WHERE id = ?""",
        (
            model_normalized,
            brand,
            1 if is_valid_segment else 0,
            invalid_reason,
            duplicate_of,
            listing_id,
        ),
    )
    conn.commit()


def get_normalization_summary(conn: sqlite3.Connection) -> dict:
    """Retorna un resumen de la normalizacion actual."""
    total = conn.execute("SELECT count(*) as c FROM listings").fetchone()["c"]
    normalized = conn.execute(
        "SELECT count(*) as c FROM listings WHERE normalized_at IS NOT NULL"
    ).fetchone()["c"]
    valid = conn.execute(
        "SELECT count(*) as c FROM listings WHERE is_valid_segment = 1"
    ).fetchone()["c"]
    invalid = conn.execute(
        "SELECT count(*) as c FROM listings WHERE is_valid_segment = 0"
    ).fetchone()["c"]
    duplicates = conn.execute(
        "SELECT count(*) as c FROM listings WHERE duplicate_of IS NOT NULL"
    ).fetchone()["c"]

    # Motivos de descarte
    reasons_cursor = conn.execute(
        """SELECT invalid_reason, count(*) as c
           FROM listings
           WHERE is_valid_segment = 0 AND invalid_reason IS NOT NULL
           GROUP BY invalid_reason
           ORDER BY c DESC"""
    )
    reasons = {row["invalid_reason"]: row["c"] for row in reasons_cursor.fetchall()}

    # Modelos encontrados
    models_cursor = conn.execute(
        """SELECT model_normalized, count(*) as c
           FROM listings
           WHERE is_valid_segment = 1 AND model_normalized IS NOT NULL
           GROUP BY model_normalized
           ORDER BY c DESC"""
    )
    models = {row["model_normalized"]: row["c"] for row in models_cursor.fetchall()}

    return {
        "total": total,
        "normalized": normalized,
        "valid": valid,
        "invalid": invalid,
        "duplicates": duplicates,
        "invalid_reasons": reasons,
        "valid_models": models,
    }


# --- Pricing (Fase 4) ---

def get_listings_for_pricing(
    conn: sqlite3.Connection,
    limit: int = 200,
) -> list[dict]:
    """Retorna listings validos y no duplicados pendientes de analisis de pricing.

    Un listing esta 'pendiente' si no tiene un registro en pricing_analyses
    o si fue re-normalizado despues del ultimo analisis.
    """
    cursor = conn.execute(
        """SELECT l.*
           FROM listings l
           LEFT JOIN pricing_analyses pa ON pa.listing_id = l.id
           WHERE l.is_valid_segment = 1
             AND l.duplicate_of IS NULL
             AND l.price IS NOT NULL
             AND l.km IS NOT NULL
             AND (pa.id IS NULL OR l.normalized_at > pa.analyzed_at)
           ORDER BY l.id
           LIMIT ?""",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def update_financing_flags(
    conn: sqlite3.Connection,
    listing_id: int,
    is_financing: bool,
    is_down_payment: bool,
    is_total_price_confident: bool,
) -> None:
    """Actualiza los flags de financiamiento de un listing."""
    conn.execute(
        """UPDATE listings
           SET is_financing = ?,
               is_down_payment = ?,
               is_total_price_confident = ?
           WHERE id = ?""",
        (
            1 if is_financing else 0,
            1 if is_down_payment else 0,
            1 if is_total_price_confident else 0,
            listing_id,
        ),
    )
    conn.commit()


def save_pricing_analysis(
    conn: sqlite3.Connection,
    listing_id: int,
    published_price: Optional[float],
    fair_price: Optional[float],
    gap_pct: Optional[float],
    opportunity_level: Optional[str],
    anomaly_risk: Optional[str],
    anomaly_reasons: Optional[str],
    comparables_found: int,
    comparables_used: int,
    min_comparable_price: Optional[float],
    max_comparable_price: Optional[float],
    median_comparable_price: Optional[float],
    p25_comparable_price: Optional[float],
    pricing_status: str,
    is_dominated: bool = False,
    dominated_by_listing_id: Optional[int] = None,
    dominance_reason: Optional[str] = None,
    comparable_level: Optional[str] = None,
    currency_used: Optional[str] = None,
    # Fase 4.2: local rank
    local_price_rank: Optional[int] = None,
    local_group_size: int = 0,
    local_price_percentile: Optional[float] = None,
    is_top_local_price_1: bool = False,
    is_top_local_price_3: bool = False,
    # Fase 4.2: freshness
    freshness_bucket: Optional[str] = None,
    freshness_boost: float = 0.0,
    days_on_market: Optional[int] = None,
    # Fase 4.2: price history
    initial_price: Optional[float] = None,
    current_price: Optional[float] = None,
    price_change_count: int = 0,
    markdown_abs: Optional[float] = None,
    markdown_pct: Optional[float] = None,
    markdown_bonus: float = 0.0,
    # Fase 4.2: priority score
    price_edge_score: float = 0.0,
    local_rank_bonus: float = 0.0,
    dominance_penalty: float = 0.0,
    anomaly_penalty: float = 0.0,
    final_priority_score: Optional[float] = None,
    final_priority_level: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Persiste un resultado de analisis de pricing con priority score (Fase 4.2)."""
    cursor = conn.execute(
        """INSERT INTO pricing_analyses
           (listing_id, published_price, fair_price, gap_pct,
            opportunity_level, anomaly_risk, anomaly_reasons,
            comparables_found, comparables_used,
            min_comparable_price, max_comparable_price,
            median_comparable_price, p25_comparable_price,
            is_dominated, dominated_by_listing_id, dominance_reason,
            comparable_level, currency_used,
            local_price_rank, local_group_size, local_price_percentile,
            is_top_local_price_1, is_top_local_price_3,
            freshness_bucket, freshness_boost, days_on_market,
            initial_price, current_price, price_change_count,
            markdown_abs, markdown_pct, markdown_bonus,
            price_edge_score, local_rank_bonus,
            dominance_penalty, anomaly_penalty,
            final_priority_score, final_priority_level,
            pricing_status, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            listing_id, published_price, fair_price, gap_pct,
            opportunity_level, anomaly_risk, anomaly_reasons,
            comparables_found, comparables_used,
            min_comparable_price, max_comparable_price,
            median_comparable_price, p25_comparable_price,
            1 if is_dominated else 0, dominated_by_listing_id, dominance_reason,
            comparable_level, currency_used,
            local_price_rank, local_group_size, local_price_percentile,
            1 if is_top_local_price_1 else 0, 1 if is_top_local_price_3 else 0,
            freshness_bucket, freshness_boost, days_on_market,
            initial_price, current_price, price_change_count,
            markdown_abs, markdown_pct, markdown_bonus,
            price_edge_score, local_rank_bonus,
            dominance_penalty, anomaly_penalty,
            final_priority_score, final_priority_level,
            pricing_status, notes,
        ),
    )
    conn.commit()
    logger.debug(
        "Pricing analysis guardado: listing_id=%d, status=%s, priority=%s score=%s",
        listing_id, pricing_status, final_priority_level, final_priority_score,
    )
    return cursor.lastrowid


def get_pricing_summary(conn: sqlite3.Connection) -> dict:
    """Retorna un resumen del estado de pricing."""
    total = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses"
    ).fetchone()["c"]

    enough = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE pricing_status = 'enough_data'"
    ).fetchone()["c"]

    insufficient = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE pricing_status = 'insufficient_data'"
    ).fetchone()["c"]

    no_data = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE pricing_status = 'no_data'"
    ).fetchone()["c"]

    strong = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE opportunity_level = 'strong_opportunity'"
    ).fetchone()["c"]

    medium = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE opportunity_level = 'medium_opportunity'"
    ).fetchone()["c"]

    high_risk = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE anomaly_risk = 'alto'"
    ).fetchone()["c"]

    errors = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE pricing_status = 'error'"
    ).fetchone()["c"]

    dominated = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE is_dominated = 1"
    ).fetchone()["c"]

    financing = conn.execute(
        "SELECT count(*) as c FROM listings WHERE is_financing = 1 OR is_down_payment = 1"
    ).fetchone()["c"]

    # Fase 4.2: prioridad operativa
    urgent = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE final_priority_level = 'urgent_review'"
    ).fetchone()["c"]
    high_pri = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE final_priority_level = 'high_priority'"
    ).fetchone()["c"]
    top_local = conn.execute(
        "SELECT count(*) as c FROM pricing_analyses WHERE is_top_local_price_1 = 1"
    ).fetchone()["c"]

    return {
        "total_analyzed": total,
        "enough_data": enough,
        "insufficient_data": insufficient,
        "no_data": no_data,
        "strong_opportunities": strong,
        "medium_opportunities": medium,
        "high_risk": high_risk,
        "dominated": dominated,
        "financing_excluded": financing,
        "urgent_review": urgent,
        "high_priority": high_pri,
        "top_local_1": top_local,
        "errors": errors,
    }


# --- Alertas enviadas (Fase 5) ---

def get_alertable_listings(
    conn: sqlite3.Connection,
    priority_levels: list[str],
) -> list[dict]:
    """Retorna listings elegibles para alertar con su pricing más reciente.

    Un listing es elegible si:
    - tiene pricing_analyses con final_priority_level en los niveles dados
    - está activo
    - es válido para el segmento
    - no está duplicado
    - no es financiamiento

    Returns:
        Lista de dicts con campos de listings + pricing_analyses (JOIN).
    """
    placeholders = ",".join("?" for _ in priority_levels)
    cursor = conn.execute(
        f"""SELECT l.*, pa.*,
                   l.id as listing_id,
                   pa.id as pricing_id
            FROM listings l
            INNER JOIN pricing_analyses pa ON pa.listing_id = l.id
            WHERE pa.final_priority_level IN ({placeholders})
              AND l.is_active = 1
              AND l.is_valid_segment = 1
              AND l.duplicate_of IS NULL
              AND (l.is_financing = 0 AND l.is_down_payment = 0)
              AND pa.pricing_status = 'enough_data'
            ORDER BY pa.final_priority_score DESC""",
        priority_levels,
    )
    return [dict(row) for row in cursor.fetchall()]


def get_last_successful_alert(
    conn: sqlite3.Connection,
    listing_id: int,
) -> Optional[dict]:
    """Retorna la última alerta exitosa enviada para un listing."""
    cursor = conn.execute(
        """SELECT * FROM sent_alerts
           WHERE listing_id = ?
             AND send_status = 'sent'
             AND is_dry_run = 0
           ORDER BY sent_at DESC
           LIMIT 1""",
        (listing_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def save_sent_alert(
    conn: sqlite3.Connection,
    listing_id: int,
    message_fingerprint: str,
    alert_reason: str,
    *,
    channel: str = "telegram",
    telegram_chat_id: Optional[str] = None,
    sent_price: Optional[float] = None,
    sent_currency: Optional[str] = None,
    sent_opportunity_level: Optional[str] = None,
    sent_final_priority_level: Optional[str] = None,
    sent_final_priority_score: Optional[float] = None,
    sent_fair_price: Optional[float] = None,
    sent_gap_pct: Optional[float] = None,
    send_status: str = "sent",
    send_error: Optional[str] = None,
    telegram_message_id: Optional[int] = None,
    is_dry_run: bool = False,
) -> int:
    """Persiste un registro de alerta enviada (o intentada)."""
    cursor = conn.execute(
        """INSERT INTO sent_alerts
           (listing_id, channel, telegram_chat_id, message_fingerprint,
            sent_price, sent_currency, sent_opportunity_level,
            sent_final_priority_level, sent_final_priority_score,
            sent_fair_price, sent_gap_pct,
            send_status, send_error, telegram_message_id,
            alert_reason, is_dry_run)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            listing_id, channel, telegram_chat_id, message_fingerprint,
            sent_price, sent_currency, sent_opportunity_level,
            sent_final_priority_level, sent_final_priority_score,
            sent_fair_price, sent_gap_pct,
            send_status, send_error, telegram_message_id,
            alert_reason, 1 if is_dry_run else 0,
        ),
    )
    conn.commit()
    logger.debug(
        "Alerta registrada: listing_id=%d reason=%s status=%s dry=%s",
        listing_id, alert_reason, send_status, is_dry_run,
    )
    return cursor.lastrowid


def get_alert_summary(conn: sqlite3.Connection) -> dict:
    """Resumen de alertas enviadas."""
    total = conn.execute(
        "SELECT count(*) as c FROM sent_alerts"
    ).fetchone()["c"]
    sent_ok = conn.execute(
        "SELECT count(*) as c FROM sent_alerts WHERE send_status = 'sent' AND is_dry_run = 0"
    ).fetchone()["c"]
    failed = conn.execute(
        "SELECT count(*) as c FROM sent_alerts WHERE send_status = 'failed'"
    ).fetchone()["c"]
    dry = conn.execute(
        "SELECT count(*) as c FROM sent_alerts WHERE is_dry_run = 1"
    ).fetchone()["c"]
    return {
        "total": total,
        "sent_ok": sent_ok,
        "failed": failed,
        "dry_run": dry,
    }
