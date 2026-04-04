"""Tests para Calculator — lógica fiscal de conversión y cálculo."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from renta.calculator import Calculator
from renta.exchange import ExchangeRateProvider
from renta.models import FidelityData, KoinlyData

from factories import (
    make_crypto_gain,
    make_crypto_reward,
    make_dividend,
    make_stock_sale,
    make_withholding,
)

# Tasa fija usada en todos los tests: 1.25 USD = 1 EUR → $100 = €80.00
_RATE = Decimal("1.2500")
_DATE = date(2024, 1, 15)
_DATE2 = date(2024, 1, 16)
_DATE3 = date(2024, 1, 17)


def _provider(*extra_dates: date) -> ExchangeRateProvider:
    """Provider con tasa 1.25 para _DATE, _DATE2, _DATE3 y cualquier fecha extra."""
    rates = {
        _DATE: _RATE,
        _DATE2: _RATE,
        _DATE3: _RATE,
        date(2024, 3, 12): _RATE,
        date(2024, 5, 5): _RATE,
        date(2020, 5, 5): _RATE,
    }
    for d in extra_dates:
        rates[d] = _RATE
    return ExchangeRateProvider(rates)


def _calc(*extra_dates: date) -> Calculator:
    return Calculator(_provider(*extra_dates))


def _calc_no_rates() -> Calculator:
    return Calculator(ExchangeRateProvider({}))


# ---------------------------------------------------------------------------
# Dividendos
# ---------------------------------------------------------------------------

class TestCalcDividendos:
    def test_single_dividend_converts_correctly(self):
        # $100 / 1.25 = €80.00
        calc = _calc()
        casilla = calc._calc_dividendos([make_dividend(_DATE, "100.00")])
        assert casilla.valor == Decimal("80.00")
        assert casilla.numero == "0029"
        assert len(casilla.desglose) == 1
        assert casilla.desglose[0].importe_eur == Decimal("80.00")
        assert casilla.errores == []

    def test_multiple_dividends_sum(self):
        # Tres dividendos de $100 = €240.00
        calc = _calc()
        divs = [
            make_dividend(_DATE, "100.00"),
            make_dividend(_DATE2, "100.00"),
            make_dividend(_DATE3, "100.00"),
        ]
        casilla = calc._calc_dividendos(divs)
        assert casilla.valor == Decimal("240.00")
        assert len(casilla.desglose) == 3

    def test_rate_failure_sets_valor_none(self):
        # Sin tasa disponible → valor debe ser None
        calc = _calc_no_rates()
        div = make_dividend(_DATE, "100.00")
        casilla = calc._calc_dividendos([div])
        assert casilla.valor is None
        assert len(casilla.errores) == 1
        assert casilla.desglose[0].importe_eur is None
        assert casilla.desglose[0].error is not None
        # El modelo no debe quedar con un EUR inventado
        assert div.amount_eur is None

    def test_partial_failure_taints_entire_casilla(self):
        # Un dividendo ok + uno sin tasa → valor None
        calc = _calc()  # solo tiene tasa para _DATE
        div_ok = make_dividend(_DATE, "100.00")
        div_fail = make_dividend(date(2024, 6, 1), "50.00")  # fecha sin tasa
        casilla = calc._calc_dividendos([div_ok, div_fail])
        assert casilla.valor is None
        assert len(casilla.errores) == 1
        assert len(casilla.desglose) == 2

    def test_empty_dividends_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_dividendos([])
        assert casilla.valor == Decimal("0.00")
        assert casilla.errores == []
        assert casilla.desglose == []

    def test_weekend_fallback_generates_warning(self):
        # Sábado 20 → usa viernes 19
        friday = date(2024, 1, 19)
        saturday = date(2024, 1, 20)
        calc = _calc(friday)  # tasa disponible solo el viernes
        div = make_dividend(saturday, "100.00")
        casilla = calc._calc_dividendos([div])
        # El cálculo debe tener éxito usando el viernes
        assert casilla.valor is not None
        assert len(calc._warnings) == 1
        assert "2024-01-19" in calc._warnings[0]


# ---------------------------------------------------------------------------
# Ganancias de acciones (RSUs)
# ---------------------------------------------------------------------------

class TestCalcGananciasAcciones:
    def _sale_with_gain(self):
        # cost $500 / 1.25 = €400; proceeds $750 / 1.25 = €600; gain = €200
        return make_stock_sale(
            date_sold=date(2024, 3, 12),
            date_acquired=date(2020, 5, 5),
            cost_basis_usd="500.00",
            proceeds_usd="750.00",
            gain_loss_usd="250.00",
        )

    def test_single_sale_gain(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([self._sale_with_gain()])
        assert casilla.valor == Decimal("200.00")
        assert casilla.errores == []

    def test_sale_mutates_model_with_eur_values(self):
        calc = _calc()
        sale = self._sale_with_gain()
        calc._calc_ganancias_acciones([sale])
        assert sale.cost_basis_eur == Decimal("400.00")
        assert sale.proceeds_eur == Decimal("600.00")
        assert sale.gain_loss_eur == Decimal("200.00")

    def test_sale_loss_negative(self):
        # proceeds < cost → ganancia negativa
        sale = make_stock_sale(
            date_sold=date(2024, 3, 12),
            date_acquired=date(2020, 5, 5),
            cost_basis_usd="750.00",
            proceeds_usd="500.00",
            gain_loss_usd="-250.00",
        )
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([sale])
        assert casilla.valor == Decimal("-200.00")

    def test_vesting_rate_failure_sets_valor_none(self):
        sale = make_stock_sale(
            date_sold=date(2024, 3, 12),
            date_acquired=date(1999, 1, 1),  # sin tasa
        )
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([sale])
        assert casilla.valor is None
        assert len(casilla.errores) == 1
        assert sale.cost_basis_eur is None

    def test_sold_rate_failure_sets_valor_none(self):
        sale = make_stock_sale(
            date_sold=date(1999, 1, 1),  # sin tasa
            date_acquired=date(2020, 5, 5),
        )
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([sale])
        assert casilla.valor is None
        assert len(casilla.errores) == 1

    def test_multiple_sales_total(self):
        calc = _calc()
        sales = [self._sale_with_gain(), self._sale_with_gain()]
        casilla = calc._calc_ganancias_acciones(sales)
        assert casilla.valor == Decimal("400.00")

    def test_empty_sales_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([])
        assert casilla.valor == Decimal("0.00")


# ---------------------------------------------------------------------------
# Doble imposición (retenciones USA)
# ---------------------------------------------------------------------------

class TestCalcDobleImposicion:
    def test_single_withholding_negative(self):
        # Retención: -$7.50 / 1.25 = -€6.00 → valor = abs = €6.00
        calc = _calc()
        wh = make_withholding(_DATE, "-7.50")
        casilla = calc._calc_doble_imposicion([wh])
        assert casilla.valor == Decimal("6.00")
        assert casilla.numero == "0588-0589"

    def test_mixed_retention_and_adjustment(self):
        # -$10.00 + $2.50 = -$7.50 / 1.25 = -€6.00 → abs = €6.00
        calc = _calc()
        whs = [
            make_withholding(_DATE, "-10.00"),
            make_withholding(_DATE2, "2.50"),
        ]
        casilla = calc._calc_doble_imposicion(whs)
        assert casilla.valor == Decimal("6.00")

    def test_rate_failure_sets_valor_none(self):
        calc = _calc_no_rates()
        casilla = calc._calc_doble_imposicion([make_withholding(_DATE, "-7.00")])
        assert casilla.valor is None
        assert len(casilla.errores) == 1

    def test_empty_withholdings_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_doble_imposicion([])
        assert casilla.valor == Decimal("0.00")


# ---------------------------------------------------------------------------
# Ganancias crypto (ya en EUR, sin conversión)
# ---------------------------------------------------------------------------

class TestCalcGananciasCrypto:
    def test_single_gain(self):
        calc = _calc()
        g = make_crypto_gain(cost_eur="15.55", proceeds_eur="97.82", gain_loss_eur="82.27")
        casilla = calc._calc_ganancias_crypto([g])
        assert casilla.valor == Decimal("82.27")
        assert casilla.errores == []

    def test_multiple_gains_sum(self):
        calc = _calc()
        gains = [
            make_crypto_gain(cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00"),
            make_crypto_gain(cost_eur="20.00", proceeds_eur="80.00", gain_loss_eur="60.00"),
        ]
        casilla = calc._calc_ganancias_crypto(gains)
        assert casilla.valor == Decimal("100.00")

    def test_crypto_loss(self):
        calc = _calc()
        g = make_crypto_gain(cost_eur="100.00", proceeds_eur="60.00", gain_loss_eur="-40.00")
        casilla = calc._calc_ganancias_crypto([g])
        assert casilla.valor == Decimal("-40.00")

    def test_empty_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_ganancias_crypto([])
        assert casilla.valor == Decimal("0.00")


# ---------------------------------------------------------------------------
# Rendimientos staking/rewards (ya en EUR)
# ---------------------------------------------------------------------------

class TestCalcRendimientosCrypto:
    def test_rewards_sum(self):
        calc = _calc()
        rewards = [
            make_crypto_reward(asset="ADA", price_eur="1.00"),
            make_crypto_reward(asset="ADA", price_eur="2.00"),
            make_crypto_reward(asset="STETH", price_eur="5.00"),
        ]
        casilla = calc._calc_rendimientos_crypto(rewards)
        assert casilla.valor == Decimal("8.00")

    def test_rewards_grouped_by_asset_in_desglose(self):
        calc = _calc()
        rewards = [
            make_crypto_reward(asset="ADA", price_eur="1.00"),
            make_crypto_reward(asset="ADA", price_eur="2.00"),
            make_crypto_reward(asset="STETH", price_eur="5.00"),
        ]
        casilla = calc._calc_rendimientos_crypto(rewards)
        # Dos activos distintos → dos líneas de desglose
        assert len(casilla.desglose) == 2
        # Ordenados alfabéticamente
        assert casilla.desglose[0].descripcion == "Staking rewards ADA"
        assert casilla.desglose[1].descripcion == "Staking rewards STETH"

    def test_empty_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_rendimientos_crypto([])
        assert casilla.valor == Decimal("0.00")
        assert casilla.desglose == []


# ---------------------------------------------------------------------------
# Integración: calculate()
# ---------------------------------------------------------------------------

class TestCalculateIntegration:
    def test_full_calculate_returns_all_casillas(self):
        calc = _calc()
        fidelity = FidelityData(
            dividends=[make_dividend(_DATE, "100.00")],
            stock_sales=[make_stock_sale()],
            withholdings=[make_withholding(_DATE, "-7.50")],
        )
        koinly = KoinlyData(
            capital_gains=[make_crypto_gain()],
            rewards=[make_crypto_reward()],
        )
        resultado = calc.calculate(fidelity, koinly, year=2024)
        assert resultado.year == 2024
        assert resultado.dividendos is not None
        assert resultado.ganancias_acciones is not None
        assert resultado.doble_imposicion is not None
        assert resultado.ganancias_crypto is not None
        assert resultado.rendimientos_crypto is not None
        assert len(resultado.exchange_rates_used) > 0

    def test_calculate_empty_data_no_errors(self):
        calc = _calc()
        resultado = calc.calculate(FidelityData(), KoinlyData(), year=2024)
        assert resultado.dividendos.valor == Decimal("0.00")
        assert resultado.ganancias_acciones.valor == Decimal("0.00")
        assert resultado.doble_imposicion.valor == Decimal("0.00")
        assert resultado.ganancias_crypto.valor == Decimal("0.00")
        assert resultado.rendimientos_crypto.valor == Decimal("0.00")
        assert resultado.warnings == []
