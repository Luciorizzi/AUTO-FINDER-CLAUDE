"""Tests para el motor de pricing v2 (Fase 4 corregida).

Cubre:
- Deteccion de financiamiento
- Comparable finder con niveles A/B y filtro de moneda
- Filtro de outliers (IQR)
- Fair price por mediana
- Gap y clasificacion de oportunidad
- Dominancia
- Riesgo de anomalia
- Persistencia
- Casos de negocio integrados
"""

import sqlite3

import pytest

from app.filters.financing_detector import detect_financing
from app.parsers.text_normalizer import detect_currency
from app.pricing.comparable_finder import find_comparables
from app.pricing.dominance_checker import check_dominance
from app.pricing.fair_price import calculate_fair_price
from app.pricing.opportunity_score import (
    MEDIUM_OPPORTUNITY,
    NOT_OPPORTUNITY,
    STRONG_OPPORTUNITY,
    calculate_gap,
    classify_opportunity,
)
from app.pricing.outlier_filter import filter_outliers
from app.risk.anomaly_detector import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    assess_anomaly_risk,
)
from app.storage.repositories import (
    get_pricing_summary,
    save_pricing_analysis,
    update_financing_flags,
    update_normalization,
    upsert_listing,
)
from app.parsers.listing_parser import ListingDetail


# --- Helpers ---

def _insert_valid_listing(
    conn: sqlite3.Connection,
    source_id: str,
    model: str,
    year: int,
    km: int,
    price: float,
    currency: str = "ARS",
    title: str = "",
    brand: str = "",
    is_financing: bool = False,
    is_down_payment: bool = False,
) -> int:
    """Inserta un listing valido y normalizado para tests."""
    detail = ListingDetail(
        source_id=source_id,
        url=f"http://test/{source_id}",
        title=title or f"{model} {year}",
        price=price,
        year=year,
        km=km,
        currency=currency,
    )
    listing_id = upsert_listing(conn, detail)
    update_normalization(
        conn, listing_id,
        model_normalized=model,
        brand=brand,
        is_valid_segment=True,
    )
    if is_financing or is_down_payment:
        update_financing_flags(
            conn, listing_id,
            is_financing=is_financing,
            is_down_payment=is_down_payment,
            is_total_price_confident=False,
        )
    return listing_id


# --- Financing Detector ---

class TestFinancingDetector:
    def test_anticipo_detected(self):
        result = detect_financing("Anticipo de $ 5.600.000 Gol Trend 2013")
        assert result.is_financing is True
        assert result.is_down_payment is True
        assert result.is_total_price_confident is False

    def test_cuotas_detected(self):
        result = detect_financing("Gol Trend 2013 - Entrega y cuotas")
        assert result.is_financing is True
        assert result.is_total_price_confident is False

    def test_financiado_detected(self):
        result = detect_financing("Ford Ka 2012 Financiado")
        assert result.is_financing is True

    def test_credito_detected(self):
        result = detect_financing("Clio Mio 2014 - Credito con DNI")
        assert result.is_financing is True

    def test_solo_con_dni(self):
        result = detect_financing("Gol Trend solo con DNI financiacion")
        assert result.is_financing is True

    def test_normal_title_not_detected(self):
        result = detect_financing("Volkswagen Gol Trend 1.6 Pack I 2013")
        assert result.is_financing is False
        assert result.is_total_price_confident is True

    def test_none_title(self):
        result = detect_financing(None)
        assert result.is_financing is False

    def test_plan_de_ahorro(self):
        result = detect_financing("Gol Trend Plan de ahorro cuotas")
        assert result.is_financing is True


# --- Currency Detection ---

class TestCurrencyDetection:
    def test_ars_default(self):
        assert detect_currency("$ 10.500.000") == "ARS"

    def test_usd_u_dollar_s(self):
        assert detect_currency("U$S 8.000") == "USD"

    def test_usd_us_dollar(self):
        assert detect_currency("US$ 8.000") == "USD"

    def test_usd_text(self):
        assert detect_currency("USD 8000") == "USD"

    def test_none_defaults_ars(self):
        assert detect_currency(None) == "ARS"


