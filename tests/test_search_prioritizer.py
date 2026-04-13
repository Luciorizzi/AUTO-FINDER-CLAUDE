"""Tests de priorizacion y balance de resultados de search."""

import sqlite3

from app.collectors.search_prioritizer import (
    compute_preview_priority_score,
    prioritize_results,
)
from app.parsers.listing_parser import ListingDetail, SearchResult, parse_search_result
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
    title: str | None = None,
    financing: bool = False,
) -> SearchResult:
    return SearchResult(
        source_id=source_id,
        listing_url=f"https://auto.mercadolibre.com.ar/{source_id}",
        title_preview=title or f"Test {source_id}",
        price_preview=price,
        currency_preview="ARS",
        search_query=query,
        search_position=position,
        is_financing_preview=financing,
        financing_pattern="anticipo" if financing else None,
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


class TestFinancingPreview:
    def test_financing_detected_goes_last(self):
        """Un preview con 'anticipo' debe quedar al final de la cola."""
        results = {
            "gol trend": [
                _make_result("MLA1", "gol trend", price=1_500_000, financing=True,
                             title="Gol Trend anticipo y cuotas"),
                _make_result("MLA2", "gol trend", price=4_000_000, financing=False),
                _make_result("MLA3", "gol trend", price=3_500_000, financing=False),
            ],
        }
        selected, stats = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1, prioritize_lowest_price=True,
            deprioritize_financing=True, exclude_financing=False,
        )
        ids = [r.source_id for r in selected]
        # El financiero queda ultimo aunque tenga "precio" mas bajo
        assert ids[-1] == "MLA1"
        assert ids[0] in ("MLA3",)
        assert stats.total_financing_detected == 1
        assert stats.total_financing_excluded == 0

    def test_financing_can_be_excluded(self):
        """Con exclude_financing=True, los financieros ni siquiera entran."""
        results = {
            "gol trend": [
                _make_result("MLA1", "gol trend", price=1_500_000, financing=True),
                _make_result("MLA2", "gol trend", price=4_000_000),
            ],
        }
        selected, stats = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1, exclude_financing=True,
        )
        ids = {r.source_id for r in selected}
        assert "MLA1" not in ids
        assert "MLA2" in ids
        assert stats.total_financing_excluded == 1

    def test_cheap_non_financing_wins_over_cheaper_financing(self):
        """Escenario clave: barato financiero NO debe ganarle a no-financiero razonable."""
        results = {
            "gol trend": [
                _make_result("G_fin", "gol trend", price=500_000, financing=True,
                             title="Gol Trend anticipo 500k"),
                _make_result("G_ok", "gol trend", price=3_800_000, financing=False),
                _make_result("G_ok2", "gol trend", price=4_200_000, financing=False),
            ],
        }
        selected, _ = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1, deprioritize_financing=True,
        )
        ids = [r.source_id for r in selected]
        # Los no-financieros deben ir primero (ordenados por precio asc)
        assert ids[0] == "G_ok"
        assert ids[1] == "G_ok2"
        assert ids[2] == "G_fin"

    def test_parser_detects_financing_from_title(self):
        """parse_search_result debe setear is_financing_preview desde el titulo."""
        r = parse_search_result(
            url="https://auto.mercadolibre.com.ar/MLA-1",
            title="Ford Ka 2013 ENTREGA Y CUOTAS",
            price_text="$ 1.200.000",
            currency_text="$",
            location="CABA",
            attrs=["2013", "80.000 km"],
            search_query="ford ka",
        )
        assert r.is_financing_preview is True
        assert r.financing_pattern is not None

    def test_parser_clean_title_not_flagged(self):
        r = parse_search_result(
            url="https://auto.mercadolibre.com.ar/MLA-2",
            title="Ford Ka 2013 titular unico",
            price_text="$ 4.200.000",
            currency_text="$",
            location="CABA",
            attrs=["2013", "90.000 km"],
            search_query="ford ka",
        )
        assert r.is_financing_preview is False


