"""Tests para parsers de texto y datos de publicaciones."""

import pytest

from app.parsers.text_normalizer import (
    clean_text,
    detect_currency,
    extract_number,
    normalize_text,
    parse_km,
    parse_price,
    parse_year,
)
from app.parsers.listing_parser import (
    extract_source_id,
    parse_search_result,
    parse_specs_table,
    build_listing_detail,
)


# --- text_normalizer ---

class TestNormalizeText:
    def test_lowercase_and_accents(self):
        assert normalize_text("Clio Mío Confort") == "clio mio confort"

    def test_uppercase(self):
        assert normalize_text("FORD KA FLY") == "ford ka fly"

    def test_special_chars_removed(self):
        assert normalize_text("Gol-Trend 1.6!") == "gol trend 1.6"

    def test_none_returns_empty(self):
        assert normalize_text(None) == ""

    def test_empty_returns_empty(self):
        assert normalize_text("") == ""


class TestCleanText:
    def test_removes_extra_spaces(self):
        assert clean_text("  hola   mundo  ") == "hola mundo"

    def test_none_returns_none(self):
        assert clean_text(None) is None

    def test_empty_returns_none(self):
        assert clean_text("   ") is None


class TestExtractNumber:
    def test_simple_number(self):
        assert extract_number("2013") == 2013

    def test_number_with_dots(self):
        assert extract_number("75.000 km") == 75000

    def test_price_with_dots(self):
        assert extract_number("$ 3.500.000") == 3500000

    def test_none_returns_none(self):
        assert extract_number(None) is None

    def test_no_numbers(self):
        assert extract_number("sin numeros") is None


class TestParsePrice:
    def test_simple_integer(self):
        assert parse_price("3500000") == 3500000.0

    def test_with_dots_as_thousands(self):
        assert parse_price("3.500.000") == 3500000.0

    def test_with_currency_symbol(self):
        assert parse_price("$ 3.500.000") == 3500000.0

    def test_usd_price(self):
        assert parse_price("U$S 15.000") == 15000.0

    def test_none_returns_none(self):
        assert parse_price(None) is None

    def test_empty_returns_none(self):
        assert parse_price("") is None

    def test_with_comma_decimal(self):
        assert parse_price("3.500.000,50") == 3500000.50


class TestDetectCurrency:
    def test_default_ars(self):
        assert detect_currency("$ 3.500.000") == "ARS"

    def test_usd(self):
        assert detect_currency("U$S 15.000") == "USD"

    def test_us_dollar(self):
        assert detect_currency("USD 12000") == "USD"

    def test_none_returns_ars(self):
        assert detect_currency(None) == "ARS"


class TestParseKm:
    def test_with_km_suffix(self):
        assert parse_km("75.000 km") == 75000

    def test_plain_number(self):
        assert parse_km("95000") == 95000

    def test_none(self):
        assert parse_km(None) is None

    def test_mil_km_space(self):
        assert parse_km("75 mil km") == 75000

    def test_mil_no_space(self):
        assert parse_km("97mil") == 97000

    def test_mil_km_variante(self):
        assert parse_km("110 mil") == 110000

    def test_empty_string(self):
        assert parse_km("") is None


class TestParseYear:
    def test_four_digit_year(self):
        assert parse_year("2013") == 2013

    def test_year_in_text(self):
        assert parse_year("Gol Trend 2014 - 75000 km") == 2014

    def test_no_year(self):
        assert parse_year("sin año") is None

    def test_none(self):
        assert parse_year(None) is None

    def test_out_of_range(self):
        # 1899 no es un año valido para nosotros
        assert parse_year("1899") is None


# --- listing_parser ---

class TestExtractSourceId:
    def test_standard_url(self):
        url = "https://auto.mercadolibre.com.ar/MLA-1234567890-gol-trend-2013"
        assert extract_source_id(url) == "MLA1234567890"

    def test_compact_url(self):
        url = "https://www.mercadolibre.com.ar/gol-trend/p/MLA1234567"
        assert extract_source_id(url) == "MLA1234567"

    def test_no_id(self):
        assert extract_source_id("https://example.com") == ""


class TestParseSpecsTable:
    def test_extracts_year(self):
        specs = {"Año": "2013", "Kilómetros": "75.000 km"}
        parsed = parse_specs_table(specs)
        assert parsed["year"] == 2013

    def test_extracts_km(self):
        specs = {"Kilómetros": "75.000 km"}
        parsed = parse_specs_table(specs)
        assert parsed["km"] == 75000

    def test_extracts_fuel(self):
        specs = {"Tipo de combustible": "Nafta"}
        parsed = parse_specs_table(specs)
        assert parsed["fuel_type"] == "Nafta"

    def test_empty_specs(self):
        assert parse_specs_table({}) == {}


class TestBuildListingDetail:
    def test_builds_complete_detail(self):
        detail = build_listing_detail(
            url="https://auto.mercadolibre.com.ar/MLA-123-gol",
            title="Gol Trend 2013",
            price_text="3.500.000",
            currency_text="$",
            location="Capital Federal",
            specs={"Año": "2013", "Kilómetros": "75.000 km"},
        )
        assert detail.source_id == "MLA123"
        assert detail.title == "Gol Trend 2013"
        assert detail.price == 3500000.0
        assert detail.currency == "ARS"
        assert detail.year == 2013
        assert detail.km == 75000

    def test_handles_missing_fields(self):
        detail = build_listing_detail(
            url="https://auto.mercadolibre.com.ar/MLA-456-test",
            title=None,
            price_text=None,
            currency_text=None,
            location=None,
            specs={},
        )
        assert detail.source_id == "MLA456"
        assert detail.title is None
        assert detail.price is None
        assert detail.year is None