# --- Comparable Finder with Levels ---

class TestComparableFinderV2:
    def test_level_a_same_year_same_currency(self, db_conn):
        """Nivel A: mismo anio +-1, misma moneda."""
        _insert_valid_listing(db_conn, "C1", "Gol Trend", 2012, 80000, 10_000_000)
        _insert_valid_listing(db_conn, "C2", "Gol Trend", 2013, 85000, 10_500_000)
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 82000, 8_000_000)

        result = find_comparables(db_conn, target, "Gol Trend", 82000, year=2012, currency="ARS")
        assert len(result.comparables) == 2
        assert result.level_used == "A"

    def test_excludes_different_currency(self, db_conn):
        """No mezcla ARS con USD."""
        _insert_valid_listing(db_conn, "C1", "Gol Trend", 2012, 80000, 10_000_000, currency="ARS")
        _insert_valid_listing(db_conn, "C2", "Gol Trend", 2012, 80000, 8_000, currency="USD")
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 82000, 8_500_000, currency="ARS")

        result = find_comparables(db_conn, target, "Gol Trend", 82000, year=2012, currency="ARS")
        assert len(result.comparables) == 1
        assert result.excluded_currency_mismatch == 1

    def test_usd_with_usd_only(self, db_conn):
        """USD se compara solo con USD."""
        _insert_valid_listing(db_conn, "C1", "Gol Trend", 2012, 80000, 8_500, currency="USD")
        _insert_valid_listing(db_conn, "C2", "Gol Trend", 2013, 85000, 9_000, currency="USD")
        _insert_valid_listing(db_conn, "C3", "Gol Trend", 2012, 80000, 10_000_000, currency="ARS")
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 82000, 7_500, currency="USD")

        result = find_comparables(db_conn, target, "Gol Trend", 82000, year=2012, currency="USD")
        assert len(result.comparables) == 2
        assert result.excluded_currency_mismatch == 1

    def test_excludes_financing(self, db_conn):
        """Excluye publicaciones de financiamiento."""
        _insert_valid_listing(db_conn, "C1", "Gol Trend", 2012, 80000, 10_000_000)
        _insert_valid_listing(db_conn, "C2", "Gol Trend", 2012, 85000, 5_000_000,
                              is_financing=True)  # anticipo
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 82000, 8_000_000)

        result = find_comparables(db_conn, target, "Gol Trend", 82000, year=2012, currency="ARS")
        assert len(result.comparables) == 1
        assert result.excluded_financing >= 1

    def test_falls_back_to_level_b(self, db_conn):
        """Con pocos en A, abre a nivel B (anio +-2)."""
        # Solo 1 de anio 2012 (nivel A) pero varios de 2014 (nivel B)
        _insert_valid_listing(db_conn, "C1", "Gol Trend", 2012, 80000, 10_000_000)
        _insert_valid_listing(db_conn, "C2", "Gol Trend", 2014, 85000, 11_000_000)
        _insert_valid_listing(db_conn, "C3", "Gol Trend", 2014, 90000, 10_500_000)
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 82000, 8_000_000)

        result = find_comparables(
            db_conn, target, "Gol Trend", 82000, year=2012, currency="ARS",
            min_comparables_level_a=3,  # Necesita 3 en A, solo tiene 1
        )
        assert result.level_a_count == 1
        assert result.level_b_count == 2
        assert result.level_used == "B"
        assert len(result.comparables) == 3

    def test_stays_level_a_when_enough(self, db_conn):
        """Si tiene suficientes en A, no abre a B."""
        for i in range(5):
            _insert_valid_listing(db_conn, f"C{i}", "Gol Trend", 2012, 80000 + i * 2000, 10_000_000 + i * 100_000)
        # Nivel B: anio lejano
        _insert_valid_listing(db_conn, "CB1", "Gol Trend", 2014, 85000, 12_000_000)
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 82000, 8_000_000)

        result = find_comparables(
            db_conn, target, "Gol Trend", 82000, year=2012, currency="ARS",
            min_comparables_level_a=3,
        )
        assert result.level_used == "A"
        assert len(result.comparables) == 5  # Solo nivel A

    def test_excludes_self(self, db_conn):
        target = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2012, 80000, 10_000_000)
        result = find_comparables(db_conn, target, "Gol Trend", 80000, year=2012, currency="ARS")
        assert len(result.comparables) == 0
        assert result.excluded_self == 1


