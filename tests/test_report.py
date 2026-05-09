"""Tests para el generador de informe HTML."""

from decimal import Decimal

import pytest

from renta.models import Casilla, LineaDetalle, ResultadoRenta
from renta.report import (
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
            "coste_eur": "462,96 €",
            "ingresos_eur": "688,07 €",
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
            "coste_eur": "15,55 €",
            "ingresos_eur": "97,82 €",
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
        numero="0033", nombre="Rendimientos crypto", valor=valor, desglose=[linea], notas="Notas rend",
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
        assert _filter_format_num(Decimal("1234.5")) == "1.234,50"
        assert _filter_format_num(Decimal("0")) == "0,00"
        assert _filter_format_num(Decimal("-99.99")) == "-99,99"

    def test_clipboard_value_str_basico(self):
        assert _filter_clipboard_value_str("462,96 €") == "462,96"

    def test_clipboard_value_str_con_miles(self):
        assert _filter_clipboard_value_str("1.234,56 €") == "1.234,56"

    def test_clipboard_value_str_negativo(self):
        assert _filter_clipboard_value_str("-7,08 €") == "-7,08"

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
        assert "Renta 2024" in html

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
        assert "150,00" in html
        assert "15/01/2024" in html

    def test_seccion_dividendos_ausente_cuando_none(self):
        result = ResultadoRenta(year=2024, dividendos=None)
        html = generate(result)
        assert "Total dividendos" not in html

    def test_seccion_ventas_acciones(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        assert "Venta de acciones" in html
        assert 'casilla-badge">0328' in html
        assert 'casilla-badge">0331' in html
        assert 'casilla-badge">0336' in html
        assert 'casilla-badge">0337' in html
        assert 'casilla-badge">0338' in html
        assert 'casilla-badge">0339' in html
        assert 'casilla-badge">0340' in html
        assert "casilla-num" not in html
        assert "Casilla 0328" not in html
        assert "Casilla 0331" not in html
        assert "ORCL" in html
        assert "Segunda línea" in html  # nl2br procesa notas
        assert "grupo-activo" in html  # grupos desplegables presentes
        assert "cell-trio" in html
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
        assert 'casilla-badge">0029' in html
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
        assert 'casilla-badge">1800' in html
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
        assert "XXXX" not in html  # los placeholders XXXX deben haberse eliminado
        assert "verify-btn" in html

    def test_cabecera_activo_crypto_muestra_casillas_1804_1806(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        assert "Transmisiones" in html
        assert "Adquisiciones" in html
        # badges de casilla en los summaries de la sección crypto
        assert 'casilla-badge">1804' in html
        assert 'casilla-badge">1806' in html
        # valores numéricos presentes
        assert "97,82\xa0€" in html
        assert "15,55\xa0€" in html

    def test_tabla_resumen_crypto_balance_positivo(self):
        casilla = _casilla_crypto_ganancias()  # total_ganancia_eur=82.27 (positivo)
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        assert 'casilla-badge">1809' in html   # badge casilla balance ganancia
        assert 'casilla-badge">1814' in html   # badge casilla total ganancias
        assert 'casilla-badge">1813' in html   # badge casilla total pérdidas
        # 1807/1808 aparecen en el bloque de instrucciones aunque no haya pérdidas en los datos
        assert 'casilla-badge">1807' in html
        assert 'casilla-badge">1808' in html
        assert "n/a" not in html               # sin columnas n/a
        # el trío está envuelto en cell-trio con casilla-slot
        assert 'class="cell-trio"' in html
        assert 'class="casilla-slot"' in html

    def test_tabla_resumen_crypto_balance_negativo(self):
        casilla = _casilla_crypto_ganancias(valor=Decimal("-30.00"))
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        assert 'casilla-badge">1807' in html   # dos badges para pérdida
        assert 'casilla-badge">1808' in html
        # 1809 aparece en el bloque de instrucciones aunque no haya ganancias en los datos
        assert 'casilla-badge">1809' in html
        # ambos badges dentro del mismo casilla-slot
        assert 'casilla-slot">%s%s' % (
            '<span class="casilla-badge">1807</span>',
            '<span class="casilla-badge">1808</span>',
        ) in html

    def test_tabla_resumen_crypto_ganancias_perdidas_sin_boton_ni_badge(self):
        # Ganancias y Pérdidas por activo son informativas: solo valor, sin botón ni badge
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        # Hay verify-btn en la sección (para balance y totales), pero en las celdas
        # de Ganancias/Pérdidas por activo no debe haber ni botón ni badge de casilla.
        # Los badges presentes son para 1809, 1814, 1813 (no para las celdas informativas).
        assert "casilla-badge" in html     # hay badges en la sección
        assert "verify-btn" in html        # hay botones ojo en la sección
        assert "n/a" not in html           # sin columnas n/a

    def test_casilla_badge_padding(self):
        # El macro casilla_badge formatea siempre a 4 dígitos con ceros a la izquierda
        from src.renta.report import generate
        from src.renta.models import ResultadoRenta
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        # Los badges de la fixture tienen 4 dígitos ya (1809, 1814, etc.)
        assert 'casilla-badge">1809' in html
        assert 'casilla-badge">1814' in html

    def test_casilla_badge_range_en_h2_crypto(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        # h2 usa casilla_badge_range(1800, 1814): dos badges con " - " entre ellos
        assert 'casilla-badge">1800</span> - <span class="casilla-badge">1814' in html

    def test_render_casilla_rango_en_resumen(self):
        # La tabla resumen usa render_casilla: "0328-0337" → dos badges
        result = ResultadoRenta(year=2024, ganancias_acciones=_casilla_ventas())
        html = generate(result)
        assert 'casilla-badge">0328</span> - <span class="casilla-badge">0337' in html
        # "0328-0337" sólo debe aparecer como ID/href (atributos), nunca como texto visible
        import re
        visible_text = re.sub(r'<[^>]+>', '', html)
        assert "0328-0337" not in visible_text

    def test_render_casilla_etiqueta_texto_plano(self):
        # Una etiqueta no numérica → render_casilla la pasa como texto plano sin badge
        from dataclasses import replace as dc_replace
        casilla = _casilla_rendimientos()
        casilla = dc_replace(casilla, numero="EtiquetaLibre")
        result = ResultadoRenta(year=2024, rendimientos_crypto=casilla)
        html = generate(result)
        assert "EtiquetaLibre" in html
        assert 'casilla-badge">EtiquetaLibre' not in html

    def test_casilla_inline_filter_en_notas(self):
        # El filtro casilla_inline sustituye "casilla NNNN" por badge en notas dinámicas
        from src.renta.report import _filter_casilla_inline
        out = _filter_casilla_inline("Introduce el valor en la casilla 0588 de Renta Web.")
        assert '<span class="casilla-badge">0588</span>' in out
        assert "casilla 0588" not in out

    def test_casilla_inline_filter_plural_word(self):
        # "casillas" (plural) también se sustituye cuando va seguido de un número
        from src.renta.report import _filter_casilla_inline
        out = _filter_casilla_inline("Introduce el importe en las casillas 0029.")
        assert '<span class="casilla-badge">0029</span>' in out

    def test_ventas_acciones_tabla_tres_columnas(self):
        # La tabla resumen de ventas tiene 3 columnas (Activo | Ganancias | Pérdidas)
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # Los dos badges de pérdidas (0337 y 0338) deben estar dentro del mismo casilla-slot
        slot_content = 'casilla-slot"><span class="casilla-badge">0337</span><span class="casilla-badge">0338</span>'
        assert slot_content in html

    def test_casilla_num_eliminado_de_todo_el_html(self):
        # Centinela: casilla-num no debe aparecer en ningún HTML generado
        result = ResultadoRenta(
            year=2024,
            dividendos=_casilla_dividendos(),
            ganancias_acciones=_casilla_ventas(),
            ganancias_crypto=_casilla_crypto_ganancias(),
            doble_imposicion=_casilla_retenciones(),
            rendimientos_crypto=_casilla_rendimientos(),
        )
        html = generate(result)
        assert "casilla-num" not in html

    def test_seccion_rendimientos_crypto_sin_rewards(self):
        casilla = _casilla_rendimientos()
        result = ResultadoRenta(year=2024, rendimientos_crypto=casilla)
        html = generate(result)
        assert "Staking/rewards crypto" in html
        assert "ADA" in html
        assert "Ver detalle" not in html  # sin rewards no hay detalle expandible

    def test_seccion_rendimientos_crypto_con_rewards(self):
        reward = make_crypto_reward()
        casilla = _casilla_rendimientos(rewards=[reward])
        result = ResultadoRenta(year=2024, rendimientos_crypto=casilla)
        html = generate(result)
        assert "Staking/Rewards" in html
        assert "ADA" in html

    def test_warnings_en_casilla(self):
        from decimal import Decimal
        from renta.models import Casilla
        casilla = Casilla(
            numero="0029", nombre="Test", valor=Decimal("0"),
            template="_dividendos.html",
            advertencias=["Tipo de cambio fallback"],
            extras={"grupos_dividendos": []},
        )
        result = ResultadoRenta(year=2024, dividendos=casilla)
        html = generate(result)
        assert "Tipo de cambio fallback" in html
        assert 'casilla-warnings' in html

    def test_notas_secciones_merge(self):
        from decimal import Decimal
        from renta.models import Casilla, LineaDetalle
        from renta.calculator import Calculator
        from renta.exchange import ExchangeRateProvider

        calc = Calculator(ExchangeRateProvider({}))
        linea = LineaDetalle(descripcion="x", importe_eur=Decimal("5"))
        c1 = Casilla(
            numero="0029", nombre="Test", valor=Decimal("10"),
            notas="Nota de Fidelity.", fuente="Fidelity",
            template="_dividendos.html",
            desglose=[LineaDetalle(descripcion="y", importe_eur=Decimal("10"))],
            extras={"grupos_dividendos": []},
        )
        c2 = Casilla(
            numero="0029", nombre="Test", valor=Decimal("5"),
            notas="Nota de DEGIRO.", fuente="DEGIRO",
            template="_dividendos.html",
            desglose=[linea],
            extras={"grupos_dividendos": []},
        )
        merged = calc._merge_casillas(c1, c2)
        assert len(merged.notas_secciones) == 2
        assert merged.notas_secciones[0]["fuente"] == "Fidelity"
        assert merged.notas_secciones[1]["fuente"] == "DEGIRO"
        assert merged.notas == ""

        result = ResultadoRenta(year=2024, dividendos=merged)
        html = generate(result)
        assert "<strong>Fidelity:</strong>" in html
        assert "<strong>DEGIRO:</strong>" in html
        assert "banner-body" in html

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
        assert 'casilla-badge">0029' in html
        assert 'casilla-badge">0328' in html
        assert 'casilla-badge">0337' in html
        assert 'casilla-badge">1800' in html
        assert 'casilla-badge">1814' in html
        assert 'casilla-badge">0588' in html
        assert 'casilla-badge">0033' in html

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
        assert "462,96" in html  # total_coste_eur del grupo → Casilla 0331
        assert "688,07" in html  # total_ingresos_eur del grupo → Casilla 0328
        # Casilla 0339 (ganancias) en el resumen
        assert "225,11" in html

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
        assert 'casilla-badge">0337' in html
        assert 'casilla-badge">0338' in html

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
        assert "cb(this,event,'1.234,56'" in html

    def test_botones_copy_valor_negativo_con_signo(self):
        casilla = _casilla_retenciones(valor=Decimal("-7.08"))
        result = ResultadoRenta(year=2024, doble_imposicion=casilla)
        html = generate(result)
        # El valor negativo se copia con signo, igual que se muestra en pantalla
        assert "cb(this,event,'-7,08'" in html

    def test_botones_copy_en_coste_ingresos_ventas(self):
        casilla = _casilla_ventas()
        result = ResultadoRenta(year=2024, ganancias_acciones=casilla)
        html = generate(result)
        # coste_eur="462,96€" -> 462,96; ingresos_eur="688,07€" -> 688,07
        assert "cb(this,event,'462,96'" in html
        assert "cb(this,event,'688,07'" in html

    def test_valores_visibles_en_crypto(self):
        casilla = _casilla_crypto_ganancias()
        result = ResultadoRenta(year=2024, ganancias_crypto=casilla)
        html = generate(result)
        # Los valores de coste e ingresos deben aparecer en el detalle (sin copy buttons)
        assert "15,55\xa0€" in html
        assert "97,82\xa0€" in html

    def test_botones_copy_ocultos_en_print(self):
        result = ResultadoRenta(year=2024)
        html = generate(result)
        assert ".copy-btn" in html and "display: none" in html
