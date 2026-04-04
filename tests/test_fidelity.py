"""Tests para los helpers del parser de Fidelity (sin PDFs reales)."""

from datetime import date
from decimal import Decimal

import pytest

from renta.parsers.fidelity import (
    _DIV_RE,
    _SALE_RE,
    _WITH_RE,
    _parse_date,
    _parse_decimal,
    _parse_dividends,
    _parse_stock_sales,
    _parse_withholdings,
    validate,
)
from renta.models import FidelityData, DividendEntry, StockSale, WithholdingEntry


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_january(self):
        assert _parse_date("Jan-25-2024") == date(2024, 1, 25)

    def test_march(self):
        assert _parse_date("Mar-12-2024") == date(2024, 3, 12)

    def test_september(self):
        assert _parse_date("Sep-23-2024") == date(2024, 9, 23)

    def test_december(self):
        assert _parse_date("Dec-31-2024") == date(2024, 12, 31)

    def test_invalid_returns_none(self):
        assert _parse_date("foo") is None

    def test_empty_returns_none(self):
        assert _parse_date("") is None

    def test_wrong_format_returns_none(self):
        assert _parse_date("2024-01-25") is None


# ---------------------------------------------------------------------------
# _parse_decimal
# ---------------------------------------------------------------------------

class TestParseDecimal:
    def test_plain_number(self):
        assert _parse_decimal("47.20") == Decimal("47.20")

    def test_with_dollar_sign(self):
        assert _parse_decimal("$1,893.73") == Decimal("1893.73")

    def test_negative(self):
        assert _parse_decimal("-$7.08") == Decimal("-7.08")

    def test_positive_with_plus(self):
        assert _parse_decimal("+$1,117.48") == Decimal("1117.48")

    def test_with_commas(self):
        assert _parse_decimal("$1,234,567.89") == Decimal("1234567.89")

    def test_invalid_returns_none(self):
        assert _parse_decimal("N/A") is None

    def test_empty_returns_none(self):
        assert _parse_decimal("") is None


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

class TestDivRe:
    def test_matches_dividend_line(self):
        line = "Jan-25-2024 Dividend / Interest $47.20 USD"
        m = _DIV_RE.match(line)
        assert m is not None
        assert m.group(1) == "Jan-25-2024"
        assert "$47.20" in m.group(2)

    def test_no_match_on_sale_line(self):
        line = "Mar-12-2024 May-05-2020 15.0000 $776.25 $1,893.73 + $1,117.48 USD RS"
        assert _DIV_RE.match(line) is None

    def test_no_match_on_withholding_line(self):
        line = "Jan-25-2024 Other -$7.08 USD"
        assert _DIV_RE.match(line) is None


class TestSaleRe:
    def test_matches_gain_line(self):
        line = "Mar-12-2024 May-05-2020 15.0000 $776.25 $1,893.73 + $1,117.48 USD RS"
        m = _SALE_RE.match(line)
        assert m is not None
        assert m.group(1) == "Mar-12-2024"
        assert m.group(2) == "May-05-2020"
        assert m.group(3) == "15.0000"
        assert m.group(7) == "RS"

    def test_matches_loss_line(self):
        line = "Sep-23-2024 Sep-20-2024 8.0000 $1,340.72 $1,324.23 -$16.49 USD RS"
        m = _SALE_RE.match(line)
        assert m is not None
        assert "-$16.49" in m.group(6)

    def test_no_match_on_dividend_line(self):
        line = "Jan-25-2024 Dividend / Interest $47.20 USD"
        assert _SALE_RE.match(line) is None


class TestWithRe:
    def test_matches_negative_retention(self):
        line = "Jan-25-2024 Other -$7.08 USD"
        m = _WITH_RE.match(line)
        assert m is not None
        assert m.group(1) == "Jan-25-2024"
        assert "-$7.08" in m.group(2)

    def test_matches_positive_adjustment(self):
        line = "Jan-31-2024 Other $0.02 USD"
        m = _WITH_RE.match(line)
        assert m is not None

    def test_no_match_on_dividend_line(self):
        line = "Jan-25-2024 Dividend / Interest $47.20 USD"
        assert _WITH_RE.match(line) is None


# ---------------------------------------------------------------------------
# _parse_dividends
# ---------------------------------------------------------------------------

class TestParseDividends:
    def test_parses_valid_lines(self):
        lines = [
            "Jan-25-2024 Dividend / Interest $47.20 USD",
            "Mar-15-2024 Dividend / Interest $23.10 USD",
        ]
        entries = _parse_dividends(lines, page_num=2, filename="fidelity.pdf")
        assert len(entries) == 2
        assert entries[0].date == date(2024, 1, 25)
        assert entries[0].amount_usd == Decimal("47.20")
        assert entries[1].date == date(2024, 3, 15)

    def test_skips_non_matching_lines(self):
        lines = [
            "  ",
            "Transaction Date Amount",
            "Mar-12-2024 May-05-2020 15.0000 $776.25 $1,893.73 + $1,117.48 USD RS",
        ]
        entries = _parse_dividends(lines, page_num=2, filename="fidelity.pdf")
        assert entries == []

    def test_source_ref_populated(self):
        lines = ["Jan-25-2024 Dividend / Interest $47.20 USD"]
        entries = _parse_dividends(lines, page_num=3, filename="test.pdf")
        src = entries[0].source
        assert src.file == "test.pdf"
        assert src.page == 3
        assert src.section == "Dividend income"

    def test_mixed_valid_and_invalid(self):
        lines = [
            "Header line",
            "Jan-25-2024 Dividend / Interest $47.20 USD",
            "",
            "Mar-15-2024 Dividend / Interest $23.10 USD",
            "some garbage",
        ]
        entries = _parse_dividends(lines, page_num=2, filename="f.pdf")
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# _parse_stock_sales
# ---------------------------------------------------------------------------

