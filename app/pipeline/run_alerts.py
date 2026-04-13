"""Pipeline de alertas: selecciona listings priorizados y envía por Telegram.

Flujo:
1. Lee listings elegibles (priority_level en niveles configurados).
2. Para cada uno, evalúa deduplicación contra historial de envíos.
3. Si corresponde enviar, construye mensaje y lo envía (o simula en dry_run).
4. Persiste resultado del envío para dedup futura y auditoría.
5. Genera resumen final.
"""

import sqlite3
from dataclasses import dataclass, field

from app.config import EnvSettings
from app.notifications.alert_dedup import (
    DedupDecision,
    build_alert_fingerprint,
    evaluate_dedup,
)
from app.notifications.alert_formatter import format_alert_message
from app.notifications.telegram_bot import TelegramSendResult, send_telegram_message
from app.storage.repositories import (
    get_alertable_listings,
    get_last_successful_alert,
    save_sent_alert,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AlertsSummary:
    """Resumen de ejecución del pipeline de alertas."""
    total_eligible: int = 0
    total_new: int = 0
    total_resent_price_drop: int = 0
    total_resent_priority_upgrade: int = 0
    total_resent_opportunity_upgrade: int = 0
    total_skipped_duplicate: int = 0
    total_sent_ok: int = 0
    total_failed: int = 0
    total_dry_run: int = 0
    errors: list[str] = field(default_factory=list)


def run_alerts_pipeline(
    conn: sqlite3.Connection,
    env: EnvSettings,
) -> AlertsSummary:
    """Ejecuta el pipeline completo de alertas.

    Args:
        conn: Conexión a SQLite.
        env: Configuración de entorno.

    Returns:
        AlertsSummary con métricas del lote.
    """
    summary = AlertsSummary()
    priority_levels = [
        lvl.strip() for lvl in env.alert_priority_levels.split(",") if lvl.strip()
    ]

    if not priority_levels:
        logger.warning("No hay niveles de prioridad configurados para alertas.")
        return summary

    # 1. Obtener listings elegibles
    eligible = get_alertable_listings(conn, priority_levels)
    summary.total_eligible = len(eligible)
    logger.info(
        "Alertas: %d listings elegibles (priority_levels=%s)",
        len(eligible), priority_levels,
    )

    if not eligible:
        return summary

    # 2. Procesar cada listing
    for row in eligible:
        listing_id = row["listing_id"]

        try:
            _process_single_alert(conn, row, env, summary)
        except Exception as e:
            logger.error(
                "Error procesando alerta para listing_id=%d: %s",
                listing_id, e, exc_info=True,
            )
            summary.errors.append(f"listing_id={listing_id}: {e}")

    # 3. Log resumen
    logger.info(
        "Alertas resumen: elegibles=%d nuevos=%d "
        "resent_price=%d resent_priority=%d resent_opportunity=%d "
        "duplicados=%d enviados_ok=%d fallidos=%d dry_run=%d",
        summary.total_eligible,
        summary.total_new,
        summary.total_resent_price_drop,
        summary.total_resent_priority_upgrade,
        summary.total_resent_opportunity_upgrade,
        summary.total_skipped_duplicate,
        summary.total_sent_ok,
        summary.total_failed,
        summary.total_dry_run,
    )

    return summary


def _process_single_alert(
    conn: sqlite3.Connection,
    row: dict,
    env: EnvSettings,
    summary: AlertsSummary,
) -> None:
    """Procesa la alerta de un listing individual."""
    listing_id = row["listing_id"]
    current_price = row.get("price")
    current_opp = row.get("opportunity_level")
    current_prio = row.get("final_priority_level")
    current_score = row.get("final_priority_score")
    fair_price = row.get("fair_price")
    gap_pct = row.get("gap_pct")
    currency = row.get("currency_used") or row.get("currency", "ARS")

    # 2a. Evaluar deduplicación
    last_sent = get_last_successful_alert(conn, listing_id)
    decision: DedupDecision = evaluate_dedup(
        listing_id=listing_id,
        current_price=current_price,
        current_opportunity=current_opp,
        current_priority=current_prio,
        last_sent=last_sent,
        resend_on_price_change=env.alert_resend_on_price_change,
        resend_on_priority_upgrade=env.alert_resend_on_priority_upgrade,
        resend_on_opportunity_upgrade=env.alert_resend_on_opportunity_upgrade,
    )

    if not decision.should_send:
        summary.total_skipped_duplicate += 1
        return

    # Contabilizar razón
    if decision.reason == "new_match":
        summary.total_new += 1
    elif decision.reason == "price_drop":
        summary.total_resent_price_drop += 1
    elif decision.reason == "priority_upgrade":
        summary.total_resent_priority_upgrade += 1
    elif decision.reason == "opportunity_upgrade":
        summary.total_resent_opportunity_upgrade += 1

    # 2b. Construir mensaje
    # Separar listing y pricing del row (ambos vienen del JOIN)
    listing_dict = {
        k: row[k] for k in ("title", "url", "price", "currency", "year", "km",
                             "model_raw", "model_normalized")
        if k in row.keys()
    }
    listing_dict["listing_id"] = listing_id

    pricing_dict = {
        k: row[k] for k in (
            "opportunity_level", "final_priority_level", "final_priority_score",
            "fair_price", "gap_pct", "freshness_bucket", "currency_used",
        )
        if k in row.keys()
    }

    message = format_alert_message(listing_dict, pricing_dict, decision.reason)
    fingerprint = build_alert_fingerprint(
        listing_id, current_price, current_opp, current_prio
    )

    # 2c. Enviar (o dry_run)
    is_dry = env.alert_dry_run
    send_result: TelegramSendResult

    if is_dry:
        logger.info(
            "[DRY RUN] Habría enviado alerta: listing_id=%d reason=%s priority=%s",
            listing_id, decision.reason, current_prio,
        )
        send_result = TelegramSendResult(success=True)
        summary.total_dry_run += 1
    elif not env.telegram_enabled:
        logger.info(
            "Telegram deshabilitado. Alerta omitida: listing_id=%d", listing_id,
        )
        send_result = TelegramSendResult(success=False, error="telegram_disabled")
    else:
        send_result = send_telegram_message(
            bot_token=env.telegram_bot_token,
            chat_id=env.telegram_chat_id,
            text=message,
        )

    # 2d. Persistir resultado
    if send_result.success:
        if not is_dry:
            summary.total_sent_ok += 1
        status = "sent"
    else:
        summary.total_failed += 1
        status = "failed"

    save_sent_alert(
        conn,
        listing_id=listing_id,
        message_fingerprint=fingerprint,
        alert_reason=decision.reason,
        channel=env.alert_channel,
        telegram_chat_id=env.telegram_chat_id,
        sent_price=current_price,
        sent_currency=currency,
        sent_opportunity_level=current_opp,
        sent_final_priority_level=current_prio,
        sent_final_priority_score=current_score,
        sent_fair_price=fair_price,
        sent_gap_pct=gap_pct,
        send_status=status,
        send_error=send_result.error,
        telegram_message_id=send_result.message_id,
        is_dry_run=is_dry,
    )
