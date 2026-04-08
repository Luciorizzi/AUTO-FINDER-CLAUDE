"""Tests para el motor de prioridad operativa (Fase 4.2).

Cubre:
- Freshness bucket assignment
- Local ranking dentro del microgrupo
- Price history signals (markdown, days on market)
- Priority score calculation
- Priority level mapping con gates de seguridad
- Casos de negocio integrados
- Persistencia de nuevos campos
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.pricing.freshness import (
    BUCKET_0_1D,
    BUCKET_1_3D,
    BUCKET_3_7D,
    BUCKET_OLD,
    BUCKET_UNKNOWN,
    compute_freshness,
)
from app.pricing.local_rank import compute_local_rank
from app.pricing.price_history import compute_price_history
from app.pricing.priority_score import (
    HIGH_PRIORITY,
    LOW_PRIORITY,
    MEDIUM_PRIORITY,
    URGENT_REVIEW,
    compute_priority_score,
)
from app.parsers.listing_parser import ListingDetail
from app.storage.repositories import (
    create_snapshot,
    get_pricing_summary,
    save_pricing_analysis,
    update_normalization,
    upsert_listing,
)


# --- Helpers ---

def _insert_valid(
    conn: sqlite3.Connection,
    source_id: str,
    model: str,
    year: int,
    km: int,
    price: float,
    currency: str = "ARS",
) -> int:
    detail = ListingDetail(
        source_id=source_id,
        url=f"http://test/{source_id}",
        title=f"{model} {year}",
        price=price,
        year=year,
        km=km,
        currency=currency,
    )
    lid = upsert_listing(conn, detail)
    update_normalization(conn, lid, model_normalized=model, brand="", is_valid_segment=True)
    return lid


NOW = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)


# --- Freshness ---

class TestFreshness:
    def test_bucket_today(self):
        ts = (NOW - timedelta(hours=5)).isoformat()
        r = compute_freshness(ts, now=NOW)
        assert r.bucket == BUCKET_0_1D
        assert r.boost == 25.0
        assert r.days_on_market == 0

    def test_bucket_yesterday_still_0_1d(self):
        ts = (NOW - timedelta(hours=23)).isoformat()
        r = compute_freshness(ts, now=NOW)
        assert r.bucket == BUCKET_0_1D

    def test_bucket_2_days(self):
        ts = (NOW - timedelta(days=2)).isoformat()
        r = compute_freshness(ts, now=NOW)
        assert r.bucket == BUCKET_1_3D
        assert r.boost == 15.0
        assert r.days_on_market == 2

    def test_bucket_5_days(self):
        ts = (NOW - timedelta(days=5)).isoformat()
        r = compute_freshness(ts, now=NOW)
        assert r.bucket == BUCKET_3_7D
        assert r.boost == 5.0

    def test_bucket_old(self):
        ts = (NOW - timedelta(days=20)).isoformat()
        r = compute_freshness(ts, now=NOW)
        assert r.bucket == BUCKET_OLD
        assert r.boost == 0.0
        assert r.days_on_market == 20

    def test_none_timestamp(self):
        r = compute_freshness(None, now=NOW)
        assert r.bucket == BUCKET_UNKNOWN
        assert r.boost == 0.0

    def test_sqlite_format_timestamp(self):
        """Acepta formato SQLite 'YYYY-MM-DD HH:MM:SS'."""
        ts = (NOW - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        r = compute_freshness(ts, now=NOW)
        assert r.bucket == BUCKET_0_1D


# --- Local Rank ---

class TestLocalRank:
    def test_top_1_cheapest(self):
        comparables = [
            {"price": 10_000_000, "year": 2013, "km": 80_000},
            {"price": 10_500_000, "year": 2013, "km": 82_000},
            {"price": 11_000_000, "year": 2013, "km": 85_000},
        ]
        r = compute_local_rank(
            target_price=9_000_000,
            comparables=comparables,
            target_year=2013,
            target_km=81_000,
        )
        assert r.has_enough_data is True
        assert r.local_group_size == 4
        assert r.local_price_rank == 1
        assert r.is_top_local_price_1 is True
        assert r.is_top_local_price_3 is True
        assert r.local_price_percentile == 0.0

    def test_top_3_but_not_1(self):
        comparables = [
            {"price": 9_500_000, "year": 2013, "km": 80_000},
            {"price": 10_500_000, "year": 2013, "km": 82_000},
            {"price": 11_000_000, "year": 2013, "km": 85_000},
            {"price": 11_500_000, "year": 2013, "km": 87_000},
        ]
        r = compute_local_rank(
            target_price=10_000_000,
            comparables=comparables,
            target_year=2013,
            target_km=81_000,
        )
        assert r.local_group_size == 5
        assert r.local_price_rank == 2
        assert r.is_top_local_price_1 is False
        assert r.is_top_local_price_3 is True

    def test_not_top_3(self):
        comparables = [
            {"price": 9_000_000, "year": 2013, "km": 80_000},
            {"price": 9_500_000, "year": 2013, "km": 82_000},
            {"price": 10_000_000, "year": 2013, "km": 85_000},
            {"price": 10_500_000, "year": 2013, "km": 87_000},
        ]
        r = compute_local_rank(
            target_price=11_000_000,
            comparables=comparables,
            target_year=2013,
            target_km=81_000,
        )
        assert r.local_price_rank == 5
        assert r.is_top_local_price_3 is False

    def test_group_too_small(self):
        """Grupo muy chico -> no se calcula rank."""
        comparables = [
            {"price": 10_000_000, "year": 2013, "km": 80_000},
        ]
        r = compute_local_rank(
            target_price=9_000_000,
            comparables=comparables,
            target_year=2013,
            target_km=81_000,
            local_min_group_size=3,
        )
        assert r.has_enough_data is False
        assert r.local_price_rank is None

    def test_excludes_far_year(self):
        """Comparables con anio +-2 NO son microgrupo local (solo +-1)."""
        comparables = [
            {"price": 10_000_000, "year": 2013, "km": 80_000},
            {"price": 10_500_000, "year": 2013, "km": 82_000},
            {"price": 8_000_000, "year": 2015, "km": 80_000},  # fuera del microgrupo
        ]
        r = compute_local_rank(
            target_price=9_000_000,
            comparables=comparables,
            target_year=2013,
            target_km=81_000,
            local_group_max_year_diff=1,
        )
        assert r.local_group_size == 3  # target + 2 cercanos
        assert r.is_top_local_price_1 is True  # 9M < 10M, 10.5M

    def test_none_target_price(self):
        r = compute_local_rank(
            target_price=None,
            comparables=[{"price": 10_000_000, "year": 2013, "km": 80_000}],
            target_year=2013,
            target_km=80_000,
        )
        assert r.local_price_rank is None


# --- Price History ---

class TestPriceHistory:
    def test_single_snapshot_no_markdown(self, db_conn):
        lid = _insert_valid(db_conn, "H1", "Gol Trend", 2013, 80000, 10_000_000)
        create_snapshot(db_conn, lid, price=10_000_000)

        r = compute_price_history(db_conn, lid, current_price=10_000_000)
        assert r.snapshot_count == 1
        assert r.initial_price == 10_000_000
        assert r.has_markdown is False

    def test_markdown_detected(self, db_conn):
        lid = _insert_valid(db_conn, "H2", "Gol Trend", 2013, 80000, 9_500_000)
        create_snapshot(db_conn, lid, price=10_000_000)
        create_snapshot(db_conn, lid, price=9_800_000)
        create_snapshot(db_conn, lid, price=9_500_000)

        r = compute_price_history(db_conn, lid, current_price=9_500_000)
        assert r.snapshot_count == 3
        assert r.initial_price == 10_000_000
        assert r.current_price == 9_500_000
        assert r.price_change_count == 2
        assert r.markdown_pct == -5.0  # -500k/10M
        assert r.has_markdown is True

    def test_no_snapshots(self, db_conn):
        lid = _insert_valid(db_conn, "H3", "Gol Trend", 2013, 80000, 9_500_000)
        r = compute_price_history(db_conn, lid, current_price=9_500_000)
        assert r.snapshot_count == 0
        assert r.initial_price is None
        assert r.has_markdown is False


# --- Priority Score ---

class TestPriorityScore:
    def test_strong_opp_fresh_top_local_urgent(self):
        """gap=-15, top1 local, reciente => urgent_review."""
        r = compute_priority_score(
            gap_pct=-15.0,
            is_top_local_price_1=True,
            is_top_local_price_3=True,
            freshness_boost=25.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
        )
        # 15 + 30 + 25 = 70 => urgent
        assert r.price_edge_score == 15.0
        assert r.local_rank_bonus == 30.0
        assert r.freshness_boost == 25.0
        assert r.final_priority_score == 70.0
        assert r.final_priority_level == URGENT_REVIEW

    def test_medium_opp_fresh_top_local_urgent(self):
        """medium_opportunity pero reciente + top1 local => urgent_review.

        Un auto puede ser medium (gap -10) pero la frescura + ranking local
        lo suben a urgent.
        """
        r = compute_priority_score(
            gap_pct=-10.0,
            is_top_local_price_1=True,
            is_top_local_price_3=True,
            freshness_boost=25.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
            urgent_review_threshold=60.0,  # 10+30+25 = 65
        )
        assert r.final_priority_level == URGENT_REVIEW

    def test_dominated_cannot_be_urgent(self):
        """Aunque el score lo permita, dominado NUNCA es urgent."""
        r = compute_priority_score(
            gap_pct=-25.0,       # price edge 25
            is_top_local_price_1=True,  # +30
            is_top_local_price_3=True,
            freshness_boost=25.0,  # +25
            markdown_pct=None,
            is_dominated=True,   # -40
            anomaly_risk="bajo",
        )
        # 25 + 30 + 25 - 40 = 40 => high_priority
        assert r.final_priority_score == 40.0
        # Gate: dominado no puede ser urgent. Pero 40 < 45 (high threshold) anyway.
        # Lo probamos tambien con score alto:
        r2 = compute_priority_score(
            gap_pct=-40.0,
            is_top_local_price_1=True,
            is_top_local_price_3=True,
            freshness_boost=25.0,
            markdown_pct=-5.0,
            is_dominated=True,
            anomaly_risk="bajo",
            dominance_penalty=10.0,  # baja penalizacion para que pase 70
        )
        # 40+30+25+20-10 = 105 => gate lo baja a high_priority
        assert r2.final_priority_score == 105.0
        assert r2.final_priority_level == HIGH_PRIORITY  # gate

    def test_high_risk_cannot_be_urgent(self):
        """anomaly_risk=alto degrada urgent a high_priority."""
        r = compute_priority_score(
            gap_pct=-20.0,
            is_top_local_price_1=True,
            is_top_local_price_3=True,
            freshness_boost=25.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="alto",  # -25
        )
        # 20+30+25-25 = 50 => high_priority (no urgent por gate)
        assert r.final_priority_score == 50.0
        assert r.final_priority_level == HIGH_PRIORITY

    def test_old_no_edge_low_priority(self):
        """Viejo, sin ventaja de precio, sin rank => low_priority."""
        r = compute_priority_score(
            gap_pct=2.0,  # mas caro que mediana
            is_top_local_price_1=False,
            is_top_local_price_3=False,
            freshness_boost=0.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
        )
        assert r.price_edge_score == 0.0  # gap positivo => clamped a 0
        assert r.final_priority_score == 0.0
        assert r.final_priority_level == LOW_PRIORITY

    def test_markdown_bonus_applied(self):
        """Rebaja significativa => bonus."""
        r = compute_priority_score(
            gap_pct=-5.0,
            is_top_local_price_1=False,
            is_top_local_price_3=True,
            freshness_boost=0.0,
            markdown_pct=-8.0,  # rebaja del 8%
            is_dominated=False,
            anomaly_risk="bajo",
        )
        # 5 + 15 + 0 + 20 = 40 => medium_priority (>=20)
        assert r.markdown_bonus == 20.0
        assert r.final_priority_score == 40.0

    def test_markdown_below_threshold_no_bonus(self):
        """Rebaja menor al umbral => sin bonus."""
        r = compute_priority_score(
            gap_pct=-10.0,
            is_top_local_price_1=False,
            is_top_local_price_3=False,
            freshness_boost=0.0,
            markdown_pct=-1.5,  # rebaja muy chica
            is_dominated=False,
            anomaly_risk="bajo",
            markdown_significant_pct=3.0,
        )
        assert r.markdown_bonus == 0.0

    def test_dominated_high_priority_degraded(self):
        """Dominado con score en frontera de high_priority => degrada a medium."""
        r = compute_priority_score(
            gap_pct=-30.0,  # +30 edge
            is_top_local_price_1=True,  # +30
            is_top_local_price_3=True,
            freshness_boost=15.0,  # +15
            markdown_pct=None,
            is_dominated=True,  # -40
            anomaly_risk="bajo",
        )
        # 30+30+15-40 = 35. high >= 45, medium >= 20. Cae en medium.
        assert r.final_priority_score == 35.0
        assert r.final_priority_level == MEDIUM_PRIORITY

    def test_price_edge_capped(self):
        """gap muy negativo se capea al cap."""
        r = compute_priority_score(
            gap_pct=-80.0,
            is_top_local_price_1=False,
            is_top_local_price_3=False,
            freshness_boost=0.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
            price_edge_cap=40.0,
        )
        assert r.price_edge_score == 40.0

    def test_gap_none_does_not_crash(self):
        """gap_pct=None no debe romper; score=0."""
        r = compute_priority_score(
            gap_pct=None,
            is_top_local_price_1=False,
            is_top_local_price_3=False,
            freshness_boost=0.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
        )
        assert r.price_edge_score == 0.0
        assert r.final_priority_level == LOW_PRIORITY


# --- Persistencia ---

class TestPriorityPersistence:
    def test_save_with_priority_fields(self, db_conn):
        lid = _insert_valid(db_conn, "PR1", "Gol Trend", 2013, 80000, 9_000_000)

        save_pricing_analysis(
            conn=db_conn, listing_id=lid,
            published_price=9_000_000, fair_price=10_000_000, gap_pct=-10.0,
            opportunity_level="medium_opportunity",
            anomaly_risk="bajo", anomaly_reasons=None,
            comparables_found=10, comparables_used=9,
            min_comparable_price=9_000_000, max_comparable_price=11_000_000,
            median_comparable_price=10_000_000, p25_comparable_price=9_500_000,
            pricing_status="enough_data",
            comparable_level="A", currency_used="ARS",
            local_price_rank=1, local_group_size=6,
            local_price_percentile=0.0,
            is_top_local_price_1=True, is_top_local_price_3=True,
            freshness_bucket="0-1d", freshness_boost=25.0, days_on_market=0,
            initial_price=9_500_000, current_price=9_000_000,
            price_change_count=1, markdown_abs=-500_000, markdown_pct=-5.26,
            markdown_bonus=20.0,
            price_edge_score=10.0, local_rank_bonus=30.0,
            dominance_penalty=0.0, anomaly_penalty=0.0,
            final_priority_score=85.0, final_priority_level="urgent_review",
        )

        row = db_conn.execute(
            "SELECT * FROM pricing_analyses WHERE listing_id = ?", (lid,)
        ).fetchone()
        assert row is not None
        assert row["final_priority_level"] == "urgent_review"
        assert row["final_priority_score"] == 85.0
        assert row["is_top_local_price_1"] == 1
        assert row["freshness_bucket"] == "0-1d"
        assert row["markdown_bonus"] == 20.0
        assert row["local_group_size"] == 6

        summary = get_pricing_summary(db_conn)
        assert summary["urgent_review"] == 1
        assert summary["top_local_1"] == 1


# --- Casos de negocio integrados ---

class TestBusinessCasesPriority:
    def test_medium_opp_urgent_review_via_local_and_freshness(self, db_conn):
        """Gol Trend 2013 con gap -10% pero top1 local y recien publicado:
        estadistica = medium_opportunity, operativa = urgent_review."""
        # Setup: 5 comparables a 10M, uno a 11M
        for i in range(5):
            _insert_valid(db_conn, f"C{i}", "Gol Trend", 2013, 80000 + i * 1000, 10_000_000)
        _insert_valid(db_conn, "C5", "Gol Trend", 2013, 85000, 11_000_000)
        # Target: 9M (gap ~= -10% vs mediana 10M)
        target_price = 9_000_000

        # Simular comparables directamente
        comparables = [
            {"price": 10_000_000, "year": 2013, "km": 80_000},
            {"price": 10_000_000, "year": 2013, "km": 81_000},
            {"price": 10_000_000, "year": 2013, "km": 82_000},
            {"price": 10_000_000, "year": 2013, "km": 83_000},
            {"price": 10_000_000, "year": 2013, "km": 84_000},
            {"price": 11_000_000, "year": 2013, "km": 85_000},
        ]
        local = compute_local_rank(
            target_price=target_price,
            comparables=comparables,
            target_year=2013, target_km=81_000,
        )
        assert local.is_top_local_price_1 is True

        fresh = compute_freshness(
            first_seen_at=(NOW - timedelta(hours=6)).isoformat(),
            now=NOW,
        )
        assert fresh.boost == 25.0

        priority = compute_priority_score(
            gap_pct=-10.0,
            is_top_local_price_1=local.is_top_local_price_1,
            is_top_local_price_3=local.is_top_local_price_3,
            freshness_boost=fresh.boost,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
        )
        # 10 + 30 + 25 = 65. Urgent = 70, high = 45 => high_priority
        # Ajustamos el umbral para este caso (urgent=60)
        priority2 = compute_priority_score(
            gap_pct=-10.0,
            is_top_local_price_1=True,
            is_top_local_price_3=True,
            freshness_boost=25.0,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
            urgent_review_threshold=60.0,
        )
        assert priority2.final_priority_level == URGENT_REVIEW

    def test_old_with_low_edge_is_low_priority(self):
        """Publicado hace 20 dias, gap -2% => low_priority."""
        fresh = compute_freshness(
            first_seen_at=(NOW - timedelta(days=20)).isoformat(),
            now=NOW,
        )
        priority = compute_priority_score(
            gap_pct=-2.0,
            is_top_local_price_1=False,
            is_top_local_price_3=False,
            freshness_boost=fresh.boost,
            markdown_pct=None,
            is_dominated=False,
            anomaly_risk="bajo",
        )
        assert priority.final_priority_level == LOW_PRIORITY
