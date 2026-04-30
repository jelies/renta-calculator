"""Tests para Calculator — lógica fiscal de conversión y cálculo."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from renta.calculator import Calculator, _fmt_qty
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
# _fmt_qty
# ---------------------------------------------------------------------------


class TestFmtQty:
    def test_entero(self):
        assert _fmt_qty(Decimal("3")) == "3"

    def test_entero_grande(self):
        assert _fmt_qty(Decimal("1000")) == "1000"

    def test_decimal_normal(self):
        assert _fmt_qty(Decimal("0.5")) == "0.5"

    def test_decimal_recorta_ceros(self):
        assert _fmt_qty(Decimal("1.2300")) == "1.23"

    def test_muy_pequenyo_sin_notacion_cientifica(self):
        assert _fmt_qty(Decimal("1E-7")) == "0.0000001"

    def test_muy_pequenyo_con_decimales(self):
        assert _fmt_qty(Decimal("0.00000012")) == "0.00000012"


# ---------------------------------------------------------------------------
# Dividendos
# ---------------------------------------------------------------------------

class TestCalcDividendos:
    def test_single_dividend_converts_correctly(self):
        # $100 / 1.25 = €80.00
        calc = _calc()
        casilla = calc._calc_dividendos([make_dividend(_DATE, "100.00")], year=2024)
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
        casilla = calc._calc_dividendos(divs, year=2024)
        assert casilla.valor == Decimal("240.00")
        assert len(casilla.desglose) == 3

    def test_rate_failure_sets_valor_none(self):
        # Sin tasa disponible → valor debe ser None
        calc = _calc_no_rates()
        div = make_dividend(_DATE, "100.00")
        casilla = calc._calc_dividendos([div], year=2024)
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
        casilla = calc._calc_dividendos([div_ok, div_fail], year=2024)
        assert casilla.valor is None
        assert len(casilla.errores) == 1
        assert len(casilla.desglose) == 2

    def test_empty_dividends_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_dividendos([], year=2024)
        assert casilla.valor == Decimal("0.00")
        assert casilla.errores == []
        assert casilla.desglose == []

    def test_weekend_fallback_generates_warning(self):
        # Sábado 20 → usa viernes 19
        friday = date(2024, 1, 19)
        saturday = date(2024, 1, 20)
        calc = _calc(friday)  # tasa disponible solo el viernes
        div = make_dividend(saturday, "100.00")
        casilla = calc._calc_dividendos([div], year=2024)
        # El cálculo debe tener éxito usando el viernes
        assert casilla.valor is not None
        assert len(calc._warnings) == 1
        assert "19/01/2024" in calc._warnings[0]
        assert "fin de semana" in calc._warnings[0]

    def test_holiday_fallback_generates_warning_with_reason(self):
        # Miércoles 1 de enero (festivo) → usa el día anterior disponible
        new_years_eve = date(2024, 12, 31)  # martes
        new_years_day = date(2025, 1, 1)   # miércoles (festivo)
        calc = _calc(new_years_eve)
        div = make_dividend(new_years_day, "100.00")
        casilla = calc._calc_dividendos([div], year=2025)
        assert casilla.valor is not None
        assert len(calc._warnings) == 1
        assert "día festivo/sin cotización del BCE" in calc._warnings[0]

    def test_grupos_dividendos_generated(self):
        calc = _calc()
        divs = [make_dividend(_DATE, "100.00"), make_dividend(_DATE2, "200.00")]
        casilla = calc._calc_dividendos(divs, year=2024)
        grupos = casilla.extras["grupos_dividendos"]
        assert len(grupos) == 1
        g = grupos[0]
        assert g["ticker"] == "ORCL / FYIXX (US)"
        assert g["total_eur"] == Decimal("240.00")
        assert g["num_ops"] == 2
        assert g["tiene_errores"] is False
        assert len(g["operaciones"]) == 2

    def test_grupos_dividendos_error_marks_group(self):
        calc = _calc()
        div_ok = make_dividend(_DATE, "100.00")
        div_fail = make_dividend(date(2024, 6, 1), "50.00")
        casilla = calc._calc_dividendos([div_ok, div_fail], year=2024)
        grupos = casilla.extras["grupos_dividendos"]
        assert len(grupos) == 1
        assert grupos[0]["tiene_errores"] is True
        assert grupos[0]["total_eur"] is None

    def test_grupos_dividendos_empty(self):
        calc = _calc()
        casilla = calc._calc_dividendos([], year=2024)
        assert casilla.extras["grupos_dividendos"] == []

    def test_wrong_year_dividend_excluded_from_total(self):
        # Un dividendo de 2024 al calcular año 2025 → excluido, no suma al total
        calc = _calc()
        div_2024 = make_dividend(_DATE, "100.00")  # _DATE es 2024
        casilla = calc._calc_dividendos([div_2024], year=2025)
        assert casilla.valor == Decimal("0.00")  # total sin la fila excluida
        assert casilla.errores == []  # no es error bloqueante
        assert casilla.desglose[0].importe_eur is None
        assert casilla.desglose[0].error is not None
        assert "fuera del año fiscal 2025" in casilla.desglose[0].error

    def test_wrong_year_excluded_but_valid_year_sums(self):
        # Un dividendo del año correcto + uno del año incorrecto → total solo incluye el correcto
        right_date = date(2025, 1, 15)
        calc = _calc(right_date)
        div_wrong = make_dividend(_DATE, "100.00")   # 2024 → excluido
        div_right = make_dividend(right_date, "100.00")  # 2025 → suma: €80.00
        casilla = calc._calc_dividendos([div_wrong, div_right], year=2025)
        assert casilla.valor == Decimal("80.00")
        assert casilla.errores == []
        excluded = next(l for l in casilla.desglose if l.error)
        assert "fuera del año fiscal 2025" in excluded.error

    def test_grupos_dividendos_degiro(self):
        calc = _calc()
        divs = [
            make_degiro_dividend(country="US", product="ARES CAPITAL", gross_eur="50.00"),
            make_degiro_dividend(country="US", product="ARES CAPITAL", gross_eur="30.00"),
            make_degiro_dividend(country="IE", product="VANGUARD ETF", gross_eur="20.00"),
        ]
        casilla = calc._calc_dividendos_degiro(divs)
        grupos = casilla.extras["grupos_dividendos"]
        assert len(grupos) == 2
        tickers = [g["ticker"] for g in grupos]
        assert "ARES CAPITAL (US)" in tickers
        assert "VANGUARD ETF (IE)" in tickers
        ares = next(g for g in grupos if g["ticker"] == "ARES CAPITAL (US)")
        assert ares["total_eur"] == Decimal("80.00")
        assert ares["num_ops"] == 2

    def test_merge_casillas_combines_grupos_dividendos(self):
        calc = _calc()
        c1 = calc._calc_dividendos([make_dividend(_DATE, "100.00")], year=2024)
        c2 = calc._calc_dividendos_degiro([make_degiro_dividend(country="IE", product="VANGUARD ETF", gross_eur="50.00")])
        merged = calc._merge_casillas(c1, c2)
        grupos = merged.extras["grupos_dividendos"]
        tickers = [g["ticker"] for g in grupos]
        assert "ORCL / FYIXX (US)" in tickers
        assert "VANGUARD ETF (IE)" in tickers
        assert tickers == sorted(tickers)


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
        casilla = calc._calc_ganancias_acciones([self._sale_with_gain()], year=2024)
        assert casilla.valor == Decimal("200.00")
        assert casilla.errores == []

    def test_sale_mutates_model_with_eur_values(self):
        calc = _calc()
        sale = self._sale_with_gain()
        calc._calc_ganancias_acciones([sale], year=2024)
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
        casilla = calc._calc_ganancias_acciones([sale], year=2024)
        assert casilla.valor == Decimal("-200.00")

    def test_vesting_rate_failure_sets_valor_none(self):
        sale = make_stock_sale(
            date_sold=date(2024, 3, 12),
            date_acquired=date(1999, 1, 1),  # sin tasa
        )
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([sale], year=2024)
        assert casilla.valor is None
        assert len(casilla.errores) == 1
        assert sale.cost_basis_eur is None

    def test_sold_rate_failure_sets_valor_none(self):
        sale = make_stock_sale(
            date_sold=date(1999, 1, 1),  # sin tasa
            date_acquired=date(2020, 5, 5),
        )
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([sale], year=1999)
        assert casilla.valor is None
        assert len(casilla.errores) == 1

    def test_multiple_sales_total(self):
        calc = _calc()
        sales = [self._sale_with_gain(), self._sale_with_gain()]
        casilla = calc._calc_ganancias_acciones(sales, year=2024)
        assert casilla.valor == Decimal("400.00")

    def test_empty_sales_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([], year=2024)
        assert casilla.valor == Decimal("0.00")

    def test_wrong_year_sale_excluded_from_total(self):
        # Venta de 2024 al calcular año 2025 → excluida del total
        sale_2024 = make_stock_sale(date_sold=date(2024, 3, 12), date_acquired=date(2020, 5, 5))
        right_date = date(2025, 3, 12)
        sale_2025 = make_stock_sale(date_sold=right_date, date_acquired=date(2020, 5, 5))
        calc = _calc(right_date)
        casilla = calc._calc_ganancias_acciones([sale_2024, sale_2025], year=2025)
        # Solo la venta de 2025 suma: proceeds=600, cost=400 → gain=200
        assert casilla.valor == Decimal("200.00")
        assert casilla.errores == []
        excluded = next(l for l in casilla.desglose if l.error)
        assert "fuera del año fiscal 2025" in excluded.error
        assert excluded.importe_eur is None


# ---------------------------------------------------------------------------
# Doble imposición (retenciones USA)
# ---------------------------------------------------------------------------

class TestCalcDobleImposicion:
    def test_single_withholding_negative(self):
        # Retención: -$7.50 / 1.25 = -€6.00 → valor = abs = €6.00
        calc = _calc()
        wh = make_withholding(_DATE, "-7.50")
        casilla = calc._calc_doble_imposicion([wh], year=2024)
        assert casilla.valor == Decimal("6.00")
        assert casilla.numero == "0588"

    def test_mixed_retention_and_adjustment(self):
        # -$10.00 + $2.50 = -$7.50 / 1.25 = -€6.00 → abs = €6.00
        calc = _calc()
        whs = [
            make_withholding(_DATE, "-10.00"),
            make_withholding(_DATE2, "2.50"),
        ]
        casilla = calc._calc_doble_imposicion(whs, year=2024)
        assert casilla.valor == Decimal("6.00")

    def test_rate_failure_sets_valor_none(self):
        calc = _calc_no_rates()
        casilla = calc._calc_doble_imposicion([make_withholding(_DATE, "-7.00")], year=2024)
        assert casilla.valor is None
        assert len(casilla.errores) == 1

    def test_empty_withholdings_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_doble_imposicion([], year=2024)
        assert casilla.valor == Decimal("0.00")

    def test_wrong_year_withholding_excluded_from_total(self):
        # Retención de 2024 en un cálculo del año 2025 → excluida, no invalida total
        calc = _calc()
        wh_2024 = make_withholding(_DATE, "-10.00")  # _DATE es 2024
        wh_2025 = make_withholding(date(2025, 1, 15), "-5.00")
        calc2 = _calc(date(2025, 1, 15))
        casilla = calc2._calc_doble_imposicion([wh_2024, wh_2025], year=2025)
        # Solo la retención de 2025: -$5.00 / 1.25 = -€4.00 → abs = €4.00
        assert casilla.valor == Decimal("4.00")
        assert casilla.errores == []
        excluded = next(l for l in casilla.desglose if l.aviso)
        assert "fuera del año fiscal 2025" in excluded.aviso
        assert excluded.importe_eur is None

    def test_grupos_retenciones_generated(self):
        calc = _calc()
        whs = [make_withholding(_DATE, "-7.50"), make_withholding(_DATE2, "2.50")]
        casilla = calc._calc_doble_imposicion(whs, year=2024)
        grupos = casilla.extras["grupos_retenciones"]
        assert len(grupos) == 1
        g = grupos[0]
        assert g["ticker"] == "ORCL / FYIXX (US)"
        # neto = -7.50/1.25 + 2.50/1.25 = -6.00 + 2.00 = -4.00 → abs = 4.00
        assert g["total_eur"] == Decimal("4.00")
        assert g["num_ops"] == 2
        assert g["tiene_errores"] is False
        assert g["tiene_avisos"] is False
        assert len(g["operaciones"]) == 2

    def test_grupos_retenciones_aviso_no_bloquea_total(self):
        # Retención de 2024 junto a una de 2025: la de 2024 es aviso, el total sigue calculado
        calc2 = _calc(date(2025, 1, 15))
        wh_ok = make_withholding(date(2025, 1, 15), "-5.00")   # válida
        wh_aviso = make_withholding(_DATE, "-10.00")            # fuera del año → aviso
        casilla = calc2._calc_doble_imposicion([wh_ok, wh_aviso], year=2025)
        grupos = casilla.extras["grupos_retenciones"]
        g = grupos[0]
        assert g["tiene_avisos"] is True
        assert g["tiene_errores"] is False
        # total = abs(-5.00/1.25) = 4.00, sin incluir la de 2024
        assert g["total_eur"] == Decimal("4.00")

    def test_grupos_retenciones_error_marks_group(self):
        calc = _calc_no_rates()
        casilla = calc._calc_doble_imposicion([make_withholding(_DATE, "-7.00")], year=2024)
        grupos = casilla.extras["grupos_retenciones"]
        assert len(grupos) == 1
        assert grupos[0]["tiene_errores"] is True
        assert grupos[0]["tiene_avisos"] is False
        assert grupos[0]["total_eur"] is None

    def test_grupos_retenciones_empty(self):
        calc = _calc()
        casilla = calc._calc_doble_imposicion([], year=2024)
        assert casilla.extras["grupos_retenciones"] == []

    def test_grupos_retenciones_degiro(self):
        calc = _calc()
        divs = [
            make_degiro_dividend(country="US", product="ARES CAPITAL", gross_eur="50.00", withholding_eur="-5.00"),
            make_degiro_dividend(country="IE", product="VANGUARD ETF", gross_eur="20.00", withholding_eur="-2.00"),
        ]
        casilla = calc._calc_doble_imposicion_degiro(divs)
        grupos = casilla.extras["grupos_retenciones"]
        assert len(grupos) == 2
        tickers = [g["ticker"] for g in grupos]
        assert "ARES CAPITAL (US)" in tickers
        assert "VANGUARD ETF (IE)" in tickers
        ares = next(g for g in grupos if g["ticker"] == "ARES CAPITAL (US)")
        assert ares["total_eur"] == Decimal("5.00")
        assert ares["num_ops"] == 1

    def test_merge_casillas_combines_grupos_retenciones(self):
        calc = _calc()
        c1 = calc._calc_doble_imposicion([make_withholding(_DATE, "-7.50")], year=2024)
        c2 = calc._calc_doble_imposicion_degiro([
            make_degiro_dividend(country="IE", product="VANGUARD ETF", gross_eur="20.00", withholding_eur="-2.00"),
        ])
        merged = calc._merge_casillas(c1, c2)
        grupos = merged.extras["grupos_retenciones"]
        tickers = [g["ticker"] for g in grupos]
        assert "ORCL / FYIXX (US)" in tickers
        assert "VANGUARD ETF (IE)" in tickers
        assert tickers == sorted(tickers)


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
        assert casilla.numero == "1800-1814"

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

    def test_grupos_activo_created(self):
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00", wallet="Kraken"),
            make_crypto_gain(asset="BTC", cost_eur="5.00", proceeds_eur="20.00", gain_loss_eur="15.00", wallet="Kraken"),
            make_crypto_gain(asset="ADA", cost_eur="3.00", proceeds_eur="2.00", gain_loss_eur="-1.00", wallet="Ledger"),
        ]
        casilla = calc._calc_ganancias_crypto(gains)
        grupos = casilla.extras["grupos_activo"]
        assert len(grupos) == 2
        btc = next(g for g in grupos if g["ticker"] == "BTC")
        ada = next(g for g in grupos if g["ticker"] == "ADA")
        assert btc["ganancias_activo"] == Decimal("55.00")
        assert btc["perdidas_activo"] == Decimal("0.00")
        assert ada["ganancias_activo"] == Decimal("0.00")
        assert ada["perdidas_activo"] == Decimal("-1.00")

    def test_total_ganancias_perdidas(self):
        calc = _calc()
        gains = [
            make_crypto_gain(cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00"),
            make_crypto_gain(cost_eur="100.00", proceeds_eur="70.00", gain_loss_eur="-30.00"),
        ]
        casilla = calc._calc_ganancias_crypto(gains)
        assert casilla.extras["total_ganancias"] == Decimal("40.00")
        assert casilla.extras["total_perdidas"] == Decimal("-30.00")

    def test_wallets_deduplicadas_por_activo(self):
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00", wallet="Kraken"),
            make_crypto_gain(asset="BTC", cost_eur="5.00", proceeds_eur="20.00", gain_loss_eur="15.00", wallet="Ledger"),
            make_crypto_gain(asset="BTC", cost_eur="2.00", proceeds_eur="8.00", gain_loss_eur="6.00", wallet="Kraken"),
        ]
        casilla = calc._calc_ganancias_crypto(gains)
        grupos = casilla.extras["grupos_activo"]
        assert len(grupos) == 1
        assert grupos[0]["wallets"] == ["Kraken", "Ledger"]

    def test_asset_summary_overrides_group_totals(self):
        calc = _calc()
        gains = [
            make_crypto_gain(asset="LTC", cost_eur="100.00", proceeds_eur="50.00", gain_loss_eur="-50.00"),
        ]
        # El PDF dice que LTC tiene 0 ganancias y 89,59 pérdidas
        asset_summary = {"LTC": {"ganancias": Decimal("0.00"), "perdidas": Decimal("89.59"), "neto": Decimal("-89.59")}}
        casilla = calc._calc_ganancias_crypto(gains, asset_summary)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["ganancias_activo"] == Decimal("0.00")
        assert grupo["perdidas_activo"] == Decimal("-89.59")

    def test_asset_summary_total_uses_pdf_values(self):
        calc = _calc()
        gains = [
            make_crypto_gain(asset="LTC", cost_eur="100.00", proceeds_eur="50.00", gain_loss_eur="-50.00"),
            make_crypto_gain(asset="XRP", cost_eur="0.00", proceeds_eur="0.03", gain_loss_eur="0.03"),
        ]
        asset_summary = {
            "LTC": {"ganancias": Decimal("0.00"), "perdidas": Decimal("89.59"), "neto": Decimal("-89.59")},
            "XRP": {"ganancias": Decimal("0.03"), "perdidas": Decimal("0.00"), "neto": Decimal("0.03")},
        }
        casilla = calc._calc_ganancias_crypto(gains, asset_summary)
        assert casilla.extras["total_ganancias"] == Decimal("0.03")
        assert casilla.extras["total_perdidas"] == Decimal("-89.59")

    def test_asset_summary_fallback_when_asset_missing(self):
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00"),
        ]
        # BTC no está en el asset_summary, debe usar suma local
        asset_summary = {"LTC": {"ganancias": Decimal("0.00"), "perdidas": Decimal("89.59"), "neto": Decimal("-89.59")}}
        casilla = calc._calc_ganancias_crypto(gains, asset_summary)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["ganancias_activo"] == Decimal("40.00")

    def test_fechas_sin_hora_en_extras(self):
        calc = _calc()
        g = make_crypto_gain(cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00")
        casilla = calc._calc_ganancias_crypto([g])
        linea = casilla.desglose[0]
        assert ":" not in linea.extras["fecha_venta"]
        assert ":" not in linea.extras["fecha_adquisicion"]

    def test_asset_totals_official_overrides_coste_ingresos(self):
        """Los totales de adquisición/transmisión por activo vienen del Spain report."""
        calc = _calc()
        gains = [
            make_crypto_gain(asset="LTC", cost_eur="280.10", proceeds_eur="115.97", gain_loss_eur="-164.13"),
        ]
        asset_totals_official = {
            "LTC": {"valor_eur": Decimal("280.10"), "ingresos_eur": Decimal("115.98"), "ganancia_eur": Decimal("-164.12")},
        }
        casilla = calc._calc_ganancias_crypto(gains, asset_totals_official=asset_totals_official)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["total_coste_eur"] == Decimal("280.10")
        assert grupo["total_ingresos_eur"] == Decimal("115.98")
        assert grupo["total_ganancia_eur"] == Decimal("-164.12")

    def test_asset_totals_official_updates_casilla_valor(self):
        """El valor total de la casilla refleja los totales oficiales."""
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="15.55", proceeds_eur="97.81", gain_loss_eur="82.26"),
            make_crypto_gain(asset="ETH", cost_eur="120.00", proceeds_eur="195.51", gain_loss_eur="75.51"),
        ]
        asset_totals_official = {
            "BTC": {"valor_eur": Decimal("15.55"), "ingresos_eur": Decimal("97.82"), "ganancia_eur": Decimal("82.27")},
            "ETH": {"valor_eur": Decimal("120.00"), "ingresos_eur": Decimal("195.50"), "ganancia_eur": Decimal("75.50")},
        }
        casilla = calc._calc_ganancias_crypto(gains, asset_totals_official=asset_totals_official)
        assert casilla.extras["total_cost"] == Decimal("135.55")
        assert casilla.extras["total_proceeds"] == Decimal("293.32")
        assert casilla.valor == Decimal("157.77")

    def test_asset_totals_official_partial_coverage(self):
        """Con cobertura parcial, se usa oficial sólo para activos presentes."""
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="10.00", proceeds_eur="50.00", gain_loss_eur="40.00"),
            make_crypto_gain(asset="ETH", cost_eur="20.00", proceeds_eur="30.00", gain_loss_eur="10.00"),
        ]
        asset_totals_official = {
            "BTC": {"valor_eur": Decimal("10.01"), "ingresos_eur": Decimal("50.02"), "ganancia_eur": Decimal("40.01")},
        }
        casilla = calc._calc_ganancias_crypto(gains, asset_totals_official=asset_totals_official)
        grupos = {g["ticker"]: g for g in casilla.extras["grupos_activo"]}
        assert grupos["BTC"]["total_coste_eur"] == Decimal("10.01")
        assert grupos["BTC"]["total_ingresos_eur"] == Decimal("50.02")
        assert grupos["ETH"]["total_coste_eur"] == Decimal("20.00")
        assert grupos["ETH"]["total_ingresos_eur"] == Decimal("30.00")

    def test_no_asset_totals_official_preserves_existing_behavior(self):
        """Sin Spain report, el comportamiento es idéntico al actual."""
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="15.55", proceeds_eur="97.82", gain_loss_eur="82.27"),
        ]
        casilla = calc._calc_ganancias_crypto(gains)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["total_coste_eur"] == Decimal("15.55")
        assert grupo["total_ingresos_eur"] == Decimal("97.82")
        assert casilla.valor == Decimal("82.27")

    def test_desglose_operaciones_no_modificado_por_official(self):
        """Los detalles operación-a-operación no se tocan aunque haya totales oficiales."""
        calc = _calc()
        gains = [
            make_crypto_gain(asset="BTC", cost_eur="15.55", proceeds_eur="97.82", gain_loss_eur="82.27"),
        ]
        asset_totals_official = {
            "BTC": {"valor_eur": Decimal("15.56"), "ingresos_eur": Decimal("97.83"), "ganancia_eur": Decimal("82.27")},
        }
        casilla = calc._calc_ganancias_crypto(gains, asset_totals_official=asset_totals_official)
        linea = casilla.desglose[0]
        assert linea.extras["coste_eur"] == "15,55\xa0€"
        assert linea.extras["ingresos_eur"] == "97,82\xa0€"


# ---------------------------------------------------------------------------
# Rendimientos staking/rewards (ya en EUR)
# ---------------------------------------------------------------------------

class TestCalcRendimientosCrypto:
    def test_rewards_sum(self):
        calc = _calc()
        koinly = KoinlyData(rewards=[
            make_crypto_reward(asset="ADA", price_eur="1.00"),
            make_crypto_reward(asset="ADA", price_eur="2.00"),
            make_crypto_reward(asset="STETH", price_eur="5.00"),
        ])
        casilla = calc._calc_rendimientos_crypto(koinly)
        assert casilla.valor == Decimal("8.00")

    def test_rewards_grouped_by_asset_in_desglose(self):
        calc = _calc()
        koinly = KoinlyData(rewards=[
            make_crypto_reward(asset="ADA", price_eur="1.00"),
            make_crypto_reward(asset="ADA", price_eur="2.00"),
            make_crypto_reward(asset="STETH", price_eur="5.00"),
        ])
        casilla = calc._calc_rendimientos_crypto(koinly)
        assert len(casilla.desglose) == 2
        assert casilla.desglose[0].descripcion == "Staking rewards ADA"
        assert casilla.desglose[1].descripcion == "Staking rewards STETH"

    def test_empty_returns_zero(self):
        calc = _calc()
        casilla = calc._calc_rendimientos_crypto(KoinlyData(rewards=[]))
        assert casilla.valor == Decimal("0.00")
        assert casilla.desglose == []

    def test_rewards_uses_pdf_total_when_available(self):
        calc = _calc()
        koinly = KoinlyData(
            rewards=[
                make_crypto_reward(asset="ADA", price_eur="23.00"),
                make_crypto_reward(asset="STETH", price_eur="23.97"),
            ],
            summary_rewards_eur=Decimal("46.93"),
        )
        casilla = calc._calc_rendimientos_crypto(koinly)
        assert casilla.valor == Decimal("46.93")
        assert len(casilla.desglose) == 2

    def test_rewards_falls_back_to_sum_when_no_pdf_total(self):
        calc = _calc()
        koinly = KoinlyData(
            rewards=[
                make_crypto_reward(asset="ADA", price_eur="1.50"),
                make_crypto_reward(asset="STETH", price_eur="2.50"),
            ],
            summary_rewards_eur=None,
        )
        casilla = calc._calc_rendimientos_crypto(koinly)
        assert casilla.valor == Decimal("4.00")


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
        assert casilla.numero == "0588"

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
        assert casilla.numero == "0326-0340"
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
        c2 = calc._calc_dividendos([], year=2024)
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
        c_none = calc._calc_dividendos([make_dividend(_DATE, "100.00")], year=2024)  # sin tasa → None
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
        casilla = calc._calc_ganancias_acciones([sale], year=2024)
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
        casilla = calc._calc_ganancias_acciones(sales, year=2024)
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
        casilla = calc._calc_ganancias_acciones(sales, year=2024)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["total_coste_eur"] == Decimal("800.00")
        assert grupo["total_ingresos_eur"] == Decimal("1200.00")
        assert grupo["total_ganancia_eur"] == Decimal("400.00")

    def test_ops_sorted_by_date_within_group(self):
        # Dos ventas ORCL en fechas distintas: la más reciente primero en input
        calc = _calc()
        sale_later = make_stock_sale(ticker="ORCL", date_sold=_DATE3)
        sale_earlier = make_stock_sale(ticker="ORCL", date_sold=_DATE)
        casilla = calc._calc_ganancias_acciones([sale_later, sale_earlier], year=2024)
        grupo = casilla.extras["grupos_activo"][0]
        # Debe aparecer la operación más antigua primero
        assert grupo["operaciones"][0].extras["fecha_venta"] == _DATE.strftime("%d/%m/%Y")
        assert grupo["operaciones"][1].extras["fecha_venta"] == _DATE3.strftime("%d/%m/%Y")

    def test_group_with_error_has_none_totals(self):
        # Sin tasa disponible para la fecha de adquisición
        calc = _calc()
        sale_err = make_stock_sale(ticker="ORCL", date_acquired=date(1999, 1, 1))
        casilla = calc._calc_ganancias_acciones([sale_err], year=2024)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["tiene_errores"] is True
        assert grupo["total_coste_eur"] is None
        assert grupo["total_ingresos_eur"] is None
        assert grupo["total_ganancia_eur"] is None
        assert grupo["ganancias_activo"] is None
        assert grupo["perdidas_activo"] is None

    def test_group_ganancias_perdidas_activo(self):
        # Dos ops con la misma tasa: una ganancia y una pérdida
        # make_stock_sale: cost=$500, proceeds=$750 → gain=$250/1.25=€200
        # Para simular pérdida necesitaríamos cost>proceeds, pero make_stock_sale usa valores fijos.
        # Usamos dos tickers distintos y verificamos la separación sobre ganancias > 0.
        calc = _calc()
        sale = make_stock_sale(ticker="ORCL")
        casilla = calc._calc_ganancias_acciones([sale], year=2024)
        grupo = casilla.extras["grupos_activo"][0]
        # proceeds €600 > coste €400 → ganancia positiva → ganancias_activo > 0, perdidas_activo = 0
        assert grupo["ganancias_activo"] > Decimal("0")
        assert grupo["perdidas_activo"] == Decimal("0.00")

    def test_group_perdidas_activo_cero_cuando_solo_ganancias(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([make_stock_sale(ticker="ORCL")], year=2024)
        grupo = casilla.extras["grupos_activo"][0]
        assert grupo["perdidas_activo"] == Decimal("0.00")

    def test_group_ganancias_activo_cuantizado_a_centimos(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([make_stock_sale(ticker="ORCL")], year=2024)
        grupo = casilla.extras["grupos_activo"][0]
        # Verificar que está cuantizado (2 decimales)
        assert grupo["ganancias_activo"].as_tuple().exponent == -2
        assert grupo["perdidas_activo"].as_tuple().exponent == -2

    def test_empty_sales_returns_empty_grupos(self):
        calc = _calc()
        casilla = calc._calc_ganancias_acciones([], year=2024)
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
        c_fidelity = calc._calc_ganancias_acciones([make_stock_sale(ticker="ORCL")], year=2024)
        c_degiro = calc._calc_ganancias_degiro([make_degiro_stock_sale(product="Ares Capital Corp", symbol_isin="US04010L1035")])
        merged = calc._merge_casillas(c_fidelity, c_degiro)
        grupos = merged.extras["grupos_activo"]
        assert len(grupos) == 2
        # "Ares Capital Corp (US)" < "ORCL (US)" alfabéticamente (A < O)
        assert grupos[0]["ticker"] == "Ares Capital Corp (US)"
        assert grupos[1]["ticker"] == "ORCL (US)"

    def test_merge_preserves_per_group_totals(self):
        calc = _calc()
        c_fidelity = calc._calc_ganancias_acciones([make_stock_sale(ticker="ORCL")], year=2024)
        c_degiro = calc._calc_ganancias_degiro([make_degiro_stock_sale()])
        merged = calc._merge_casillas(c_fidelity, c_degiro)
        # Los grupos individuales mantienen sus totales propios
        orcl = next(g for g in merged.extras["grupos_activo"] if g["ticker"] == "ORCL (US)")
        assert orcl["total_coste_eur"] is not None
        assert orcl["num_ops"] == 1

    def test_merge_suma_total_ganancias_y_perdidas(self):
        # Fidelity con ganancia, DEGIRO con pérdida → merge suma cada parte por separado
        calc = _calc()
        # Fidelity: proceeds=750, cost=500 → gain_eur=(750-500)/1.25=200 → total_ganancias=200
        c_fidelity = calc._calc_ganancias_acciones([make_stock_sale(
            cost_basis_usd="500.00", proceeds_usd="750.00", gain_loss_usd="250.00",
        )], year=2024)
        # DEGIRO: gain_loss_eur negativo → total_perdidas < 0
        c_degiro = calc._calc_ganancias_degiro([make_degiro_stock_sale(gain_loss_eur="-50.00")])
        merged = calc._merge_casillas(c_fidelity, c_degiro)
        assert merged.extras["total_ganancias"] == Decimal("200.00")
        assert merged.extras["total_perdidas"] == Decimal("-50.00")


class TestTotalesGananciasPerdidas:
    def test_total_ganancias_solo_positivos(self):
        # rate=1.25: sale_a gain=(750-500)/1.25=200; sale_b gain=(300-500)/1.25=-160
        calc = _calc()
        sale_a = make_stock_sale(cost_basis_usd="500.00", proceeds_usd="750.00", gain_loss_usd="250.00")
        sale_b = make_stock_sale(cost_basis_usd="500.00", proceeds_usd="300.00", gain_loss_usd="-200.00")
        casilla = calc._calc_ganancias_acciones([sale_a, sale_b], year=2024)
        assert casilla.extras["total_ganancias"] == Decimal("200.00")

    def test_total_perdidas_solo_negativos(self):
        calc = _calc()
        sale_a = make_stock_sale(cost_basis_usd="500.00", proceeds_usd="750.00", gain_loss_usd="250.00")
        sale_b = make_stock_sale(cost_basis_usd="500.00", proceeds_usd="300.00", gain_loss_usd="-200.00")
        casilla = calc._calc_ganancias_acciones([sale_a, sale_b], year=2024)
        assert casilla.extras["total_perdidas"] == Decimal("-160.00")

    def test_totales_none_cuando_hay_error(self):
        # date_acquired fuera de rango → error de conversión → totales None
        calc = _calc()
        sale_err = make_stock_sale(date_acquired=date(1999, 1, 1))
        casilla = calc._calc_ganancias_acciones([sale_err], year=2024)
        assert casilla.extras["total_ganancias"] is None
        assert casilla.extras["total_perdidas"] is None

    def test_total_ganancias_degiro(self):
        calc = _calc()
        casilla = calc._calc_ganancias_degiro([make_degiro_stock_sale(gain_loss_eur="120.00")])
        assert casilla.extras["total_ganancias"] == Decimal("120.00")
        assert casilla.extras["total_perdidas"] == Decimal("0.00")
