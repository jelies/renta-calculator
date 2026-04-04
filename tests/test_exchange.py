"""Tests para ExchangeRateProvider (sin red — construcción directa con dict)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from renta.exchange import ExchangeRateProvider


# ---------------------------------------------------------------------------
# get_rate
# ---------------------------------------------------------------------------

class TestGetRate:
    def test_exact_date_found(self):
        d = date(2024, 1, 15)
        provider = ExchangeRateProvider({d: Decimal("1.2500")})
        rate, effective = provider.get_rate(d)
        assert rate == Decimal("1.2500")
        assert effective == d

    def test_weekend_falls_back_to_friday(self):
        # Sábado 20 de enero 2024 → usa el viernes 19
        friday = date(2024, 1, 19)
        saturday = date(2024, 1, 20)
        provider = ExchangeRateProvider({friday: Decimal("1.1000")})
        rate, effective = provider.get_rate(saturday)
        assert rate == Decimal("1.1000")
        assert effective == friday

    def test_sunday_falls_back_to_friday(self):
        friday = date(2024, 1, 19)
        sunday = date(2024, 1, 21)
        provider = ExchangeRateProvider({friday: Decimal("1.1000")})
        rate, effective = provider.get_rate(sunday)
        assert effective == friday

    def test_holiday_falls_back_to_previous_business_day(self):
        # Solo hay tasa el viernes 12; se consulta el lunes 15 (festivo simulado)
        friday = date(2024, 1, 12)
        monday = date(2024, 1, 15)
        provider = ExchangeRateProvider({friday: Decimal("1.0800")})
        rate, effective = provider.get_rate(monday)
        assert effective == friday
        assert rate == Decimal("1.0800")

    def test_14_day_limit_raises(self):
        # Solo hay tasa el 1 de enero; se consulta el 16 (15 días después)
        provider = ExchangeRateProvider({date(2024, 1, 1): Decimal("1.1000")})
        with pytest.raises(ValueError, match="14 días"):
            provider.get_rate(date(2024, 1, 16))

    def test_empty_rates_raises(self):
        provider = ExchangeRateProvider({})
        with pytest.raises(ValueError):
            provider.get_rate(date(2024, 1, 15))


# ---------------------------------------------------------------------------
# usd_to_eur
# ---------------------------------------------------------------------------

class TestUsdToEur:
    def test_basic_conversion(self):
        # $100 a 1.25 USD/EUR = €80.00 exactos
        provider = ExchangeRateProvider({date(2024, 1, 15): Decimal("1.2500")})
        eur, rate, effective = provider.usd_to_eur(Decimal("100.00"), date(2024, 1, 15))
        assert eur == Decimal("80.00")
        assert rate == Decimal("1.2500")
        assert effective == date(2024, 1, 15)

    def test_result_quantized_to_2_decimals(self):
        # $100 a 1.1050 → 100/1.1050 = 90.4977... → 90.50
        provider = ExchangeRateProvider({date(2024, 1, 15): Decimal("1.1050")})
        eur, _, _ = provider.usd_to_eur(Decimal("100.00"), date(2024, 1, 15))
        assert eur == eur.quantize(Decimal("0.01"))
        # Verificamos que tiene exactamente 2 decimales
        assert str(eur).split(".")[-1] in {str(i).zfill(2) for i in range(100)}

    def test_propagates_value_error_when_no_rate(self):
        provider = ExchangeRateProvider({})
        with pytest.raises(ValueError):
            provider.usd_to_eur(Decimal("100.00"), date(2024, 1, 15))

    def test_negative_amount(self):
        # Retenciones son negativas
        provider = ExchangeRateProvider({date(2024, 1, 15): Decimal("1.2500")})
        eur, _, _ = provider.usd_to_eur(Decimal("-7.00"), date(2024, 1, 15))
        assert eur == Decimal("-5.60")


# ---------------------------------------------------------------------------
# Constructor directo (sin red)
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_direct_construction_no_network(self):
        rates = {date(2024, 1, 2): Decimal("1.1050")}
        provider = ExchangeRateProvider(rates)
        rate, _ = provider.get_rate(date(2024, 1, 2))
        assert rate == Decimal("1.1050")

    def test_all_rates_used_returns_copy(self):
        rates = {date(2024, 1, 2): Decimal("1.1050")}
        provider = ExchangeRateProvider(rates)
        result = provider.all_rates_used()
        assert result == rates
        # Es una copia, no la misma referencia
        result[date(2024, 1, 3)] = Decimal("1.2000")
        assert date(2024, 1, 3) not in provider.all_rates_used()
