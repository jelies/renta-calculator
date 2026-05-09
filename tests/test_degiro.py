"""Tests para el parser DEGIRO."""

from decimal import Decimal
from pathlib import Path

import pytest

import renta.parsers.degiro as degiro
from renta.models import DegiroData
from renta.parsers.degiro import _build_page_locator

SAMPLES_DIR = Path(__file__).parent.parent / "samples"
SAMPLE_PDF = SAMPLES_DIR / "1-samples" / "DEGIRO 2024 informe fiscal.pdf"


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detects_degiro_lowercase(self):
        assert degiro.detect("flatexdegiro bank ag\ninforme fiscal 2024") is True

    def test_detects_degiro_mixed_case(self):
        assert degiro.detect("flatexDEGIRO Bank AG\nInforme Fiscal para el año 2024") is True

    def test_does_not_detect_other_broker(self):
        assert degiro.detect("Fidelity Investments\nCustom Transaction Summary") is False

    def test_does_not_detect_empty(self):
        assert degiro.detect("") is False


# ---------------------------------------------------------------------------
# parse (requiere PDF sintético en samples/)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="PDF sintético no generado")
class TestParse:
    def setup_method(self):
        self.data = degiro.parse(SAMPLE_PDF)

    def test_year_detected(self):
        assert self.data.year == 2024

    def test_dividends_count(self):
        assert len(self.data.dividends) == 2

    def test_dividend_values(self):
        # Primer dividendo: NL PROSUS NV 1,50 -0,23 1,28
        nl_div = next(d for d in self.data.dividends if d.country == "NL")
        assert nl_div.product == "PROSUS NV"
        assert nl_div.gross_eur == Decimal("1.50")
        assert nl_div.withholding_eur == Decimal("-0.23")
        assert nl_div.net_eur == Decimal("1.28")

    def test_dividend_us_values(self):
        # Segundo dividendo: US ARES CAPITAL CORP 2,56 -0,38 2,18
        us_div = next(d for d in self.data.dividends if d.country == "US")
        assert us_div.product == "ARES CAPITAL CORP"
        assert us_div.gross_eur == Decimal("2.56")
        assert us_div.withholding_eur == Decimal("-0.38")

    def test_dividend_summary_totals(self):
        assert self.data.summary_dividends_gross_eur == Decimal("4.06")
        assert self.data.summary_dividends_withholding_eur == Decimal("-0.59")
        assert self.data.summary_dividends_net_eur == Decimal("3.48")

    def test_sales_count(self):
        # El sample 2024 solo tiene la sección resumida (sin ventas individuales)
        assert len(self.data.stock_sales) == 0

    def test_sale_summary_total(self):
        # El sample 2024 tiene Total 0,00 EUR
        assert self.data.summary_stock_sales_total_eur == Decimal("0.00")

    def test_sources_populated(self):
        for div in self.data.dividends:
            assert div.source is not None
            assert div.source.file == SAMPLE_PDF.name
            assert div.source.page >= 1


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="PDF sintético no generado")
class TestValidate:
    def test_valid_data_no_warnings(self):
        data = degiro.parse(SAMPLE_PDF)
        warnings = degiro.validate(data)
        assert warnings == []

    def test_tampered_total_generates_warning(self):
        data = degiro.parse(SAMPLE_PDF)
        data.summary_dividends_gross_eur = Decimal("99.99")
        warnings = degiro.validate(data)
        assert len(warnings) == 1
        assert "dividendos" in warnings[0].lower()

    def test_no_summary_no_warning(self):
        from renta.models import DegiroDividend
        data = DegiroData()
        data.dividends = [
            DegiroDividend("US", "ACME", Decimal("10"), Decimal("-1.5"), Decimal("8.5"))
        ]
        # Sin summary → no hay qué validar
        assert degiro.validate(data) == []


# ---------------------------------------------------------------------------
# stats_summary, year_hint, usd_dates
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _build_page_locator
# ---------------------------------------------------------------------------

class TestBuildPageLocator:
    def _locator(self, pages):
        return _build_page_locator(pages)

    def test_single_page_always_returns_1(self):
        locate = self._locator(["hello world"])
        assert locate(0) == 1
        assert locate(5) == 1
        assert locate(10) == 1

    def test_two_pages_offset_0_is_page_1(self):
        # pages: "abc" (len=3) + "\n" + "def" (len=3) → all_text = "abc\ndef"
        locate = self._locator(["abc", "def"])
        assert locate(0) == 1

    def test_two_pages_start_of_second_page(self):
        # página 2 empieza en offset 4 ("abc\n" = 4 chars)
        locate = self._locator(["abc", "def"])
        assert locate(4) == 2

    def test_two_pages_middle_of_second_page(self):
        locate = self._locator(["abc", "def"])
        assert locate(5) == 2

    def test_three_pages(self):
        # "aa"(2) + "\n" + "bbb"(3) + "\n" + "cccc"(4)
        # página 1: offsets 0-2, página 2: offsets 3-6, página 3: offsets 7-10
        locate = self._locator(["aa", "bbb", "cccc"])
        assert locate(0) == 1
        assert locate(3) == 2
        assert locate(6) == 2
        assert locate(7) == 3
        assert locate(10) == 3

    def test_last_page(self):
        pages = ["page one text", "page two text", "page three text"]
        all_text = "\n".join(pages)
        locate = self._locator(pages)
        assert locate(len(all_text) - 1) == 3


class TestMetadata:
    def test_stats_summary(self):
        data = DegiroData()
        data.dividends = [object(), object()]  # type: ignore
        data.stock_sales = [object()]  # type: ignore
        assert degiro.stats_summary(data) == "2 dividendos, 1 ventas (DEGIRO)"

    def test_year_hint_returns_year(self):
        data = DegiroData(year=2024)
        assert degiro.year_hint(data) == 2024

    def test_year_hint_none(self):
        data = DegiroData()
        assert degiro.year_hint(data) is None

    def test_usd_dates_empty(self):
        data = DegiroData()
        assert degiro.usd_dates(data) == set()
