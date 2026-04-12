"""Tests para el generador de informe HTML."""

from decimal import Decimal

import pytest

from renta.models import Casilla, LineaDetalle, ResultadoRenta
from renta.report import (
    _filter_clipboard_value,
    _filter_clipboard_value_str,
    _filter_color_class,
    _filter_format_num,
    _filter_nl2br,
    generate,
)
from tests.factories import make_crypto_reward


# ---------------------------------------------------------------------------
# Helpers de construcción de fixtures
# ---------------------------------------------------------------------------

def _casilla_dividendos(valor=Decimal("150.00"), con_error=False):
    if con_error:
        linea = LineaDetalle(
            descripcion="div",
            importe_eur=None,
            extras={"fecha": "15/01/2024", "importe_usd": "$110.00"},
            error="Fecha no disponible en BCE",
        )
        return Casilla(
            numero="0029",
            nombre="Dividendos",
            valor=None,
            desglose=[linea],
            notas="Notas dividendos",
            errores=["Fecha no disponible en BCE"],
            template="_dividendos.html",
        )
    linea = LineaDetalle(
        descripcion="div",
        importe_eur=valor,
        extras={"fecha": "15/01/2024", "importe_usd": "$110.00", "tipo_cambio": "1.0950"},
    )
    return Casilla(
        numero="0029", nombre="Dividendos", valor=valor, desglose=[linea], notas="Notas div",
        template="_dividendos.html",
    )


def _casilla_ventas(valor=Decimal("500.00")):
    linea = LineaDetalle(
        descripcion="venta",
        importe_eur=valor,
        extras={
            "ticker": "ORCL",
            "fecha_venta": "12/03/2024",
            "fecha_vesting": "05/05/2020",
            "cantidad": "10.0000",
            "coste_usd": "$500.00",
            "ingresos_usd": "$750.00",
            "tipo_vesting": "1.0800",
            "tipo_venta": "1.0900",
            "coste_eur": "462.96€",
            "ingresos_eur": "688.07€",
            "tipo_accion": "RSU",
        },
    )
    grupo_orcl = {
        "ticker": "ORCL",
        "operaciones": [linea],
        "total_coste_eur": Decimal("462.96"),
        "total_ingresos_eur": Decimal("688.07"),
        "total_ganancia_eur": Decimal("225.11"),
        "num_ops": 1,
        "tiene_errores": False,
    }
    return Casilla(
        numero="0328-0337",
        nombre="Ganancias acciones",
        valor=valor,
        desglose=[linea],
        notas="Notas ventas\nSegunda línea",
        template="_ventas_acciones.html",
        extras={
            "total_cost": Decimal("462.96"),
            "total_proceeds": Decimal("688.07"),
            "grupos_activo": [grupo_orcl],
        },
    )


def _casilla_crypto_ganancias(valor=Decimal("82.27")):
    linea = LineaDetalle(
        descripcion="BTC",
        importe_eur=valor,
        extras={
            "activo": "BTC",
            "fecha_venta": "29/07/2024",
            "fecha_adquisicion": "17/01/2018",
            "cantidad": "0.00152000",
            "coste_eur": "15.55€",
            "ingresos_eur": "97.82€",
            "wallet": "Kraken",
            "notas": "",
        },
    )
    return Casilla(
        numero="1626-1627", nombre="Ganancias crypto", valor=valor, desglose=[linea], notas="Notas crypto",
        template="_ganancias_crypto.html",
    )


def _casilla_retenciones(valor=Decimal("-7.08")):
    linea = LineaDetalle(
        descripcion="ret",
        importe_eur=valor,
        extras={"fecha": "15/01/2024", "tipo": "NRA", "importe_usd": "-$7.75", "tipo_cambio": "1.0950"},
    )
    return Casilla(
        numero="0588-0589", nombre="Retenciones", valor=valor, desglose=[linea], notas="Notas ret",
        template="_retenciones.html",
    )


def _casilla_rendimientos(valor=Decimal("12.50"), rewards=None):
    linea = LineaDetalle(
        descripcion="ADA",
        importe_eur=valor,
        extras={"activo": "ADA", "num_operaciones": "5"},
    )
    return Casilla(
        numero="0027", nombre="Rendimientos crypto", valor=valor, desglose=[linea], notas="Notas rend",
        template="_rendimientos_crypto.html",
        extras={"rewards": rewards or [], "total_ops": len(rewards) if rewards else 0},
    )


# ---------------------------------------------------------------------------
# Tests de filtros
# ---------------------------------------------------------------------------

