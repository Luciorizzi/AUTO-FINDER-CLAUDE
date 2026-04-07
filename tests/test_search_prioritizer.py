"""Tests de priorizacion y balance de resultados de search."""

import sqlite3

from app.collectors.search_prioritizer import prioritize_results
from app.parsers.listing_parser import ListingDetail, SearchResult
from app.storage.repositories import (
    get_existing_source_ids,
    get_listing_by_source_id,
    persist_listing_detail,
)


def _make_result(
    source_id: str,
    query: str,
    price: float | None = None,
    position: int = 1,
) -> SearchResult:
    return SearchResult(
        source_id=source_id,
        listing_url=f"https://auto.mercadolibre.com.ar/{source_id}",
        title_preview=f"Test {source_id}",
        price_preview=price,
        currency_preview="ARS",
        search_query=query,
        search_position=position,
    )


class TestPrioritizeByPrice:
    def test_lowest_price_first_within_query(self):
        results = {
            "gol trend": [
                _make_result("MLA1", "gol trend", price=4_000_000, position=1),
                _make_result("MLA2", "gol trend", price=2_500_000, position=2),
                _make_result("MLA3", "gol trend", price=3_200_000, position=3),
            ],
        }
        selected, stats = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1, prioritize_lowest_price=True,
        )

        assert [r.source_id for r in selected] == ["MLA2", "MLA3", "MLA1"]
        assert stats.total_selected == 3

    def test_no_price_goes_last(self):
        results = {
            "gol trend": [
                _make_result("MLA1", "gol trend", price=None, position=1),
                _make_result("MLA2", "gol trend", price=2_500_000, position=2),
                _make_result("MLA3", "gol trend", price=None, position=3),
                _make_result("MLA4", "gol trend", price=3_200_000, position=4),
            ],
        }
        selected, _ = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1, prioritize_lowest_price=True,
        )

        # Primero los que tienen precio (orden ascendente), despues los sin precio
        ids = [r.source_id for r in selected]
        assert ids[:2] == ["MLA2", "MLA4"]
        assert set(ids[2:]) == {"MLA1", "MLA3"}

    def test_no_price_still_included(self):
        """Resultados sin precio igual deben incluirse, no descartarse."""
        results = {
            "ford ka": [
                _make_result("MLA1", "ford ka", price=None, position=1),
                _make_result("MLA2", "ford ka", price=None, position=2),
            ],
        }
        selected, _ = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1, prioritize_lowest_price=True,
        )
        assert len(selected) == 2


class TestBalanceBetweenQueries:
    def test_min_per_query_guaranteed(self):
        """Una query con muchos resultados no debe consumir todo el cupo."""
        results = {
            "gol trend": [_make_result(f"MLA-G{i}", "gol trend", price=1000 + i) for i in range(20)],
            "clio mio": [_make_result(f"MLA-C{i}", "clio mio", price=2000 + i) for i in range(5)],
            "ford ka": [_make_result(f"MLA-F{i}", "ford ka", price=3000 + i) for i in range(5)],
        }
        selected, stats = prioritize_results(
            results,
            max_details_total=15,
            max_details_per_query=10,
            min_details_per_query=3,
            prioritize_lowest_price=True,
        )

        # Cada query debe tener al menos 3
        assert stats.by_query["gol trend"]["selected"] >= 3
        assert stats.by_query["clio mio"]["selected"] >= 3
        assert stats.by_query["ford ka"]["selected"] >= 3
        assert stats.total_selected <= 15

    def test_max_per_query_respected(self):
        """Cap por query no debe excederse aunque haya presupuesto."""
        results = {
            "gol trend": [_make_result(f"MLA-G{i}", "gol trend", price=1000 + i) for i in range(50)],
            "clio mio": [_make_result(f"MLA-C{i}", "clio mio", price=2000 + i) for i in range(2)],
        }
        selected, stats = prioritize_results(
            results,
            max_details_total=100,
            max_details_per_query=10,
            min_details_per_query=2,
            prioritize_lowest_price=True,
        )

        assert stats.by_query["gol trend"]["selected"] == 10
        assert stats.by_query["clio mio"]["selected"] == 2

    def test_distributes_remaining_budget(self):
        """Despues del minimo, sobra budget que debe repartirse."""
        results = {
            "q1": [_make_result(f"MLA-A{i}", "q1", price=100 + i) for i in range(20)],
            "q2": [_make_result(f"MLA-B{i}", "q2", price=200 + i) for i in range(20)],
        }
        selected, stats = prioritize_results(
            results,
            max_details_total=20,
            max_details_per_query=15,
            min_details_per_query=3,
            prioritize_lowest_price=True,
        )

        # Cada query deberia recibir entre 3 (min) y 15 (max), distribuido
        assert stats.by_query["q1"]["selected"] >= 3
        assert stats.by_query["q2"]["selected"] >= 3
        assert stats.total_selected == 20


