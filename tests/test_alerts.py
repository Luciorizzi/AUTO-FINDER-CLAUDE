"""Tests de la Fase 5: alertas por Telegram.

Cubre:
- Fingerprint y deduplicación
- Formato de mensaje
- Persistencia de alertas enviadas
- Pipeline con dry_run
- Manejo de errores de Telegram
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.config import EnvSettings
from app.notifications.alert_dedup import (
    DedupDecision,
    build_alert_fingerprint,
    evaluate_dedup,
)
from app.notifications.alert_formatter import format_alert_message
from app.notifications.telegram_bot import TelegramSendResult, send_telegram_message
from app.pipeline.run_alerts import run_alerts_pipeline
from app.storage.repositories import (
    get_last_successful_alert,
    save_sent_alert,
)


# --- Helpers ---

def _seed_listing_with_pricing(
    conn: sqlite3.Connection,
    source_id: str = "MLA123",
    price: float = 4_000_000,
    year: int = 2014,
    km: int = 80_000,
    model: str = "gol_trend",
    opportunity_level: str = "strong_opportunity",
    final_priority_level: str = "urgent_review",
    final_priority_score: float = 75.0,
    fair_price: float = 4_600_000,
    gap_pct: float = -13.0,
) -> int:
    """Inserta un listing + pricing completo para pruebas de alertas."""
    cursor = conn.execute(
        """INSERT INTO listings
           (source_id, source, url, title, model_raw, model_normalized, brand,
            year, km, price, currency, is_active, is_valid_segment,
            is_financing, is_down_payment)
           VALUES (?, 'mercadolibre', ?, ?, ?, ?, 'volkswagen',
                   ?, ?, ?, 'ARS', 1, 1, 0, 0)""",
        (
            source_id,
            f"https://auto.mercadolibre.com.ar/{source_id}",
            f"Gol Trend 1.6 {year}",
            f"Gol Trend 1.6 {year}",
            model,
            year, km, price,
        ),
    )
    listing_id = cursor.lastrowid
    conn.execute(
        """INSERT INTO pricing_analyses
           (listing_id, published_price, fair_price, gap_pct,
            opportunity_level, anomaly_risk, comparables_found, comparables_used,
            pricing_status, currency_used,
            final_priority_score, final_priority_level,
            freshness_bucket)
           VALUES (?, ?, ?, ?, ?, 'bajo', 10, 8, 'enough_data', 'ARS', ?, ?, '0-1d')""",
        (listing_id, price, fair_price, gap_pct,
         opportunity_level, final_priority_score, final_priority_level),
    )
    conn.commit()
    return listing_id


# ==============================================================
# Fingerprint
# ==============================================================

class TestFingerprint:
    def test_same_inputs_same_fingerprint(self):
        fp1 = build_alert_fingerprint(1, 4_000_000, "strong_opportunity", "urgent_review")
        fp2 = build_alert_fingerprint(1, 4_000_000, "strong_opportunity", "urgent_review")
        assert fp1 == fp2

    def test_different_price_different_fingerprint(self):
        fp1 = build_alert_fingerprint(1, 4_000_000, "strong_opportunity", "urgent_review")
        fp2 = build_alert_fingerprint(1, 3_800_000, "strong_opportunity", "urgent_review")
        assert fp1 != fp2

    def test_different_priority_different_fingerprint(self):
        fp1 = build_alert_fingerprint(1, 4_000_000, "strong_opportunity", "urgent_review")
        fp2 = build_alert_fingerprint(1, 4_000_000, "strong_opportunity", "high_priority")
        assert fp1 != fp2

    def test_different_opportunity_different_fingerprint(self):
        fp1 = build_alert_fingerprint(1, 4_000_000, "strong_opportunity", "urgent_review")
        fp2 = build_alert_fingerprint(1, 4_000_000, "medium_opportunity", "urgent_review")
        assert fp1 != fp2

    def test_fingerprint_is_string_16_chars(self):
        fp = build_alert_fingerprint(42, 1234.5, "strong_opportunity", "urgent_review")
        assert isinstance(fp, str)
        assert len(fp) == 16


# ==============================================================
# Deduplicación
# ==============================================================

class TestDedup:
    def test_no_history_is_new_match(self):
        decision = evaluate_dedup(
            listing_id=1,
            current_price=4_000_000,
            current_opportunity="strong_opportunity",
            current_priority="urgent_review",
            last_sent=None,
        )
        assert decision.should_send is True
        assert decision.reason == "new_match"

    def test_same_state_is_duplicate(self):
        last = {
            "sent_price": 4_000_000,
            "sent_opportunity_level": "strong_opportunity",
            "sent_final_priority_level": "urgent_review",
        }
        decision = evaluate_dedup(
            listing_id=1,
            current_price=4_000_000,
            current_opportunity="strong_opportunity",
            current_priority="urgent_review",
            last_sent=last,
        )
        assert decision.should_send is False
        assert decision.reason == "duplicate"

    def test_price_drop_triggers_resend(self):
        last = {
            "sent_price": 4_000_000,
            "sent_opportunity_level": "strong_opportunity",
            "sent_final_priority_level": "urgent_review",
        }
        decision = evaluate_dedup(
            listing_id=1,
            current_price=3_800_000,
            current_opportunity="strong_opportunity",
            current_priority="urgent_review",
            last_sent=last,
        )
        assert decision.should_send is True
        assert decision.reason == "price_drop"

    def test_price_drop_disabled(self):
        last = {
            "sent_price": 4_000_000,
            "sent_opportunity_level": "strong_opportunity",
            "sent_final_priority_level": "urgent_review",
        }
        decision = evaluate_dedup(
            listing_id=1,
            current_price=3_800_000,
            current_opportunity="strong_opportunity",
            current_priority="urgent_review",
            last_sent=last,
            resend_on_price_change=False,
        )
        # Price drop disabled but fingerprint changed → still duplicate
        assert decision.should_send is False

    def test_priority_upgrade_triggers_resend(self):
        last = {
            "sent_price": 4_000_000,
            "sent_opportunity_level": "strong_opportunity",
            "sent_final_priority_level": "high_priority",
        }
        decision = evaluate_dedup(
            listing_id=1,
            current_price=4_000_000,
            current_opportunity="strong_opportunity",
            current_priority="urgent_review",
            last_sent=last,
        )
        assert decision.should_send is True
        assert decision.reason == "priority_upgrade"

    def test_priority_downgrade_no_resend(self):
        last = {
            "sent_price": 4_000_000,
            "sent_opportunity_level": "strong_opportunity",
            "sent_final_priority_level": "urgent_review",
        }
        decision = evaluate_dedup(
            listing_id=1,
            current_price=4_000_000,
            current_opportunity="strong_opportunity",
            current_priority="high_priority",
            last_sent=last,
        )
        assert decision.should_send is False
        assert decision.reason == "duplicate"

    def test_opportunity_upgrade_triggers_resend(self):
        last = {
            "sent_price": 4_000_000,
            "sent_opportunity_level": "medium_opportunity",
            "sent_final_priority_level": "urgent_review",
        }
        decision = evaluate_dedup(
            listing_id=1,
            current_price=4_000_000,
            current_opportunity="strong_opportunity",
            current_priority="urgent_review",
            last_sent=last,
        )
        assert decision.should_send is True
        assert decision.reason == "opportunity_upgrade"


# ==============================================================
# Formato de mensaje
# ==============================================================

class TestAlertFormatter:
    def test_message_contains_key_fields(self):
        listing = {
            "title": "Gol Trend 1.6 Pack I 2015",
            "url": "https://auto.mercadolibre.com.ar/MLA-123",
            "price": 4_000_000,
            "currency": "ARS",
            "year": 2015,
            "km": 95_000,
        }
        pricing = {
            "opportunity_level": "strong_opportunity",
            "final_priority_level": "urgent_review",
            "final_priority_score": 74.5,
            "fair_price": 4_600_000,
            "gap_pct": -13.0,
            "freshness_bucket": "0-1d",
            "currency_used": "ARS",
        }
        msg = format_alert_message(listing, pricing, "new_match")
        assert "Gol Trend 1.6 Pack I 2015" in msg
        assert "4.000.000" in msg
        assert "2015" in msg
        assert "95.000" in msg
        assert "strong_opportunity" in msg
        assert "urgent_review" in msg
        assert "74.5" in msg
        assert "4.600.000" in msg
        assert "-13.0%" in msg
        assert "0-1d" in msg
        assert "MLA-123" in msg

    def test_message_handles_none_values(self):
        listing = {"title": "Auto test", "url": "http://test", "price": None,
                    "currency": "ARS", "year": None, "km": None}
        pricing = {"opportunity_level": None, "final_priority_level": None,
                    "final_priority_score": None, "fair_price": None,
                    "gap_pct": None, "freshness_bucket": None, "currency_used": "ARS"}
        msg = format_alert_message(listing, pricing, "new_match")
        assert "Auto test" in msg
        assert "N/A" in msg

    def test_message_shows_reason(self):
        listing = {"title": "Test", "url": "http://t", "price": 1000,
                    "currency": "ARS", "year": 2014, "km": 80000}
        pricing = {"opportunity_level": "strong_opportunity",
                    "final_priority_level": "urgent_review",
                    "final_priority_score": 70, "currency_used": "ARS"}
        msg = format_alert_message(listing, pricing, "price_drop")
        assert "Baja de precio" in msg


# ==============================================================
# Telegram (mock)
# ==============================================================

class TestTelegramBot:
    def test_empty_token_returns_error(self):
        result = send_telegram_message("", "123", "test")
        assert result.success is False
        assert "vacío" in result.error

    def test_empty_chat_id_returns_error(self):
        result = send_telegram_message("token", "", "test")
        assert result.success is False

    @patch("app.notifications.telegram_bot.requests.post")
    def test_successful_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
        mock_post.return_value = mock_resp

        result = send_telegram_message("token123", "chat456", "Hello")
        assert result.success is True
        assert result.message_id == 42

    @patch("app.notifications.telegram_bot.requests.post")
    def test_api_error_returns_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"ok": False, "description": "Forbidden"}
        mock_resp.text = "Forbidden"
        mock_post.return_value = mock_resp

        result = send_telegram_message("token", "chat", "Hello")
        assert result.success is False
        assert result.status_code == 403

    @patch("app.notifications.telegram_bot.requests.post")
    def test_timeout_returns_failure(self, mock_post):
        import requests as req
        mock_post.side_effect = req.Timeout("timeout")
        result = send_telegram_message("token", "chat", "Hello")
        assert result.success is False
        assert "timeout" in result.error


# ==============================================================
# Persistencia de alertas
# ==============================================================

class TestAlertPersistence:
    def test_save_and_retrieve_alert(self, db_conn: sqlite3.Connection):
        listing_id = _seed_listing_with_pricing(db_conn)
        alert_id = save_sent_alert(
            db_conn,
            listing_id=listing_id,
            message_fingerprint="abc123",
            alert_reason="new_match",
            telegram_chat_id="12345",
            sent_price=4_000_000,
            sent_currency="ARS",
            sent_opportunity_level="strong_opportunity",
            sent_final_priority_level="urgent_review",
            sent_final_priority_score=75.0,
            sent_fair_price=4_600_000,
            sent_gap_pct=-13.0,
            send_status="sent",
            telegram_message_id=42,
        )
        assert alert_id > 0

        last = get_last_successful_alert(db_conn, listing_id)
        assert last is not None
        assert last["sent_price"] == 4_000_000
        assert last["sent_opportunity_level"] == "strong_opportunity"
        assert last["sent_final_priority_level"] == "urgent_review"
        assert last["alert_reason"] == "new_match"
        assert last["telegram_message_id"] == 42

    def test_failed_alert_not_returned_as_last(self, db_conn: sqlite3.Connection):
        listing_id = _seed_listing_with_pricing(db_conn)
        save_sent_alert(
            db_conn,
            listing_id=listing_id,
            message_fingerprint="fail1",
            alert_reason="new_match",
            send_status="failed",
            send_error="timeout",
        )
        last = get_last_successful_alert(db_conn, listing_id)
        assert last is None

    def test_dry_run_alert_not_returned_as_last(self, db_conn: sqlite3.Connection):
        listing_id = _seed_listing_with_pricing(db_conn)
        save_sent_alert(
            db_conn,
            listing_id=listing_id,
            message_fingerprint="dry1",
            alert_reason="new_match",
            send_status="sent",
            is_dry_run=True,
        )
        last = get_last_successful_alert(db_conn, listing_id)
        assert last is None


# ==============================================================
# Pipeline completo
# ==============================================================

class TestAlertsPipeline:
    def _make_env(self, **overrides) -> EnvSettings:
        defaults = {
            "telegram_enabled": True,
            "telegram_bot_token": "test_token",
            "telegram_chat_id": "test_chat",
            "alert_priority_levels": "urgent_review,high_priority",
            "alert_dry_run": True,
            "alert_resend_on_price_change": True,
            "alert_resend_on_priority_upgrade": True,
            "alert_resend_on_opportunity_upgrade": True,
        }
        defaults.update(overrides)
        return EnvSettings(**defaults)

    def test_dry_run_does_not_call_telegram(self, db_conn: sqlite3.Connection):
        _seed_listing_with_pricing(db_conn)
        env = self._make_env(alert_dry_run=True)

        with patch("app.pipeline.run_alerts.send_telegram_message") as mock_send:
            summary = run_alerts_pipeline(db_conn, env)

        mock_send.assert_not_called()
        assert summary.total_eligible == 1
        assert summary.total_new == 1
        assert summary.total_dry_run == 1
        assert summary.total_sent_ok == 0

    def test_real_send_calls_telegram(self, db_conn: sqlite3.Connection):
        _seed_listing_with_pricing(db_conn)
        env = self._make_env(alert_dry_run=False)

        with patch("app.pipeline.run_alerts.send_telegram_message") as mock_send:
            mock_send.return_value = TelegramSendResult(success=True, message_id=99)
            summary = run_alerts_pipeline(db_conn, env)

        mock_send.assert_called_once()
        assert summary.total_sent_ok == 1
        assert summary.total_new == 1

    def test_duplicate_not_resent(self, db_conn: sqlite3.Connection):
        listing_id = _seed_listing_with_pricing(db_conn)
        # Simular alerta previa exitosa con mismo estado
        save_sent_alert(
            db_conn,
            listing_id=listing_id,
            message_fingerprint=build_alert_fingerprint(
                listing_id, 4_000_000, "strong_opportunity", "urgent_review"
            ),
            alert_reason="new_match",
            sent_price=4_000_000,
            sent_opportunity_level="strong_opportunity",
            sent_final_priority_level="urgent_review",
            send_status="sent",
        )
        env = self._make_env(alert_dry_run=True)
        summary = run_alerts_pipeline(db_conn, env)

        assert summary.total_eligible == 1
        assert summary.total_skipped_duplicate == 1
        assert summary.total_new == 0
        assert summary.total_dry_run == 0

    def test_telegram_error_does_not_break_batch(self, db_conn: sqlite3.Connection):
        _seed_listing_with_pricing(db_conn, source_id="MLA1")
        _seed_listing_with_pricing(db_conn, source_id="MLA2", price=3_500_000)
        env = self._make_env(alert_dry_run=False)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TelegramSendResult(success=False, error="timeout")
            return TelegramSendResult(success=True, message_id=100)

        with patch("app.pipeline.run_alerts.send_telegram_message", side_effect=side_effect):
            summary = run_alerts_pipeline(db_conn, env)

        assert summary.total_eligible == 2
        assert summary.total_failed == 1
        assert summary.total_sent_ok == 1

    def test_low_priority_not_eligible(self, db_conn: sqlite3.Connection):
        _seed_listing_with_pricing(
            db_conn,
            final_priority_level="low_priority",
            final_priority_score=10.0,
        )
        env = self._make_env(alert_dry_run=True)
        summary = run_alerts_pipeline(db_conn, env)

        assert summary.total_eligible == 0

    def test_medium_priority_not_eligible_by_default(self, db_conn: sqlite3.Connection):
        _seed_listing_with_pricing(
            db_conn,
            final_priority_level="medium_priority",
            final_priority_score=30.0,
        )
        env = self._make_env(alert_dry_run=True)
        summary = run_alerts_pipeline(db_conn, env)
        assert summary.total_eligible == 0

    def test_custom_priority_levels(self, db_conn: sqlite3.Connection):
        """Se puede configurar para alertar también medium_priority."""
        _seed_listing_with_pricing(
            db_conn,
            final_priority_level="medium_priority",
            final_priority_score=30.0,
        )
        env = self._make_env(
            alert_dry_run=True,
            alert_priority_levels="urgent_review,high_priority,medium_priority",
        )
        summary = run_alerts_pipeline(db_conn, env)
        assert summary.total_eligible == 1