class TestFilters:
    def test_color_class_positivo(self):
        assert _filter_color_class(Decimal("100")) == "gain"

    def test_color_class_negativo(self):
        assert _filter_color_class(Decimal("-50")) == "loss"

    def test_color_class_cero(self):
        assert _filter_color_class(Decimal("0")) == "zero"

    def test_color_class_none(self):
        assert _filter_color_class(None) == "zero"

    def test_format_num(self):
        assert _filter_format_num(Decimal("1234.5")) == "1,234.50"
        assert _filter_format_num(Decimal("0")) == "0.00"
        assert _filter_format_num(Decimal("-99.99")) == "-99.99"

    def test_clipboard_value_positivo(self):
        assert _filter_clipboard_value(Decimal("1234.56")) == "1234,56"

    def test_clipboard_value_negativo(self):
        assert _filter_clipboard_value(Decimal("-99.50")) == "99,50"

    def test_clipboard_value_cero(self):
        assert _filter_clipboard_value(Decimal("0")) == "0,00"

    def test_clipboard_value_sin_miles(self):
        assert _filter_clipboard_value(Decimal("12345.67")) == "12345,67"

    def test_clipboard_value_str_basico(self):
        assert _filter_clipboard_value_str("462.96€") == "462,96"

    def test_clipboard_value_str_con_miles(self):
        assert _filter_clipboard_value_str("1,234.56€") == "1234,56"

    def test_clipboard_value_str_negativo(self):
        assert _filter_clipboard_value_str("-7.08€") == "7,08"

    def test_clipboard_value_str_vacio(self):
        assert _filter_clipboard_value_str("") == ""

    def test_nl2br_sin_saltos(self):
        result = str(_filter_nl2br("texto simple"))
        assert result == "texto simple"

    def test_nl2br_con_saltos(self):
        result = str(_filter_nl2br("línea1\nlínea2"))
        assert result == "línea1<br>línea2"

    def test_nl2br_escapa_html(self):
        result = str(_filter_nl2br("<script>alert(1)</script>"))
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ---------------------------------------------------------------------------
# Tests de generate()
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_html_basico(self):
        result = ResultadoRenta(year=2024)
        html = generate(result)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Declaración de la Renta 2024" in html

    def test_incluye_anno(self):
        result = ResultadoRenta(year=2023)
        html = generate(result)
        assert "2023" in html

    def test_seccion_dividendos(self):
        casilla = _casilla_dividendos()
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "Dividendos" in html
        assert "0029" in html
        assert "150.00" in html
        assert "15/01/2024" in html

    def test_seccion_dividendos_ausente_cuando_none(self):
        result = ResultadoRenta(year=2024, dividendos=None)
        html = generate(result)
        assert "Dividendos — Casilla" not in html

    def test_seccion_ventas_acciones(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        assert "Ventas de acciones" in html
        assert "0328-0337" in html
        assert "ORCL" in html
        assert "Segunda línea" in html  # nl2br procesa notas
        assert "grupo-activo" in html  # grupos desplegables presentes
        assert "1 activo(s)" in html  # summary exterior con conteo de activos

    def test_seccion_retenciones(self):
        casilla = _casilla_retenciones()
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        assert "Retenciones EEUU" in html
        assert "0588-0589" in html

    def test_seccion_ganancias_crypto(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        assert "Ganancias patrimoniales crypto" in html
        assert "BTC" in html

    def test_seccion_rendimientos_crypto_sin_rewards(self):
        casilla = _casilla_rendimientos()
        result = ResultadoRenta(year=2024, rendimientos_crypto=casilla)
        html = generate(result)
        assert "Rendimientos de staking" in html
        assert "ADA" in html
        assert "Ver detalle" not in html  # sin rewards no hay detalle expandible

    def test_seccion_rendimientos_crypto_con_rewards(self):
        reward = make_crypto_reward()
        casilla = _casilla_rendimientos(rewards=[reward])
        result = ResultadoRenta(year=2024, rendimientos_crypto=casilla)
        html = generate(result)
        assert "Ver detalle de 1 operaciones" in html
        assert "ADA" in html

    def test_warnings(self):
        result = ResultadoRenta(year=2024, warnings=["Advertencia de prueba"])
        html = generate(result)
        assert "Advertencia de prueba" in html

    def test_sin_warnings_no_aparece_bloque(self):
        result = ResultadoRenta(year=2024, warnings=[])
        html = generate(result)
        assert "Advertencias:" not in html

    def test_resumen_incluye_todas_las_casillas(self):
        result = ResultadoRenta(
            year=2024,
            dividendos=_casilla_dividendos(),
            ganancias_acciones=_casilla_ventas(),
            ganancias_crypto=_casilla_crypto_ganancias(),
            doble_imposicion=_casilla_retenciones(),
            rendimientos_crypto=_casilla_rendimientos(),
        )
        html = generate(result)
        assert "0029" in html
        assert "0328-0337" in html
        assert "1626-1627" in html
        assert "0588-0589" in html
        assert "0027" in html

    def test_error_en_casilla_muestra_badge(self):
        casilla = _casilla_dividendos(con_error=True)
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "ERROR" in html
        assert "NO CALCULADO" in html or "NO CALCULABLE" in html

    def test_ventas_totales_calculados(self):
        casilla = _casilla_ventas(valor=Decimal("225.11"))
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # Los totales coste/ingresos se pre-computan a partir de extras
        assert "462.96" in html  # coste_eur
        assert "688.07" in html  # ingresos_eur

    def test_css_esta_inlineado(self):
        result = ResultadoRenta(year=2024)
        html = generate(result)
        assert "<style>" in html
        assert "font-family" in html

    def test_botones_copy_en_dividendos(self):
        casilla = _casilla_dividendos()
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "copy-btn" in html
        assert "navigator.clipboard.writeText" in html
        # 150.00 -> sin miles, coma decimal, sin signo
        assert "writeText('150,00')" in html

    def test_botones_copy_en_resumen(self):
        casilla = _casilla_dividendos(valor=Decimal("1234.56"))
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "writeText('1234,56')" in html

    def test_botones_copy_valor_negativo_sin_signo(self):
        casilla = _casilla_retenciones(valor=Decimal("-7.08"))
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        # El valor negativo debe copiarse sin el signo menos
        assert "writeText('7,08')" in html

    def test_botones_copy_en_coste_ingresos_ventas(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # coste_eur="462.96€" -> 462,96; ingresos_eur="688.07€" -> 688,07
        assert "writeText('462,96')" in html
        assert "writeText('688,07')" in html

    def test_botones_copy_en_coste_ingresos_crypto(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        # coste_eur="15.55€" -> 15,55; ingresos_eur="97.82€" -> 97,82
        assert "writeText('15,55')" in html
        assert "writeText('97,82')" in html

    def test_botones_copy_ocultos_en_print(self):
        result = ResultadoRenta(year=2024)
        html = generate(result)
        assert ".copy-btn { display: none; }" in html or "copy-btn { display: none" in html