class TestPriorityScore:
    def test_score_monotonic_with_price(self):
        """Dentro de la misma query, a menor precio mayor score."""
        cheap = _make_result("A", "q", price=1_000_000)
        mid = _make_result("B", "q", price=2_000_000)
        expensive = _make_result("C", "q", price=3_000_000)

        s_cheap = compute_preview_priority_score(cheap, 1_000_000, 3_000_000)
        s_mid = compute_preview_priority_score(mid, 1_000_000, 3_000_000)
        s_exp = compute_preview_priority_score(expensive, 1_000_000, 3_000_000)

        assert s_cheap > s_mid > s_exp

    def test_score_penalizes_financing(self):
        clean = _make_result("A", "q", price=2_000_000, financing=False)
        fin = _make_result("B", "q", price=2_000_000, financing=True)

        s_clean = compute_preview_priority_score(clean, 2_000_000, 2_000_000)
        s_fin = compute_preview_priority_score(fin, 2_000_000, 2_000_000)
        assert s_clean > s_fin
        assert s_clean - s_fin >= 100

    def test_score_penalizes_no_price(self):
        priced = _make_result("A", "q", price=2_000_000)
        noprice = _make_result("B", "q", price=None)
        s_priced = compute_preview_priority_score(priced, 2_000_000, 2_000_000)
        s_noprice = compute_preview_priority_score(noprice, 2_000_000, 2_000_000)
        assert s_priced > s_noprice

    def test_score_assigned_on_selected_results(self):
        """Despues de prioritize_results, los resultados tienen score asignado."""
        results = {
            "q": [
                _make_result(f"MLA{i}", "q", price=1000 * (i + 1))
                for i in range(5)
            ],
        }
        selected, _ = prioritize_results(
            results, max_details_total=10, max_details_per_query=10,
            min_details_per_query=1,
        )
        for r in selected:
            assert r.preview_priority_score is not None
            assert r.selected_for_detail is True


class TestBalanceWithFinancing:
    def test_balance_per_query_still_respected(self):
        """El balance minimo por query se respeta aunque una query tenga financieros."""
        results = {
            "gol trend": [
                _make_result("G1", "gol trend", price=2_000_000),
                _make_result("G2", "gol trend", price=3_000_000, financing=True),
                _make_result("G3", "gol trend", price=4_000_000),
            ],
            "ford ka": [
                _make_result("F1", "ford ka", price=1_500_000),
                _make_result("F2", "ford ka", price=2_500_000),
            ],
        }
        _, stats = prioritize_results(
            results,
            max_details_total=10,
            max_details_per_query=5,
            min_details_per_query=2,
        )
        assert stats.by_query["gol trend"]["selected"] >= 2
        assert stats.by_query["ford ka"]["selected"] >= 2

    def test_scenario_cheap_car_gets_in_budget_limit(self):
        """Un aviso barato en una query saturada igual entra al lote."""
        # 20 Gol Trend, 5 baratos al final de la lista (ML los devolvio desordenados)
        gol = [
            _make_result(f"G{i}", "gol trend", price=4_000_000 + i * 10_000, position=i + 1)
            for i in range(15)
        ]
        # 5 mas baratos aparecen despues
        gol += [
            _make_result("G_cheap1", "gol trend", price=2_500_000, position=16),
            _make_result("G_cheap2", "gol trend", price=2_700_000, position=17),
        ]
        results = {"gol trend": gol}

        selected, _ = prioritize_results(
            results,
            max_details_total=5,
            max_details_per_query=5,
            min_details_per_query=1,
            prioritize_lowest_price=True,
        )
        ids = {r.source_id for r in selected}
        # Los dos baratos deben estar aunque vengan en posicion 16/17
        assert "G_cheap1" in ids
        assert "G_cheap2" in ids


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
            preview_financing_flag=False,
            preview_priority_score=85.5,
            selected_for_detail=True,
        )
        row = get_listing_by_source_id(db_conn, "MLA999")
        assert row is not None
        assert row["search_query"] == "gol trend 2010 2015"
        assert row["search_position"] == 7
        assert row["search_page"] == 1
        assert row["preview_price"] == 4_500_000
        assert row["preview_currency"] == "ARS"
        assert row["preview_financing_flag"] == 0
        assert row["preview_priority_score"] == 85.5
        assert row["selected_for_detail"] == 1
        assert row["extraction_timestamp"] is not None

    def test_persist_financing_flag(self, db_conn: sqlite3.Connection):
        detail = ListingDetail(
            source_id="MLA_FIN",
            url="https://auto.mercadolibre.com.ar/MLA-FIN",
            title="Ford Ka anticipo y cuotas",
            price=None,
            currency="ARS",
        )
        persist_listing_detail(
            db_conn, detail,
            search_query="ford ka",
            preview_financing_flag=True,
            preview_priority_score=-55.0,
            selected_for_detail=False,
        )
        row = get_listing_by_source_id(db_conn, "MLA_FIN")
        assert row["preview_financing_flag"] == 1
        assert row["preview_priority_score"] == -55.0
        assert row["selected_for_detail"] == 0

    def test_get_existing_source_ids(self, db_conn: sqlite3.Connection):
        detail1 = ListingDetail(source_id="MLA111", url="u1", title="t1", year=2013, km=80000, price=1000)
        detail2 = ListingDetail(source_id="MLA222", url="u2", title="t2", year=2014, km=85000, price=2000)
        persist_listing_detail(db_conn, detail1)
        persist_listing_detail(db_conn, detail2)

        ids = get_existing_source_ids(db_conn)
        assert ids == {"MLA111", "MLA222"}
