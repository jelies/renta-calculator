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
        grupo = {
            "ticker": "ORCL / FYIXX (US)",
            "operaciones": [linea],
            "total_eur": None,
            "num_ops": 1,
            "tiene_errores": True,
        }
        return Casilla(
            numero="0029",
            nombre="Dividendos",
            valor=None,
            desglose=[linea],
            notas="Notas dividendos",
            errores=["Fecha no disponible en BCE"],
            template="_dividendos.html",
            extras={"grupos_dividendos": [grupo]},
        )
    linea = LineaDetalle(
        descripcion="div",
        importe_eur=valor,
        extras={"fecha": "15/01/2024", "importe_usd": "$110.00", "tipo_cambio": "1.0950"},
    )
    grupo = {
        "ticker": "ORCL / FYIXX (US)",
        "operaciones": [linea],
        "total_eur": valor,
        "num_ops": 1,
        "tiene_errores": False,
    }
    return Casilla(
        numero="0029", nombre="Dividendos", valor=valor, desglose=[linea], notas="Notas div",
        template="_dividendos.html",
        extras={"grupos_dividendos": [grupo]},
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
        "ganancias_activo": Decimal("225.11") if valor > 0 else Decimal("0.00"),
        "perdidas_activo": Decimal("0.00") if valor > 0 else valor,
        "num_ops": 1,
        "tiene_errores": False,
    }
    total_ganancias = valor if valor > 0 else Decimal("0.00")
    total_perdidas = valor if valor < 0 else Decimal("0.00")
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
            "total_ganancias": total_ganancias,
            "total_perdidas": total_perdidas,
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
            "cantidad": "0.00152",
            "coste_eur": "15.55€",
            "ingresos_eur": "97.82€",
            "wallet": "Kraken",
            "notas": "",
        },
    )
    grupo = {
        "ticker": "BTC",
        "operaciones": [linea],
        "total_coste_eur": Decimal("15.55"),
        "total_ingresos_eur": Decimal("97.82"),
        "total_ganancia_eur": valor,
        "ganancias_activo": valor if valor >= 0 else Decimal("0.00"),
        "perdidas_activo": valor if valor < 0 else Decimal("0.00"),
        "num_ops": 1,
        "tiene_errores": False,
        "wallets": ["Kraken"],
    }
    return Casilla(
        numero="1800-1814", nombre="Venta de cryptos", valor=valor, desglose=[linea], notas="Notas crypto",
        template="_ganancias_crypto.html",
        extras={
            "total_cost": Decimal("15.55"),
            "total_proceeds": Decimal("97.82"),
            "total_ganancias": valor if valor >= 0 else Decimal("0.00"),
            "total_perdidas": valor if valor < 0 else Decimal("0.00"),
            "grupos_activo": [grupo],
        },
    )