class TestParseStockSales:
    def test_parses_sale_with_gain(self):
        lines = ["Mar-12-2024 May-05-2020 15.0000 $776.25 $1,893.73 + $1,117.48 USD RS"]
        sales = _parse_stock_sales(lines, page_num=2, filename="f.pdf", ticker="ORCL")
        assert len(sales) == 1
        s = sales[0]
        assert s.date_sold == date(2024, 3, 12)
        assert s.date_acquired == date(2020, 5, 5)
        assert s.quantity == Decimal("15.0000")
        assert s.cost_basis_usd == Decimal("776.25")
        assert s.proceeds_usd == Decimal("1893.73")
        assert s.stock_source == "RS"
        assert s.ticker == "ORCL"

    def test_parses_sale_with_loss(self):
        lines = ["Sep-23-2024 Sep-20-2024 8.0000 $1,340.72 $1,324.23 -$16.49 USD RS"]
        sales = _parse_stock_sales(lines, page_num=2, filename="f.pdf", ticker="ORCL")
        assert len(sales) == 1
        assert sales[0].gain_loss_usd == Decimal("-16.49")

    def test_skips_non_matching_lines(self):
        lines = ["Header", "Jan-25-2024 Dividend / Interest $47.20 USD"]
        sales = _parse_stock_sales(lines, page_num=2, filename="f.pdf", ticker="ORCL")
        assert sales == []

    def test_source_ref_populated(self):
        lines = ["Mar-12-2024 May-05-2020 15.0000 $776.25 $1,893.73 + $1,117.48 USD RS"]
        sales = _parse_stock_sales(lines, page_num=4, filename="test.pdf", ticker="ORCL")
        assert sales[0].source.page == 4
        assert sales[0].source.section == "Stock sales"


# ---------------------------------------------------------------------------
# _parse_withholdings
# ---------------------------------------------------------------------------

class TestParseWithholdings:
    def test_parses_retention_and_adjustment(self):
        lines = [
            "Jan-25-2024 Other -$7.08 USD",
            "Jan-31-2024 Other $0.02 USD",
        ]
        entries = _parse_withholdings(lines, page_num=2, filename="f.pdf")
        assert len(entries) == 2
        assert entries[0].amount_usd == Decimal("-7.08")
        assert entries[1].amount_usd == Decimal("0.02")

    def test_skips_non_matching(self):
        lines = ["Header", "Jan-25-2024 Dividend / Interest $47.20 USD"]
        entries = _parse_withholdings(lines, page_num=2, filename="f.pdf")
        assert entries == []


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

class TestFidelityValidate:
    def _data(self, divs=None, sales=None, withs=None, sdiv=None, ssales=None, swith=None):
        d = FidelityData()
        d.dividends = divs or []
        d.stock_sales = sales or []
        d.withholdings = withs or []
        d.summary_dividends_usd = sdiv
        d.summary_stock_sales_usd = ssales
        d.summary_withholding_usd = swith
        return d

    def test_matching_totals_no_warnings(self):
        div = DividendEntry(date=date(2024, 1, 1), amount_usd=Decimal("47.20"))
        data = self._data(divs=[div], sdiv=Decimal("47.20"))
        assert validate(data) == []

    def test_dividend_mismatch_warning(self):
        div = DividendEntry(date=date(2024, 1, 1), amount_usd=Decimal("47.20"))
        data = self._data(divs=[div], sdiv=Decimal("100.00"))  # diff = 52.80 > 0.05
        warnings = validate(data)
        assert len(warnings) == 1
        assert "dividendos" in warnings[0].lower()

    def test_stock_sales_mismatch_warning(self):
        sale = StockSale(
            date_sold=date(2024, 1, 1),
            date_acquired=date(2020, 1, 1),
            quantity=Decimal("1"),
            cost_basis_usd=Decimal("100"),
            proceeds_usd=Decimal("150"),
            gain_loss_usd=Decimal("50.00"),
            stock_source="RS",
        )
        data = self._data(sales=[sale], ssales=Decimal("100.00"))  # diff = 50 > 0.05
        warnings = validate(data)
        assert len(warnings) == 1
        assert "ventas" in warnings[0].lower()

    def test_withholding_mismatch_warning(self):
        wh = WithholdingEntry(date=date(2024, 1, 1), amount_usd=Decimal("-7.08"))
        data = self._data(withs=[wh], swith=Decimal("-50.00"))  # diff > 0.05
        warnings = validate(data)
        assert len(warnings) == 1
        assert "retenciones" in warnings[0].lower()

    def test_none_summary_skips_check(self):
        div = DividendEntry(date=date(2024, 1, 1), amount_usd=Decimal("47.20"))
        # summary es None → no se compara
        data = self._data(divs=[div], sdiv=None)
        assert validate(data) == []

    def test_within_tolerance_no_warning(self):
        # diff exactamente 0.05 → no supera la tolerancia (> 0.05, no >=)
        div = DividendEntry(date=date(2024, 1, 1), amount_usd=Decimal("47.20"))
        data = self._data(divs=[div], sdiv=Decimal("47.25"))  # diff = 0.05
        assert validate(data) == []

    def test_just_over_tolerance_warns(self):
        # diff 0.06 → sí genera warning
        div = DividendEntry(date=date(2024, 1, 1), amount_usd=Decimal("47.20"))
        data = self._data(divs=[div], sdiv=Decimal("47.26"))  # diff = 0.06
        assert len(validate(data)) == 1
