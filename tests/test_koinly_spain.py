"""Tests para el parser koinly_spain (Informe de plusvalías para España)."""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from renta.parsers import koinly_spain
from renta.parsers.koinly_spain import _ASSET_ROW_RE, _parse_decimal, parse


SAMPLES_DIR = Path(__file__).parent.parent / "samples"
SAMPLE_PDF = SAMPLES_DIR / "Koinly 2024 Spain Capital Gains Report.pdf"


# ---------------------------------------------------------------------------
# _parse_decimal
# ---------------------------------------------------------------------------

class TestParseDecimal:
    def test_comma_decimal(self):
        assert _parse_decimal("15,55") == Decimal("15.55")

    def test_negative_comma(self):
        assert _parse_decimal("-164,12") == Decimal("-164.12")

    def test_dot_decimal(self):
        assert _parse_decimal("97.82") == Decimal("97.82")

    def test_invalid_returns_none(self):
        assert _parse_decimal("abc") is None


# ---------------------------------------------------------------------------
# _ASSET_ROW_RE — fila total vs sub-fila
# ---------------------------------------------------------------------------

class TestAssetRowRegex:
    def test_matches_asset_total_comma(self):
        assert _ASSET_ROW_RE.match("BTC 15,55 97,82 82,27") is not None

    def test_matches_asset_total_dot(self):
        assert _ASSET_ROW_RE.match("ETH 120.00 195.50 75.50") is not None

    def test_matches_negative(self):
        assert _ASSET_ROW_RE.match("LTC 280,10 115,98 -164,12") is not None

    def test_no_match_subfila_fue_vendido(self):
        assert _ASSET_ROW_RE.match("BTC fue vendido por fiat 0,00 0,00 0,00") is None

    def test_no_match_subfila_intercambiado(self):
        assert _ASSET_ROW_RE.match("XRP fue intercambiado por otra crypto 0,31 0,34 0,03") is None

    def test_no_match_header(self):
        assert _ASSET_ROW_RE.match("Activo Valor (EUR) Ingresos (EUR) Ganancia / pérdida") is None

    def test_no_match_empty(self):
        assert _ASSET_ROW_RE.match("") is None

    def test_captures_ticker_and_values(self):
        m = _ASSET_ROW_RE.match("LTC 280,10 115,98 -164,12")
        assert m is not None
        assert m.group(1) == "LTC"
        assert _parse_decimal(m.group(2)) == Decimal("280.10")
        assert _parse_decimal(m.group(3)) == Decimal("115.98")
        assert _parse_decimal(m.group(4)) == Decimal("-164.12")


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detects_spain_report(self):
        text = "Koinly\nInforme de plusvalías para España para el año 2024\nActivo Valor (EUR)"
        assert koinly_spain.detect(text) is True

    def test_rejects_complete_tax_report(self):
        text = "Koinly - Complete Tax Report\n1 ene 2024 hasta 31 dic 2024\nTabla de contenidos"
        assert koinly_spain.detect(text) is False

    def test_rejects_non_koinly(self):
        text = "Informe de plusvalías para España\nOtro software"
        assert koinly_spain.detect(text) is False


# ---------------------------------------------------------------------------
# parse — sobre el sample PDF
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="sample PDF no generado")
class TestParseSample:
    def test_parse_returns_btc_and_eth(self):
        data = parse(SAMPLE_PDF)
        assert "BTC" in data.asset_totals
        assert "ETH" in data.asset_totals

    def test_btc_valores(self):
        data = parse(SAMPLE_PDF)
        btc = data.asset_totals["BTC"]
        assert btc["valor_eur"] == Decimal("15.55")
        assert btc["ingresos_eur"] == Decimal("97.82")
        assert btc["ganancia_eur"] == Decimal("82.27")

    def test_eth_valores(self):
        data = parse(SAMPLE_PDF)
        eth = data.asset_totals["ETH"]
        assert eth["valor_eur"] == Decimal("120.00")
        assert eth["ingresos_eur"] == Decimal("195.50")
        assert eth["ganancia_eur"] == Decimal("75.50")

    def test_year_hint(self):
        data = parse(SAMPLE_PDF)
        assert koinly_spain.year_hint(data) == 2024

    def test_stats_summary(self):
        data = parse(SAMPLE_PDF)
        summary = koinly_spain.stats_summary(data)
        assert "2" in summary  # 2 activos

    def test_subfila_no_duplica_activos(self):
        """Las sub-filas ('BTC fue vendido...') no generan entradas extra."""
        data = parse(SAMPLE_PDF)
        assert len(data.asset_totals) == 2  # solo BTC y ETH

    def test_validate_ok(self):
        data = parse(SAMPLE_PDF)
        assert koinly_spain.validate(data) == []


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_empty_asset_totals_returns_warning(self):
        from renta.models import KoinlySpainData
        data = KoinlySpainData()
        warnings = koinly_spain.validate(data)
        assert len(warnings) == 1
        assert "no se encontraron activos" in warnings[0].lower()
