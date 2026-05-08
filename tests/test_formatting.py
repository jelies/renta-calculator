"""Tests para el módulo de formateo de importes."""

from decimal import Decimal

from renta.formatting import format_es_number, format_eur, format_rate, format_usd


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


class TestFormatRate:
    def test_tipico_bce(self):
        assert format_rate(Decimal("1.0782")) == "1,0782"

    def test_mayor_que_uno(self):
        assert format_rate(Decimal("1.2500")) == "1,2500"

    def test_menor_que_uno(self):
        assert format_rate(Decimal("0.8953")) == "0,8953"