# --- Outlier Filter ---

class TestOutlierFilter:
    def test_no_outliers(self):
        prices = [10_000_000, 10_500_000, 11_000_000, 10_200_000, 10_800_000]
        result = filter_outliers(prices)
        assert len(result.prices_out) == 5
        assert len(result.outliers_removed) == 0

    def test_removes_extreme_outlier(self):
        prices = [10_000_000, 10_500_000, 11_000_000, 10_200_000, 50_000_000]
        result = filter_outliers(prices)
        assert 50_000_000 in result.outliers_removed

    def test_removes_extreme_low(self):
        prices = [10_000_000, 10_500_000, 11_000_000, 10_200_000, 100_000]
        result = filter_outliers(prices)
        assert 100_000 in result.outliers_removed

    def test_less_than_4_no_filter(self):
        prices = [10_000_000, 50_000_000, 10_500_000]
        result = filter_outliers(prices)
        assert len(result.prices_out) == 3


# --- Fair Price ---

class TestFairPrice:
    def test_median_odd(self):
        prices = [10_000_000, 10_500_000, 11_000_000, 10_200_000, 10_800_000]
        result = calculate_fair_price(prices, min_comparables=3)
        assert result.fair_price == 10_500_000
        assert result.pricing_status == "enough_data"

    def test_insufficient_data(self):
        prices = [10_000_000, 10_500_000]
        result = calculate_fair_price(prices, min_comparables=3)
        assert result.pricing_status == "insufficient_data"
        assert result.fair_price is not None

    def test_no_data(self):
        result = calculate_fair_price([], min_comparables=3)
        assert result.pricing_status == "no_data"
        assert result.fair_price is None

    def test_outlier_excluded(self):
        prices = [10_000_000, 10_500_000, 11_000_000, 10_200_000, 50_000_000]
        result = calculate_fair_price(prices, min_comparables=3, enable_outlier_filtering=True)
        assert result.fair_price == 10_350_000
        assert result.outliers_removed == 1


# --- Opportunity Score ---

class TestOpportunityScore:
    def test_strong_opportunity(self):
        result = classify_opportunity(8_500_000, 10_000_000)
        assert result.gap_pct == -15.0
        assert result.opportunity_level == STRONG_OPPORTUNITY

    def test_medium_opportunity(self):
        result = classify_opportunity(9_000_000, 10_000_000)
        assert result.gap_pct == -10.0
        assert result.opportunity_level == MEDIUM_OPPORTUNITY

    def test_not_opportunity(self):
        result = classify_opportunity(9_500_000, 10_000_000)
        assert result.opportunity_level == NOT_OPPORTUNITY

    def test_dominated_degrades_to_not(self):
        """Un listing dominado se degrada a not_opportunity."""
        result = classify_opportunity(8_500_000, 10_000_000, is_dominated=True)
        assert result.gap_pct == -15.0
        assert result.opportunity_level == NOT_OPPORTUNITY
        assert result.degraded_by_dominance is True

    def test_boundary_strong(self):
        result = classify_opportunity(8_800_000, 10_000_000)
        assert result.gap_pct == -12.0
        assert result.opportunity_level == STRONG_OPPORTUNITY

    def test_boundary_medium(self):
        result = classify_opportunity(9_200_000, 10_000_000)
        assert result.gap_pct == -8.0
        assert result.opportunity_level == MEDIUM_OPPORTUNITY

    def test_gap_calculation(self):
        gap = calculate_gap(8_000_000, 10_000_000)
        assert gap == -20.0


