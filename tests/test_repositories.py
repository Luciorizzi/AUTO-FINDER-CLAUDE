"""Tests de repositorios: upsert de listings y snapshots."""

import sqlite3

from app.parsers.listing_parser import ListingDetail
from app.storage.repositories import (
    count_listings,
    count_snapshots,
    create_snapshot,
    get_listing_by_source_id,
    get_snapshots_for_listing,
    persist_listing_detail,
    upsert_listing,
)


def _make_detail(**overrides) -> ListingDetail:
    """Helper para crear un ListingDetail de prueba."""
    defaults = dict(
        source="mercadolibre",
        source_id="MLA123456",
        url="https://auto.mercadolibre.com.ar/MLA-123456-test",
        title="Gol Trend 2013",
        price=3500000.0,
        currency="ARS",
        location="Capital Federal",
        model_raw="Gol Trend 2013",
        year=2013,
        km=75000,
        seller_type="particular",
    )
    defaults.update(overrides)
    return ListingDetail(**defaults)


class TestUpsertListing:
    def test_insert_new(self, db_conn: sqlite3.Connection):
        detail = _make_detail()
        listing_id = upsert_listing(db_conn, detail)

        assert listing_id > 0
        assert count_listings(db_conn) == 1

        row = get_listing_by_source_id(db_conn, "MLA123456")
        assert row is not None
        assert row["title"] == "Gol Trend 2013"
        assert row["price"] == 3500000.0
        assert row["year"] == 2013
        assert row["km"] == 75000

    def test_update_existing(self, db_conn: sqlite3.Connection):
        detail = _make_detail()
        id1 = upsert_listing(db_conn, detail)

        # Simular actualizacion de precio
        detail_updated = _make_detail(price=3200000.0, km=76000)
        id2 = upsert_listing(db_conn, detail_updated)

        # Mismo ID, datos actualizados
        assert id2 == id1
        assert count_listings(db_conn) == 1

        row = get_listing_by_source_id(db_conn, "MLA123456")
        assert row["price"] == 3200000.0
        assert row["km"] == 76000

    def test_multiple_different_listings(self, db_conn: sqlite3.Connection):
        upsert_listing(db_conn, _make_detail(source_id="MLA111"))
        upsert_listing(db_conn, _make_detail(source_id="MLA222"))
        assert count_listings(db_conn) == 2


class TestSnapshots:
    def test_create_snapshot(self, db_conn: sqlite3.Connection):
        detail = _make_detail()
        listing_id = upsert_listing(db_conn, detail)

        snap_id = create_snapshot(db_conn, listing_id, 3500000.0, "ARS", 75000)
        assert snap_id > 0
        assert count_snapshots(db_conn) == 1

    def test_multiple_snapshots(self, db_conn: sqlite3.Connection):
        detail = _make_detail()
        listing_id = upsert_listing(db_conn, detail)

        create_snapshot(db_conn, listing_id, 3500000.0, "ARS", 75000)
        create_snapshot(db_conn, listing_id, 3200000.0, "ARS", 76000)

        snaps = get_snapshots_for_listing(db_conn, listing_id)
        assert len(snaps) == 2
        assert snaps[0]["price"] == 3500000.0
        assert snaps[1]["price"] == 3200000.0


class TestPersistListingDetail:
    def test_creates_listing_and_snapshot(self, db_conn: sqlite3.Connection):
        detail = _make_detail()
        listing_id = persist_listing_detail(db_conn, detail)

        assert listing_id > 0
        assert count_listings(db_conn) == 1
        assert count_snapshots(db_conn) == 1

    def test_second_persist_creates_new_snapshot(self, db_conn: sqlite3.Connection):
        detail = _make_detail()
        persist_listing_detail(db_conn, detail)

        # Segunda corrida con precio distinto
        detail2 = _make_detail(price=3200000.0)
        persist_listing_detail(db_conn, detail2)

        assert count_listings(db_conn) == 1
        assert count_snapshots(db_conn) == 2