def _casilla_retenciones(valor=Decimal("-7.08"), rentas_base_ahorro_eur=Decimal("70.80")):
    linea = LineaDetalle(
        descripcion="ret",
        importe_eur=valor,
        extras={"fecha": "15/01/2024", "tipo": "NRA", "importe_usd": "-$7.75", "tipo_cambio": "1.0950"},
    )
    grupo = {
        "ticker": "ORCL / FYIXX (US)",
        "operaciones": [linea],
        "total_eur": abs(valor),
        "num_ops": 1,
        "tiene_errores": False,
        "rentas_base_ahorro_eur": rentas_base_ahorro_eur,
    }
    return Casilla(
        numero="0588", nombre="Retenciones", valor=valor, desglose=[linea], notas="Notas ret",
        template="_retenciones.html",
        extras={
            "grupos_retenciones": [grupo],
            "total_rentas_base_ahorro": rentas_base_ahorro_eur,
        },
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
        assert "Casilla 0328" in html
        assert "ORCL" in html
        assert "Segunda línea" in html  # nl2br procesa notas
        assert "grupo-activo" in html  # grupos desplegables presentes
        assert "0339" in html
        assert "0340" in html
        assert "Casilla 0328" in html
        assert "Casilla 0331" in html
        assert "Valores (EUR)" in html
        assert "Valores (USD)" in html
        assert "Transmisión" in html
        assert "Adquisición" in html
        assert "Ganancia" in html
        assert "Coste EUR" not in html
        assert "Ingresos EUR" not in html
        assert "Coste USD" not in html
        assert "Ingresos USD" not in html
        assert "Fecha venta" not in html
        assert "TC venta" not in html
        assert "Ganancia EUR" not in html

    def test_seccion_retenciones(self):
        casilla = _casilla_retenciones()
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        assert "Retenciones extranjero" in html
        assert "Rentas incluidas en la base del ahorro" in html
        assert "Impuesto satisfecho en el extranjero" in html
        assert "casilla 0029" in html
        assert "Total retenciones" not in html
        assert "0589" not in html
        assert "ORCL / FYIXX (US)" in html
        assert "Deducción casillas" not in html
        assert "70,80" in html  # rentas_base_ahorro_eur del fixture

    def test_seccion_retenciones_sin_dividendos_para_activo(self):
        """Activo en retenciones pero sin dividendos → columna rentas muestra —."""
        casilla = _casilla_retenciones(rentas_base_ahorro_eur=None)
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        assert "Rentas incluidas en la base del ahorro" in html
        assert "Impuesto satisfecho en el extranjero" in html

    def test_seccion_retenciones_aviso_styling(self):
        linea_aviso = LineaDetalle(
            descripcion="ret",
            importe_eur=None,
            extras={"fecha": "15/01/2023", "tipo": "Retención", "importe_usd": "-$5.00", "tipo_cambio": "—"},
            aviso="Operación fuera del año fiscal 2024 — excluida del total",
        )
        grupo = {
            "ticker": "ORCL / FYIXX (US)",
            "operaciones": [linea_aviso],
            "total_eur": Decimal("6.00"),
            "num_ops": 1,
            "tiene_errores": False,
            "tiene_avisos": True,
        }
        casilla = Casilla(
            numero="0588", nombre="Retenciones", valor=Decimal("6.00"),
            desglose=[linea_aviso], notas="n",
            template="_retenciones.html",
            extras={"grupos_retenciones": [grupo]},
        )
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        assert "warning-row" in html
        assert "warning-badge" in html
        assert "AVISO" in html
        assert 'class="error-row"' not in html

    def test_seccion_ganancias_crypto(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        assert "Venta de cryptos" in html
        assert "1800-1814" in html
        assert "BTC" in html
        assert "Valores (EUR)" in html
        assert "Fechas" in html
        assert "Ganancia" in html
        # Fechas: primero Adquisición, luego Transmisión
        assert html.index(">Adquisición<") < html.index(">Transmisión<")
        assert "Coste EUR" not in html
        assert "Ingresos EUR" not in html
        assert "Ganancia EUR" not in html
        assert "Ganancias patrimoniales crypto" not in html
        assert "Ganancia neta casillas" not in html
        assert "XXXX" in html
        assert "verify-btn" in html

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
        assert "1800-1814" in html
        assert "0588" in html
        assert "0027" in html

    def test_error_en_casilla_muestra_badge(self):
        casilla = _casilla_dividendos(con_error=True)
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "ERROR" in html
        assert "error-badge" in html
        assert "error-row" in html

    def test_ventas_totales_calculados(self):
        casilla = _casilla_ventas(valor=Decimal("225.11"))
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # Casilla 0331 (valor compra) y 0328 (valor venta) en el summary del grupo
        assert "462.96" in html  # total_coste_eur del grupo → Casilla 0331
        assert "688.07" in html  # total_ingresos_eur del grupo → Casilla 0328
        # Casilla 0339 (ganancias) en el resumen
        assert "225.11" in html

    def test_ventas_resumen_muestra_0339_y_0340(self):
        casilla = _casilla_ventas(valor=Decimal("500.00"))
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        assert ">0339<" in html
        assert ">0340<" in html

    def test_favicon_presente_con_digitos_correctos_2025(self):
        result = ResultadoRenta(year=2025)
        html = generate(result)
        assert 'rel="icon"' in html
        assert 'type="image/svg+xml"' in html
        assert ">25<" in html

    def test_favicon_digitos_cambian_con_el_año(self):
        result = ResultadoRenta(year=2024)
        html = generate(result)
        assert ">24<" in html
        assert ">25<" not in html

    def test_ventas_tabla_detalle_sin_columna_activo(self):
        # La tabla de detalle (operaciones) no tiene columna Activo.
        # La tabla resumen sí la tiene — por eso se espera exactamente una sola <th>Activo</th>.
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        assert html.count("<th>Activo</th>") == 1

    def test_ventas_resumen_fila_por_activo(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        assert "ORCL" in html
        assert ">0336<" in html
        assert "0337/0338" in html

    def test_ventas_resumen_copy_btn_por_activo(self):
        casilla = _casilla_ventas(valor=Decimal("225.11"))
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # ganancias_activo = 225.11 → copy button
        assert "cb(this,event,'225,11'" in html

    def test_ventas_sin_total_casilla_ni_section_total(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        assert "TOTAL CASILLA" not in html
        assert "Ganancia neta casillas" not in html

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
        assert "cb(this,event,'150,00'" in html

    def test_botones_copy_en_resumen(self):
        casilla = _casilla_dividendos(valor=Decimal("1234.56"))
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "cb(this,event,'1234,56'" in html

    def test_botones_copy_valor_negativo_sin_signo(self):
        casilla = _casilla_retenciones(valor=Decimal("-7.08"))
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        # El valor negativo debe copiarse sin el signo menos
        assert "cb(this,event,'7,08'" in html

    def test_botones_copy_en_coste_ingresos_ventas(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # coste_eur="462.96€" -> 462,96; ingresos_eur="688.07€" -> 688,07
        assert "cb(this,event,'462,96'" in html
        assert "cb(this,event,'688,07'" in html

    def test_valores_visibles_en_crypto(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        # Los valores de coste e ingresos deben aparecer en el detalle (sin copy buttons)
        assert "15.55€" in html
        assert "97.82€" in html

    def test_botones_copy_ocultos_en_print(self):
        result = ResultadoRenta(year=2024)
        html = generate(result)
        assert ".copy-btn { display: none; }" in html or "copy-btn { display: none" in html
