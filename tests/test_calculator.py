"""Tests para Calculator — lógica fiscal de conversión y cálculo."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from renta.calculator import Calculator
from renta.exchange import ExchangeRateProvider
from renta.models import DegiroData, FidelityData, KoinlyData

from factories import (
    make_crypto_gain,
    make_crypto_reward,
    make_degiro_dividend,
    make_degiro_stock_sale,
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
        assert "fin de semana" in calc._warnings[0]

    def test_holiday_fallback_generates_warning_with_reason(self):
        # Miércoles 1 de enero (festivo) → usa el día anterior disponible
        new_years_eve = date(2024, 12, 31)  # martes
        new_years_day = date(2025, 1, 1)   # miércoles (festivo)
        calc = _calc(new_years_eve)
        div = make_dividend(new_years_day, "100.00")
        casilla = calc._calc_dividendos([div])
        assert casilla.valor is not None
        assert len(calc._warnings) == 1
        assert "día festivo/sin cotización del BCE" in calc._warnings[0]


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
        parsed_data = {
            "fidelity": FidelityData(
                dividends=[make_dividend(_DATE, "100.00")],
                stock_sales=[make_stock_sale()],
                withholdings=[make_withholding(_DATE, "-7.50")],
            ),
            "koinly": KoinlyData(
                capital_gains=[make_crypto_gain()],
                rewards=[make_crypto_reward()],
            ),
        }
        resultado = calc.calculate(parsed_data, year=2024)
        assert resultado.year == 2024
        assert resultado.dividendos is not None
        assert resultado.ganancias_acciones is not None
        assert resultado.doble_imposicion is not None
        assert resultado.ganancias_crypto is not None
        assert resultado.rendimientos_crypto is not None
        assert len(resultado.exchange_rates_used) > 0

    def test_calculate_empty_data_no_errors(self):
        calc = _calc()
        resultado = calc.calculate({}, year=2024)
        assert resultado.dividendos.valor == Decimal("0.00")
        assert resultado.ganancias_acciones.valor == Decimal("0.00")
        assert resultado.doble_imposicion.valor == Decimal("0.00")
        assert resultado.ganancias_crypto.valor == Decimal("0.00")
        assert resultado.rendimientos_crypto.valor == Decimal("0.00")
        assert resultado.warnings == []

    def test_casillas_property_returns_all_non_none(self):
        calc = _calc()
        resultado = calc.calculate({}, year=2024)
        casillas = resultado.casillas
        assert len(casillas) == 5
        assert all(c is not None for c in casillas)

    def test_casillas_have_template_set(self):
        calc = _calc()
        resultado = calc.calculate({}, year=2024)
        for casilla in resultado.casillas:
            assert casilla.template is not None, f"Casilla {casilla.numero} sin template"


# ---------------------------------------------------------------------------
# DEGIRO: dividendos (ya en EUR)
# ---------------------------------------------------------------------------

class TestCalcDividendosDegiro:
    def test_single_dividend(self):
        calc = _calc()
        div = make_degiro_dividend(gross_eur="2.56")
        casilla = calc._calc_dividendos_degiro([div])
        assert casilla.valor == Decimal("2.56")
        assert casilla.numero == "0029"
        assert casilla.errores == []

    def test_multiple_dividends_sum(self):
        calc = _calc()
        divs = [
            make_degiro_dividend(gross_eur="1.50"),
            make_degiro_dividend(gross_eur="2.56"),
        ]
        casilla = calc._calc_dividendos_degiro(divs)
        assert casilla.valor == Decimal("4.06")
        assert len(casilla.desglose) == 2

    def test_empty_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_dividendos_degiro([])
        assert casilla.valor == Decimal("0.00")
        assert casilla.desglose == []

    def test_desglose_has_activo(self):
        calc = _calc()
        div = make_degiro_dividend(country="NL", product="PROSUS NV", gross_eur="1.50")
        casilla = calc._calc_dividendos_degiro([div])
        assert casilla.desglose[0].extras["activo"] == "PROSUS NV (NL)"


# ---------------------------------------------------------------------------
# DEGIRO: doble imposición (retenciones en origen, ya en EUR)
# ---------------------------------------------------------------------------

class TestCalcDobleImposicionDegiro:
    def test_single_withholding(self):
        calc = _calc()
        div = make_degiro_dividend(withholding_eur="-0.38")
        casilla = calc._calc_doble_imposicion_degiro([div])
        assert casilla.valor == Decimal("0.38")
        assert casilla.numero == "0588-0589"

    def test_multiple_withholdings_sum(self):
        calc = _calc()
        divs = [
            make_degiro_dividend(withholding_eur="-0.23"),
            make_degiro_dividend(withholding_eur="-0.38"),
        ]
        casilla = calc._calc_doble_imposicion_degiro(divs)
        assert casilla.valor == Decimal("0.61")

    def test_zero_withholding_excluded(self):
        calc = _calc()
        divs = [
            make_degiro_dividend(withholding_eur="0"),
            make_degiro_dividend(withholding_eur="-0.38"),
        ]
        casilla = calc._calc_doble_imposicion_degiro(divs)
        assert casilla.valor == Decimal("0.38")
        assert len(casilla.desglose) == 1  # solo la que tiene retención

    def test_empty_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_doble_imposicion_degiro([])
        assert casilla.valor == Decimal("0.00")


# ---------------------------------------------------------------------------
# DEGIRO: ganancias de ventas (ya en EUR)
# ---------------------------------------------------------------------------

class TestCalcGananciasDegiro:
    def test_single_sale_gain(self):
        calc = _calc()
        sale = make_degiro_stock_sale(gain_loss_eur="1.9045")
        casilla = calc._calc_ganancias_degiro([sale])
        assert casilla.valor == Decimal("1.90")
        assert casilla.numero == "0328-0337"
        assert casilla.errores == []

    def test_single_sale_loss(self):
        calc = _calc()
        sale = make_degiro_stock_sale(gain_loss_eur="-5.23")
        casilla = calc._calc_ganancias_degiro([sale])
        assert casilla.valor == Decimal("-5.23")

    def test_multiple_sales_sum(self):
        calc = _calc()
        sales = [
            make_degiro_stock_sale(gain_loss_eur="1.9045"),
            make_degiro_stock_sale(gain_loss_eur="-5.2300"),
        ]
        casilla = calc._calc_ganancias_degiro(sales)
        assert casilla.valor == Decimal("-3.33")

    def test_empty_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_ganancias_degiro([])
        assert casilla.valor == Decimal("0.00")

    def test_desglose_has_tipo_accion_degiro(self):
        calc = _calc()
        sale = make_degiro_stock_sale()
        casilla = calc._calc_ganancias_degiro([sale])
        assert casilla.desglose[0].extras["tipo_accion"] == "DEGIRO"

    def test_extras_totals(self):
        calc = _calc()
        # value_eur=38.61, gain=1.9045 → cost=36.7055
        sale = make_degiro_stock_sale(value_eur="38.61", gain_loss_eur="1.9045")
        casilla = calc._calc_ganancias_degiro([sale])
        assert casilla.extras["total_proceeds"] == Decimal("38.61")


# ---------------------------------------------------------------------------
# _merge_casillas
# ---------------------------------------------------------------------------

class TestMergeCasillas:
    def test_both_empty_returns_first(self):
        calc = _calc()
        c1 = calc._calc_dividendos_degiro([])
        c2 = calc._calc_dividendos([])
        merged = calc._merge_casillas(c1, c2)
        # Ambas vacías (sin desglose) → devuelve la primera
        assert merged is c1

    def test_one_empty_returns_non_empty(self):
        calc = _calc()
        c_empty = calc._calc_dividendos_degiro([])
        c_with_data = calc._calc_dividendos_degiro([make_degiro_dividend(gross_eur="2.56")])
        merged = calc._merge_casillas(c_empty, c_with_data)
        assert merged is c_with_data

    def test_two_non_empty_merged(self):
        calc = _calc()
        c1 = calc._calc_dividendos_degiro([make_degiro_dividend(gross_eur="1.50")])
        c2 = calc._calc_dividendos_degiro([make_degiro_dividend(gross_eur="2.56")])
        merged = calc._merge_casillas(c1, c2)
        assert merged.valor == Decimal("4.06")
        assert len(merged.desglose) == 2

    def test_merged_valor_none_if_any_none(self):
        calc = _calc_no_rates()
        c_none = calc._calc_dividendos([make_dividend(_DATE, "100.00")])  # sin tasa → None
        calc2 = _calc()
        c_val = calc2._calc_dividendos_degiro([make_degiro_dividend(gross_eur="2.56")])
        merged = calc2._merge_casillas(c_none, c_val)
        # c_none.valor is None → merged debe ser None
        assert merged.valor is None

    def test_calculate_with_degiro_merges_dividendos(self):
        calc = _calc()
        parsed_data = {
            "fidelity": FidelityData(dividends=[make_dividend(_DATE, "125.00")]),  # $125 / 1.25 = €100
            "degiro": DegiroData(dividends=[make_degiro_dividend(gross_eur="50.00")]),
        }
        resultado = calc.calculate(parsed_data, year=2024)
        assert resultado.dividendos.valor == Decimal("150.00")  # 100 + 50
        assert len(resultado.dividendos.desglose) == 2


# ---------------------------------------------------------------------------
# Agrupación por activo en ventas de acciones (grupos_activo)
# ---------------------------------------------------------------------------

class TestGruposActivoFidelity:
    def test_single_ticker_single_op(self):
        calc = _calc()
        sale = make_stock_sale(ticker="ORCL")
        casilla = calc._calc_ganancias_acciones([sale])
        grupos = casilla.extras["grupos_activo"]
        assert len(grupos) == 1
        assert grupos[0]["ticker"] == "ORCL (US)"
        assert grupos[0]["num_ops"] == 1
        assert grupos[0]["tiene_errores"] is False
        assert grupos[0]["total_coste_eur"] is not None
        assert grupos[0]["total_ingresos_eur"] is not None

    def test_multi_ticker_sorted_alphabetically(self):
        # ORCL x2 + MSFT x1 → grupos ordenados: MSFT, ORCL
        calc = _calc()
        sales = [
            make_stock_sale(ticker="ORCL"),
            make_stock_sale(ticker="MSFT"),
            make_stock_sale(ticker="ORCL"),
        ]
        casilla = calc._calc_ganancias_acciones(sales)
        grupos = casilla.extras["grupos_activo"]
        assert len(grupos) == 2
        assert grupos[0]["ticker"] == "MSFT (US)"
        assert grupos[0]["num_ops"] == 1
        assert grupos[1]["ticker"] == "ORCL (US)"
        assert grupos[1]["num_ops"] == 2

    def test_group_totals_sum_correctly(self):
        # cost $500/1.25 = €400; proceeds $750/1.25 = €600; dos ventas ORCL
        calc = _calc()
        sales = [make_stock_sale(ticker="ORCL"), make_stock_sale(ticker="ORCL")]
        casilla = calc._calc_ganancias_acciones(sales)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["total_coste_eur"] == Decimal("800.00")
        assert grupo["total_ingresos_eur"] == Decimal("1200.00")
        assert grupo["total_ganancia_eur"] == Decimal("400.00")

    def test_ops_sorted_by_date_within_group(self):
        # Dos ventas ORCL en fechas distintas: la más reciente primero en input
        calc = _calc()
        sale_later = make_stock_sale(ticker="ORCL", date_sold=_DATE3)
        sale_earlier = make_stock_sale(ticker="ORCL", date_sold=_DATE)
        casilla = calc._calc_ganancias_acciones([sale_later, sale_earlier])
        grupo = casilla.extras["grupos_activo"][0]
        # Debe aparecer la operación más antigua primero
        assert grupo["operaciones"][0].extras["fecha_venta"] == _DATE.strftime("%d/%m/%Y")
        assert grupo["operaciones"][1].extras["fecha_venta"] == _DATE3.strftime("%d/%m/%Y")

    def test_group_with_error_has_none_totals(self):
        # Sin tasa disponible para la fecha de adquisición
        calc = _calc()
        sale_err = make_stock_sale(ticker="ORCL", date_acquired=date(1999, 1, 1))
        casilla = calc._calc_ganancias_acciones([sale_err])
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["tiene_errores"] is True
        assert grupo["total_coste_eur"] is None
        assert grupo["total_ingresos_eur"] is None
        assert grupo["total_ganancia_eur"] is None

    def test_empty_sales_returns_empty_grupos(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([])
        assert casilla.extras["grupos_activo"] == []


class TestGruposActivoDegiro:
    def test_single_isin_single_op(self):
        calc = _calc()
        sale = make_degiro_stock_sale(product="Ares Capital Corp", symbol_isin="US04010L1035")
        casilla = calc._calc_ganancias_degiro([sale])
        grupos = casilla.extras["grupos_activo"]
        assert len(grupos) == 1
        assert grupos[0]["ticker"] == "Ares Capital Corp (US)"
        assert grupos[0]["num_ops"] == 1
        assert grupos[0]["tiene_errores"] is False

    def test_ticker_uses_product_name_and_country_prefix(self):
        calc = _calc()
        sale = make_degiro_stock_sale(product="Ares Capital Corp", symbol_isin="US04010L1035")
        casilla = calc._calc_ganancias_degiro([sale])
        assert casilla.desglose[0].extras["ticker"] == "Ares Capital Corp (US)"

    def test_multi_isin_sorted_alphabetically(self):
        calc = _calc()
        sales = [
            make_degiro_stock_sale(product="Zeta Corp", symbol_isin="US9999999999"),
            make_degiro_stock_sale(product="Ares Capital Corp", symbol_isin="US04010L1035"),
        ]
        casilla = calc._calc_ganancias_degiro(sales)
        grupos = casilla.extras["grupos_activo"]
        assert len(grupos) == 2
        assert grupos[0]["ticker"] == "Ares Capital Corp (US)"
        assert grupos[1]["ticker"] == "Zeta Corp (US)"


class TestMergeGruposActivo:
    def test_merge_concatenates_and_sorts(self):
        # Fidelity: ORCL; DEGIRO: "Ares Capital Corp (US)" → merge ordena alfabéticamente
        calc = _calc()
        c_fidelity = calc._calc_ganancias_acciones([make_stock_sale(ticker="ORCL")])
        c_degiro = calc._calc_ganancias_degiro([make_degiro_stock_sale(product="Ares Capital Corp", symbol_isin="US04010L1035")])
        merged = calc._merge_casillas(c_fidelity, c_degiro)
        grupos = merged.extras["grupos_activo"]
        assert len(grupos) == 2
        # "Ares Capital Corp (US)" < "ORCL (US)" alfabéticamente (A < O)
        assert grupos[0]["ticker"] == "Ares Capital Corp (US)"
        assert grupos[1]["ticker"] == "ORCL (US)"

    def test_merge_preserves_per_group_totals(self):
        calc = _calc()
        c_fidelity = calc._calc_ganancias_acciones([make_stock_sale(ticker="ORCL")])
        c_degiro = calc._calc_ganancias_degiro([make_degiro_stock_sale()])
        merged = calc._merge_casillas(c_fidelity, c_degiro)
        # Los grupos individuales mantienen sus totales propios
        orcl = next(g for g in merged.extras["grupos_activo"] if g["ticker"] == "ORCL (US)")
        assert orcl["total_coste_eur"] is not None
        assert orcl["num_ops"] == 1