# --- Dominance ---

class TestDominance:
    def test_dominated_by_newer_cheaper(self):
        """2011 95k km $8M dominado por 2013 70k km $7.5M."""
        comparables = [
            {"id": 100, "year": 2013, "km": 70000, "price": 7_500_000},
        ]
        result = check_dominance(
            listing_id=1, year=2011, km=95000, price=8_000_000,
            comparables=comparables,
            price_tolerance_pct=5.0, min_km_advantage=3000,
        )
        assert result.is_dominated is True
        assert result.dominated_by_id == 100

    def test_not_dominated_when_comparable_older(self):
        """Comparable es mas viejo => no domina."""
        comparables = [
            {"id": 100, "year": 2010, "km": 70000, "price": 7_500_000},
        ]
        result = check_dominance(
            listing_id=1, year=2012, km=95000, price=8_000_000,
            comparables=comparables,
        )
        assert result.is_dominated is False

    def test_not_dominated_when_comparable_more_km(self):
        """Comparable tiene mas km => no domina."""
        comparables = [
            {"id": 100, "year": 2013, "km": 96000, "price": 7_000_000},
        ]
        result = check_dominance(
            listing_id=1, year=2012, km=95000, price=8_000_000,
            comparables=comparables, min_km_advantage=3000,
        )
        assert result.is_dominated is False

    def test_not_dominated_when_comparable_much_more_expensive(self):
        """Comparable es mucho mas caro => no domina."""
        comparables = [
            {"id": 100, "year": 2013, "km": 70000, "price": 12_000_000},
        ]
        result = check_dominance(
            listing_id=1, year=2012, km=95000, price=8_000_000,
            comparables=comparables, price_tolerance_pct=5.0,
        )
        assert result.is_dominated is False

    def test_dominated_with_slight_price_premium(self):
        """Comparable ligeramente mas caro pero dentro de tolerancia."""
        comparables = [
            {"id": 100, "year": 2013, "km": 70000, "price": 8_300_000},
        ]
        result = check_dominance(
            listing_id=1, year=2012, km=95000, price=8_000_000,
            comparables=comparables, price_tolerance_pct=5.0,
        )
        # 8.3M <= 8M * 1.05 = 8.4M => domina
        assert result.is_dominated is True

    def test_empty_comparables(self):
        result = check_dominance(
            listing_id=1, year=2012, km=95000, price=8_000_000,
            comparables=[],
        )
        assert result.is_dominated is False

    def test_skips_self(self):
        """No se auto-domina."""
        comparables = [
            {"id": 1, "year": 2015, "km": 50000, "price": 5_000_000},
        ]
        result = check_dominance(
            listing_id=1, year=2012, km=95000, price=8_000_000,
            comparables=comparables,
        )
        assert result.is_dominated is False


# --- Anomaly Risk ---

class TestAnomalyRisk:
    def test_low_risk(self):
        result = assess_anomaly_risk(
            comparables_found=10, comparables_used=9,
            gap_pct=-10.0, cv=0.05, pricing_status="enough_data",
            published_price=9_000_000, km=80000,
        )
        assert result.risk_level == RISK_LOW

    def test_high_risk_few_comparables(self):
        result = assess_anomaly_risk(
            comparables_found=3, comparables_used=3,
            gap_pct=-10.0, cv=0.15, pricing_status="insufficient_data",
            published_price=9_000_000, km=80000,
        )
        assert result.risk_level == RISK_HIGH

    def test_extreme_gap(self):
        result = assess_anomaly_risk(
            comparables_found=10, comparables_used=10,
            gap_pct=-35.0, cv=0.05, pricing_status="enough_data",
            published_price=6_500_000, km=80000,
        )
        assert "extreme_gap" in result.reasons


