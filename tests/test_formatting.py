"""Tests para el módulo de formateo de importes."""

import io
from decimal import Decimal

from renta.formatting import bold, cyan, dim, format_crypto_qty, format_es_number, format_eur, format_rate, format_usd, green, red, yellow


class TestFormatEsNumber:
    def test_cero(self):
        assert format_es_number(Decimal("0")) == "0,00"

    def test_pequeño(self):
        assert format_es_number(Decimal("9.99")) == "9,99"

    def test_miles(self):
        assert format_es_number(Decimal("1234.56")) == "1.234,56"

    def test_millones(self):
        assert format_es_number(Decimal("1234567.89")) == "1.234.567,89"

    def test_negativo(self):
        assert format_es_number(Decimal("-99.99")) == "-99,99"

    def test_negativo_con_miles(self):
        assert format_es_number(Decimal("-1234.56")) == "-1.234,56"

    def test_sin_decimales(self):
        assert format_es_number(Decimal("1234"), decimals=0) == "1.234"

    def test_ceros_finales_preservados(self):
        assert format_es_number(Decimal("1.5")) == "1,50"


class TestFormatEur:
    def test_basico(self):
        assert format_eur(Decimal("462.96")) == "462,96 €"

    def test_miles(self):
        assert format_eur(Decimal("1234.56")) == "1.234,56 €"

    def test_negativo(self):
        assert format_eur(Decimal("-7.08")) == "-7,08 €"

    def test_cero(self):
        assert format_eur(Decimal("0")) == "0,00 €"


class TestFormatUsd:
    def test_basico(self):
        assert format_usd(Decimal("47.20")) == "$47,20"

    def test_miles(self):
        assert format_usd(Decimal("1893.73")) == "$1.893,73"

    def test_negativo(self):
        assert format_usd(Decimal("-7.08")) == "-$7,08"

    def test_negativo_con_miles(self):
        assert format_usd(Decimal("-1340.72")) == "-$1.340,72"

    def test_cero(self):
        assert format_usd(Decimal("0")) == "$0,00"


class TestFormatCryptoQty:
    def test_entero(self):
        assert format_crypto_qty(Decimal("2.0000")) == "2"

    def test_fraccion_pequeña(self):
        assert format_crypto_qty(Decimal("0.00006762")) == "0,00006762"

    def test_fraccion_con_ceros_finales(self):
        assert format_crypto_qty(Decimal("0.12345000")) == "0,12345"

    def test_con_miles(self):
        assert format_crypto_qty(Decimal("12345.5")) == "12.345,5"

    def test_entero_con_miles(self):
        assert format_crypto_qty(Decimal("100000")) == "100.000"

    def test_uno(self):
        assert format_crypto_qty(Decimal("1")) == "1"

    def test_fraccion_tipica_btc(self):
        assert format_crypto_qty(Decimal("0.00152000")) == "0,00152"


class TestFormatRate:
    def test_tipico_bce(self):
        assert format_rate(Decimal("1.0782")) == "1,0782"

    def test_mayor_que_uno(self):
        assert format_rate(Decimal("1.2500")) == "1,2500"

    def test_menor_que_uno(self):
        assert format_rate(Decimal("0.8953")) == "0,8953"


class TestColorHelpers:
    def _tty(self):
        """Stream que simula un terminal (isatty=True)."""
        class FakeTTY:
            def isatty(self): return True
        return FakeTTY()

    def _notty(self):
        return io.StringIO()

    def test_no_color_env_desactiva_colores(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert red("x", self._tty()) == "x"
        assert green("x", self._tty()) == "x"
        assert yellow("x", self._tty()) == "x"

    def test_force_color_activa_colores_en_no_tty(self, monkeypatch):
        monkeypatch.setenv("FORCE_COLOR", "1")
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert red("x", self._notty()) == "\x1b[31mx\x1b[0m"
        assert green("x", self._notty()) == "\x1b[32mx\x1b[0m"
        assert yellow("x", self._notty()) == "\x1b[33mx\x1b[0m"
        assert cyan("x", self._notty()) == "\x1b[36mx\x1b[0m"
        assert bold("x", self._notty()) == "\x1b[1mx\x1b[0m"
        assert dim("x", self._notty()) == "\x1b[2mx\x1b[0m"

    def test_sin_tty_sin_color(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert red("x", self._notty()) == "x"
        assert bold("x", self._notty()) == "x"

    def test_tty_sin_env_activa_colores(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert red("x", self._tty()) == "\x1b[31mx\x1b[0m"
        assert green("x", self._tty()) == "\x1b[32mx\x1b[0m"

    def test_no_color_tiene_prioridad_sobre_force_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert red("x", self._tty()) == "x"
