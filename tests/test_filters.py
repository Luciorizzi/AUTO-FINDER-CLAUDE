"""Tests para filtros de segmento y deduplicacion."""

import sqlite3

from app.config import load_segment_rules
from app.filters.segment_filter import validate_listing, ValidationResult
from app.filters.duplicate_filter import check_heuristic_duplicate
from app.storage.repositories import update_normalization, get_listing_by_source_id
from app.parsers.listing_parser import ListingDetail
from app.storage.repositories import upsert_listing


def _segment():
    return load_segment_rules()


# --- Segment Filter ---

class TestSegmentFilterValid:
    """Casos que deben ser validos."""

    def test_gol_trend_valid(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2012, km=95000, price=10000000.0,
            title="Volkswagen Gol Trend 1.6 Pack I 2012 95000 km",
            segment=_segment(),
        )
        assert result.is_valid is True
        assert result.reason is None

    def test_clio_mio_valid(self):
        result = validate_listing(
            model_normalized="Clio Mio",
            year=2014, km=87000, price=8500000.0,
            title="Renault Clio Mio 2014 87000 km",
            segment=_segment(),
        )
        assert result.is_valid is True

    def test_ford_ka_valid(self):
        result = validate_listing(
            model_normalized="Ford Ka",
            year=2013, km=102000, price=7000000.0,
            title="Ford Ka Fly Viral 2013 102000 km",
            segment=_segment(),
        )
        assert result.is_valid is True

    def test_celta_valid(self):
        result = validate_listing(
            model_normalized="Chevrolet Celta",
            year=2011, km=108000, price=6000000.0,
            title="Chevrolet Celta LT 2011 108000 km",
            segment=_segment(),
        )
        assert result.is_valid is True

    def test_fiat_punto_valid(self):
        result = validate_listing(
            model_normalized="Fiat Punto",
            year=2015, km=109000, price=12000000.0,
            title="Fiat Punto Attractive 2015 109000 km",
            segment=_segment(),
        )
        assert result.is_valid is True

    def test_edge_year_min(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2010, km=50000, price=8000000.0,
            title="Gol Trend 2010",
            segment=_segment(),
        )
        assert result.is_valid is True

    def test_edge_year_max(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2015, km=50000, price=8000000.0,
            title="Gol Trend 2015",
            segment=_segment(),
        )
        assert result.is_valid is True

    def test_edge_km_max(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2012, km=110000, price=8000000.0,
            title="Gol Trend 2012",
            segment=_segment(),
        )
        assert result.is_valid is True