# --- Casos de negocio integrados ---

class TestBusinessCasesV2:
    def test_strong_opp_low_risk_same_currency(self, db_conn):
        """9 comparables ARS, gap -16%, riesgo bajo."""
        for i in range(9):
            _insert_valid_listing(
                db_conn, f"C{i}", "Gol Trend", 2013,
                80000 + i * 1000, 10_000_000 + i * 100_000,
            )
        target_id = _insert_valid_listing(
            db_conn, "T1", "Gol Trend", 2013, 82000, 8_500_000,
        )

        comp = find_comparables(db_conn, target_id, "Gol Trend", 82000, year=2013, currency="ARS")
        prices = [c["price"] for c in comp.comparables]
        fp = calculate_fair_price(prices, min_comparables=3)
        opp = classify_opportunity(8_500_000, fp.fair_price)

        assert fp.pricing_status == "enough_data"
        assert opp.opportunity_level == STRONG_OPPORTUNITY

    def test_anticipo_excluded_from_fair_price(self, db_conn):
        """Anticipo de $5M no contamina fair price de $10M."""
        for i in range(5):
            _insert_valid_listing(
                db_conn, f"C{i}", "Gol Trend", 2013,
                80000 + i * 1000, 10_000_000 + i * 100_000,
            )
        # Anticipo: precio parcial muy bajo
        _insert_valid_listing(
            db_conn, "ANT1", "Gol Trend", 2013, 82000, 5_000_000,
            title="Anticipo de $5.000.000 Gol Trend 2013",
            is_financing=True, is_down_payment=True,
        )
        target_id = _insert_valid_listing(
            db_conn, "T1", "Gol Trend", 2013, 82000, 9_000_000,
        )

        comp = find_comparables(db_conn, target_id, "Gol Trend", 82000, year=2013, currency="ARS")
        prices = [c["price"] for c in comp.comparables]

        # El anticipo de 5M NO debe estar en los comparables
        assert 5_000_000 not in prices
        assert comp.excluded_financing >= 1

    def test_usd_not_mixed_with_ars(self, db_conn):
        """USD y ARS no se mezclan."""
        # ARS comparables
        for i in range(5):
            _insert_valid_listing(
                db_conn, f"ARS{i}", "Gol Trend", 2013,
                80000 + i * 1000, 10_000_000 + i * 100_000,
            )
        # USD comparables
        for i in range(3):
            _insert_valid_listing(
                db_conn, f"USD{i}", "Gol Trend", 2013,
                80000 + i * 1000, 8_000 + i * 500, currency="USD",
            )
        # Target en USD
        target_id = _insert_valid_listing(
            db_conn, "T1", "Gol Trend", 2013, 82000, 7_000, currency="USD",
        )

        comp = find_comparables(db_conn, target_id, "Gol Trend", 82000, year=2013, currency="USD")

        # Solo comparables USD
        assert len(comp.comparables) == 3
        assert comp.excluded_currency_mismatch == 5

    def test_2011_dominated_by_2012(self, db_conn):
        """Gol Trend 2011 95k $8M dominado por 2012 85k $7.5M."""
        # Comparables normales del mismo rango
        for i in range(5):
            _insert_valid_listing(
                db_conn, f"C{i}", "Gol Trend", 2012,
                90000 + i * 2000, 10_000_000 + i * 100_000,
            )
        # El dominador: mas nuevo, menos km, mas barato
        _insert_valid_listing(db_conn, "DOM", "Gol Trend", 2012, 85000, 7_500_000)
        # Target: viejo, mas km, caro relativo
        target_id = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2011, 95000, 8_000_000)

        comp = find_comparables(
            db_conn, target_id, "Gol Trend", 95000, year=2011, currency="ARS",
            level_a_max_year_diff=1, level_b_max_year_diff=2,
        )

        dom = check_dominance(
            listing_id=target_id, year=2011, km=95000, price=8_000_000,
            comparables=comp.comparables,
            price_tolerance_pct=5.0, min_km_advantage=3000,
        )
        assert dom.is_dominated is True

        # Oportunidad degradada
        fp = calculate_fair_price([c["price"] for c in comp.comparables], min_comparables=3)
        opp = classify_opportunity(8_000_000, fp.fair_price, is_dominated=True)
        assert opp.opportunity_level == NOT_OPPORTUNITY
        assert opp.degraded_by_dominance is True

    def test_2013_not_dominated(self, db_conn):
        """Gol Trend 2013 85k $8.5M no esta dominado si no hay nada mejor."""
        for i in range(5):
            _insert_valid_listing(
                db_conn, f"C{i}", "Gol Trend", 2013,
                80000 + i * 2000, 10_000_000 + i * 200_000,
            )
        target_id = _insert_valid_listing(db_conn, "T1", "Gol Trend", 2013, 85000, 8_500_000)

        comp = find_comparables(db_conn, target_id, "Gol Trend", 85000, year=2013, currency="ARS")
        dom = check_dominance(
            listing_id=target_id, year=2013, km=85000, price=8_500_000,
            comparables=comp.comparables,
        )
        assert dom.is_dominated is False

    def test_year_weight_level_a_vs_b(self, db_conn):
        """Nivel A (anio +-1) se prefiere sobre B cuando hay suficientes."""
        # 4 comparables de 2012-2013 (nivel A para target 2012)
        for i in range(4):
            _insert_valid_listing(db_conn, f"A{i}", "Ford Ka", 2012 + (i % 2), 75000 + i * 2000, 7_000_000 + i * 100_000)
        # 3 comparables de 2014 (nivel B)
        for i in range(3):
            _insert_valid_listing(db_conn, f"B{i}", "Ford Ka", 2014, 75000 + i * 2000, 9_000_000 + i * 100_000)

        target_id = _insert_valid_listing(db_conn, "T1", "Ford Ka", 2012, 76000, 6_000_000)

        result = find_comparables(
            db_conn, target_id, "Ford Ka", 76000, year=2012, currency="ARS",
            min_comparables_level_a=3,
        )
        # Debe usar solo nivel A (tiene 4 >= 3)
        assert result.level_used == "A"
        assert len(result.comparables) == 4