class TestDedup:
    def test_excludes_already_seen(self):
        results = {
            "gol trend": [
                _make_result("MLA1", "gol trend", price=1000),
                _make_result("MLA2", "gol trend", price=2000),
                _make_result("MLA3", "gol trend", price=3000),
            ],
        }
        selected, stats = prioritize_results(
            results,
            max_details_total=10,
            max_details_per_query=10,
            min_details_per_query=1,
            already_seen_ids={"MLA2"},
        )
        ids = {r.source_id for r in selected}
        assert "MLA2" not in ids
        assert "MLA1" in ids
        assert "MLA3" in ids
        assert stats.total_selected == 2

    def test_empty_after_dedup(self):
        results = {
            "gol trend": [_make_result("MLA1", "gol trend", price=1000)],
        }
        selected, stats = prioritize_results(
            results,
            max_details_total=10,
            max_details_per_query=10,
            min_details_per_query=1,
            already_seen_ids={"MLA1"},
        )
        assert selected == []
        assert stats.total_selected == 0


class TestStats:
    def test_stats_per_query(self):
        results = {
            "q1": [_make_result(f"MLA-A{i}", "q1", price=100 + i) for i in range(5)],
            "q2": [_make_result(f"MLA-B{i}", "q2", price=200 + i) for i in range(3)],
        }
        _, stats = prioritize_results(
            results,
            max_details_total=4,
            max_details_per_query=10,
            min_details_per_query=2,
        )
        assert stats.by_query["q1"]["raw_count"] == 5
        assert stats.by_query["q2"]["raw_count"] == 3
        assert stats.by_query["q1"]["selected"] >= 2
        assert stats.by_query["q2"]["selected"] >= 2
        assert stats.total_selected == 4
        assert stats.total_excluded_by_limit == 4  # 8 candidatos - 4 seleccionados

    def test_empty_input(self):
        selected, stats = prioritize_results({}, max_details_total=10)
        assert selected == []
        assert stats.total_candidates == 0
        assert stats.total_selected == 0


class TestSearchMetadataPersistence:
    def test_persist_search_metadata(self, db_conn: sqlite3.Connection):
        detail = ListingDetail(
            source_id="MLA999",
            url="https://auto.mercadolibre.com.ar/MLA-999",
            title="Gol Trend 2015",
            price=4_500_000,
            currency="ARS",
            year=2015,
            km=80_000,
        )
        persist_listing_detail(
            db_conn, detail,
            search_query="gol trend 2010 2015",
            search_position=7,
            search_page=1,
            preview_price=4_500_000,
            preview_currency="ARS",
        )
        row = get_listing_by_source_id(db_conn, "MLA999")
        assert row is not None
        assert row["search_query"] == "gol trend 2010 2015"
        assert row["search_position"] == 7
        assert row["search_page"] == 1
        assert row["preview_price"] == 4_500_000
        assert row["preview_currency"] == "ARS"
        assert row["extraction_timestamp"] is not None

    def test_get_existing_source_ids(self, db_conn: sqlite3.Connection):
        detail1 = ListingDetail(source_id="MLA111", url="u1", title="t1", year=2013, km=80000, price=1000)
        detail2 = ListingDetail(source_id="MLA222", url="u2", title="t2", year=2014, km=85000, price=2000)
        persist_listing_detail(db_conn, detail1)
        persist_listing_detail(db_conn, detail2)

        ids = get_existing_source_ids(db_conn)
        assert ids == {"MLA111", "MLA222"}