class TestSegmentFilterInvalid:
    """Casos que deben ser invalidos con motivo explicito."""

    def test_unknown_model(self):
        result = validate_listing(
            model_normalized=None,
            year=2013, km=50000, price=15000000.0,
            title="Toyota Corolla 2013",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "unknown_model"

    def test_model_not_in_segment(self):
        result = validate_listing(
            model_normalized="Toyota Corolla",
            year=2013, km=50000, price=15000000.0,
            title="Toyota Corolla 2013",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "unknown_model"

    def test_year_too_old(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2009, km=80000, price=6000000.0,
            title="Gol Trend 2009",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "year_out_of_range"

    def test_year_too_new(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2016, km=50000, price=12000000.0,
            title="Gol Trend 2016",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "year_out_of_range"

    def test_km_over_limit(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2012, km=115000, price=7000000.0,
            title="Gol Trend 2012 115000 km",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "mileage_out_of_range"

    def test_missing_year(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=None, km=80000, price=8000000.0,
            title="Gol Trend",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "missing_year"

    def test_missing_mileage(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2012, km=None, price=8000000.0,
            title="Gol Trend 2012",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "missing_mileage"

    def test_missing_price(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2012, km=80000, price=None,
            title="Gol Trend 2012",
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "missing_price"

    def test_missing_title(self):
        result = validate_listing(
            model_normalized="Gol Trend",
            year=2012, km=80000, price=8000000.0,
            title=None,
            segment=_segment(),
        )
        assert result.is_valid is False
        assert result.reason == "missing_required_fields"


# --- Duplicate Filter ---

class TestDuplicateFilter:
    def test_no_duplicate_empty_candidates(self):
        result = check_heuristic_duplicate(
            listing_id=1,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=[],
        )
        assert result.is_duplicate is False

    def test_exact_duplicate(self):
        """Mismo modelo, año, km y precio -> duplicado."""
        candidates = [
            {"id": 10, "model_normalized": "Gol Trend", "year": 2012,
             "km": 80000, "price": 10000000.0, "title": "Gol Trend"},
        ]
        result = check_heuristic_duplicate(
            listing_id=2,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=candidates,
        )
        assert result.is_duplicate is True
        assert result.duplicate_of_id == 10

    def test_similar_within_tolerance(self):
        """Km y precio dentro de tolerancia -> duplicado."""
        candidates = [
            {"id": 10, "model_normalized": "Gol Trend", "year": 2012,
             "km": 79000, "price": 10200000.0, "title": "Gol Trend"},
        ]
        result = check_heuristic_duplicate(
            listing_id=2,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=candidates,
            price_tolerance_pct=5.0,
            mileage_tolerance=2000,
        )
        assert result.is_duplicate is True

    def test_different_price_no_duplicate(self):
        """Precio muy diferente -> no es duplicado."""
        candidates = [
            {"id": 10, "model_normalized": "Gol Trend", "year": 2012,
             "km": 80000, "price": 8000000.0, "title": "Gol Trend"},
        ]
        result = check_heuristic_duplicate(
            listing_id=2,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=candidates,
            price_tolerance_pct=5.0,
        )
        assert result.is_duplicate is False

    def test_different_year_no_duplicate(self):
        candidates = [
            {"id": 10, "model_normalized": "Gol Trend", "year": 2013,
             "km": 80000, "price": 10000000.0, "title": "Gol Trend"},
        ]
        result = check_heuristic_duplicate(
            listing_id=2,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=candidates,
        )
        assert result.is_duplicate is False

    def test_different_model_no_duplicate(self):
        candidates = [
            {"id": 10, "model_normalized": "Ford Ka", "year": 2012,
             "km": 80000, "price": 10000000.0, "title": "Ford Ka"},
        ]
        result = check_heuristic_duplicate(
            listing_id=2,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=candidates,
        )
        assert result.is_duplicate is False

    def test_skip_self(self):
        """No debe comparar consigo mismo."""
        candidates = [
            {"id": 2, "model_normalized": "Gol Trend", "year": 2012,
             "km": 80000, "price": 10000000.0, "title": "Gol Trend"},
        ]
        result = check_heuristic_duplicate(
            listing_id=2,
            model_normalized="Gol Trend",
            year=2012, km=80000, price=10000000.0,
            candidates=candidates,
        )
        assert result.is_duplicate is False

    def test_missing_fields_no_crash(self):
        result = check_heuristic_duplicate(
            listing_id=1,
            model_normalized=None,
            year=None, km=None, price=None,
            candidates=[{"id": 10, "model_normalized": "Gol Trend",
                         "year": 2012, "km": 80000, "price": 10000000.0}],
        )
        assert result.is_duplicate is False


# --- Persistencia de normalizacion ---

class TestNormalizationPersistence:
    def test_update_normalization_valid(self, db_conn: sqlite3.Connection):
        detail = ListingDetail(
            source_id="MLA999", url="http://test.com/MLA-999",
            title="Gol Trend 2012", price=10000000.0, year=2012, km=80000,
        )
        listing_id = upsert_listing(db_conn, detail)
        update_normalization(
            db_conn, listing_id,
            model_normalized="Gol Trend", brand="volkswagen",
            is_valid_segment=True,
        )
        row = get_listing_by_source_id(db_conn, "MLA999")
        assert row["model_normalized"] == "Gol Trend"
        assert row["brand"] == "volkswagen"
        assert row["is_valid_segment"] == 1
        assert row["invalid_reason"] is None
        assert row["normalized_at"] is not None

    def test_update_normalization_invalid(self, db_conn: sqlite3.Connection):
        detail = ListingDetail(
            source_id="MLA888", url="http://test.com/MLA-888",
            title="Toyota Corolla 2013", price=15000000.0, year=2013, km=50000,
        )
        listing_id = upsert_listing(db_conn, detail)
        update_normalization(
            db_conn, listing_id,
            model_normalized=None, brand=None,
            is_valid_segment=False, invalid_reason="unknown_model",
        )
        row = get_listing_by_source_id(db_conn, "MLA888")
        assert row["is_valid_segment"] == 0
        assert row["invalid_reason"] == "unknown_model"

    def test_update_normalization_duplicate(self, db_conn: sqlite3.Connection):
        # Insertar original
        d1 = ListingDetail(
            source_id="MLA100", url="http://test.com/MLA-100",
            title="Gol Trend 2012", price=10000000.0, year=2012, km=80000,
        )
        id1 = upsert_listing(db_conn, d1)

        # Insertar duplicado
        d2 = ListingDetail(
            source_id="MLA101", url="http://test.com/MLA-101",
            title="Gol Trend 2012", price=10000000.0, year=2012, km=80000,
        )
        id2 = upsert_listing(db_conn, d2)

        update_normalization(
            db_conn, id2,
            model_normalized="Gol Trend", brand="volkswagen",
            is_valid_segment=True, duplicate_of=id1,
        )
        row = get_listing_by_source_id(db_conn, "MLA101")
        assert row["duplicate_of"] == id1