# --- Persistencia ---

class TestPricingPersistenceV2:
    def test_save_with_dominance(self, db_conn):
        lid = _insert_valid_listing(db_conn, "P1", "Gol Trend", 2012, 80000, 10_000_000)

        save_pricing_analysis(
            conn=db_conn, listing_id=lid,
            published_price=8_000_000, fair_price=10_000_000, gap_pct=-20.0,
            opportunity_level="not_opportunity",
            anomaly_risk="bajo", anomaly_reasons=None,
            comparables_found=10, comparables_used=9,
            min_comparable_price=9_000_000, max_comparable_price=11_000_000,
            median_comparable_price=10_000_000, p25_comparable_price=9_500_000,
            pricing_status="enough_data",
            is_dominated=True, dominated_by_listing_id=99,
            dominance_reason="dominado por id=99: anio 2013>2012",
            comparable_level="A", currency_used="ARS",
        )

        summary = get_pricing_summary(db_conn)
        assert summary["total_analyzed"] == 1
        assert summary["dominated"] == 1

    def test_save_financing_flags(self, db_conn):
        lid = _insert_valid_listing(db_conn, "F1", "Gol Trend", 2012, 80000, 5_000_000)
        update_financing_flags(db_conn, lid, is_financing=True, is_down_payment=True, is_total_price_confident=False)

        row = db_conn.execute("SELECT is_financing, is_down_payment, is_total_price_confident FROM listings WHERE id = ?", (lid,)).fetchone()
        assert row["is_financing"] == 1
        assert row["is_down_payment"] == 1
        assert row["is_total_price_confident"] == 0

        summary = get_pricing_summary(db_conn)
        assert summary["financing_excluded"] == 1
