"""
Generador del informe HTML autocontenido.

- CSS inline, sin JS, sin dependencias externas
- Imprimible
- Usa <details>/<summary> para las secciones de detalle largas (staking rewards)
"""

from datetime import datetime
from decimal import Decimal

from renta.models import Casilla, KoinlyData, ResultadoRenta


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    font-size: 13px; color: #1a1a1a; background: #fff; padding: 24px;
    max-width: 1200px; margin: 0 auto;
}
h1 { font-size: 22px; margin-bottom: 4px; color: #111; }
h2 { font-size: 16px; margin: 28px 0 8px; color: #222; border-bottom: 2px solid #e0e0e0; padding-bottom: 4px; }
h3 { font-size: 13px; font-weight: 600; margin: 16px 0 6px; color: #333; }
.subtitle { color: #666; font-size: 12px; margin-bottom: 20px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 12px; }
th { background: #f5f5f5; text-align: left; padding: 6px 8px; border: 1px solid #ddd; font-weight: 600; }
td { padding: 5px 8px; border: 1px solid #e5e5e5; vertical-align: top; }
tr:nth-child(even) { background: #fafafa; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.total-row { font-weight: bold; background: #f0f0f0 !important; }
.gain { color: #1a7a1a; }
.loss { color: #c0392b; }
.zero { color: #888; }
.casilla-num { font-family: monospace; font-weight: bold; color: #1a5276; }
.warning { background: #fff8e1; border: 1px solid #f9a825; padding: 8px 12px;
           border-radius: 4px; margin: 8px 0; font-size: 12px; }
.note { background: #e8f4fd; border-left: 3px solid #2980b9; padding: 8px 12px;
        margin: 8px 0; font-size: 11px; color: #444; line-height: 1.5; }
.source { font-size: 10px; color: #999; font-style: italic; }
details { margin-bottom: 8px; }
summary { cursor: pointer; padding: 6px 8px; background: #f5f5f5;
          border: 1px solid #ddd; border-radius: 3px; font-weight: 600;
          font-size: 12px; user-select: none; }
summary:hover { background: #ebe8e8; }
footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid #e0e0e0;
         color: #999; font-size: 11px; }
.section-total { text-align: right; font-weight: bold; margin-top: 4px;
                 font-size: 13px; padding: 4px 0; }
.highlight { font-size: 15px; color: #1a5276; }
.error-row { background: #fff0f0 !important; }
.error-row td { border-color: #f5c6cb; }
.error-text { color: #c0392b; font-weight: bold; font-size: 11px; }
.error-badge { background: #c0392b; color: white; padding: 1px 6px; border-radius: 3px;
               font-size: 10px; font-weight: bold; }
.incomplete { color: #c0392b; font-style: italic; }
@media print {
    details { display: block; }
    summary { display: none; }
    .no-print { display: none; }
}
"""


def _color_class(amount: Decimal | None) -> str:
    if amount is None:
        return "zero"
    if amount > 0:
        return "gain"
    if amount < 0:
        return "loss"
    return "zero"


def _td(val: str, align_right: bool = False) -> str:
    cls = ' class="num"' if align_right else ""
    return f"<td{cls}>{val}</td>"


def _td_eur(amount: Decimal | None, color: bool = False) -> str:
    if amount is None:
        return '<td class="num error-text">NO CALCULADO</td>'
    cls = ("num " + _color_class(amount)) if color else "num"
    sign = "+" if amount > 0 else ""
    return f'<td class="{cls}">{sign}€{amount:,.2f}</td>'


def _td_error(msg: str) -> str:
    """Celda de error para una fila con tipo de cambio no disponible."""
    return f'<td class="error-text" colspan="99">Error: {msg}</td>'


def _section_total_html(casilla: Casilla, label: str, fmt: str = ",.2f") -> str:
    """Genera el div de total de sección, manejando valor None."""
    color = _color_class(casilla.valor)
    if casilla.valor is None:
        valor_str = '<span class="error-text">NO CALCULABLE</span>'
    elif "+" in fmt:
        valor_str = f'<span class="highlight {color}">€{casilla.valor:+,.2f}</span>'
    else:
        valor_str = f'<span class="highlight {color}">€{casilla.valor:,.2f}</span>'
    return f'<div class="section-total">{label}: {valor_str}</div>'


def _td_source(source) -> str:
    if source:
        return f'<td><span class="source">{source}</span></td>'
    return "<td></td>"


def _section_resumen(result: ResultadoRenta) -> str:
    rows = []
    casillas = [
        result.dividendos,
        result.ganancias_acciones,
        result.ganancias_crypto,
        result.doble_imposicion,
        result.rendimientos_crypto,
    ]
    for c in casillas:
        if c is None:
            continue
        if c.errores:
            valor_cell = (
                f'<td class="num incomplete">'
                f'<span class="error-badge">ERROR</span> '
                f'No calculable — {len(c.errores)} operación(es) sin tipo de cambio'
                f'</td>'
            )
        else:
            color = _color_class(c.valor)
            sign = "+" if c.valor > 0 else ""
            valor_cell = f'<td class="num {color}" style="font-weight:bold">{sign}€{c.valor:,.2f}</td>'
        rows.append(
            "<tr>"
            + f'<td><span class="casilla-num">{c.numero}</span></td>'
            + f"<td>{c.nombre}</td>"
            + valor_cell
            + "</tr>"
        )

    return (
        "<h2>Resumen de casillas</h2>"
        "<table>"
        "<thead><tr>"
        '<th style="width:140px">Casilla</th>'
        "<th>Concepto</th>"
        '<th style="width:130px" class="num">Importe (EUR)</th>'
        "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table>"
    )


def _section_dividendos(casilla: Casilla) -> str:
    if not casilla or not casilla.desglose:
        return ""
    rows = []
    for item in casilla.desglose:
        if item.error:
            row = (
                '<tr class="error-row">'
                + _td(item.extras.get("fecha", ""))
                + _td(item.extras.get("importe_usd", ""), True)
                + f'<td class="error-text" colspan="2">No se pudo obtener el tipo de cambio: {item.error}</td>'
                + _td_source(item.fuente)
                + "</tr>"
            )
        else:
            row = (
                "<tr>"
                + _td(item.extras.get("fecha", ""))
                + _td(item.extras.get("importe_usd", ""), True)
                + _td(item.extras.get("tipo_cambio", ""), True)
                + _td_eur(item.importe_eur)
                + _td_source(item.fuente)
                + "</tr>"
            )
        rows.append(row)
    rows.append(
        '<tr class="total-row">'
        + "<td colspan='3'><strong>Total dividendos</strong></td>"
        + _td_eur(casilla.valor)
        + "<td></td></tr>"
    )
    return (
        f"<h2>Dividendos — Casilla {casilla.numero}</h2>"
        + f'<div class="note">{casilla.notas}</div>'
        + "<table><thead><tr>"
        + "<th>Fecha</th>"
        + '<th class="num">Importe USD</th>'
        + '<th class="num">Tipo cambio BCE (USD/EUR)</th>'
        + '<th class="num">Importe EUR</th>'
        + "<th>Origen</th>"
        + "</tr></thead>"
        + "<tbody>" + "".join(rows) + "</tbody>"
        + "</table>"
        + _section_total_html(casilla, f"Casilla {casilla.numero}")
    )


def _section_ventas_acciones(casilla: Casilla) -> str:
    if not casilla or not casilla.desglose:
        return ""
    rows = []
    for item in casilla.desglose:
        e = item.extras
        if item.error:
            row = (
                '<tr class="error-row">'
                + _td(e.get("ticker", ""))
                + _td(e.get("fecha_venta", ""))
                + _td(e.get("fecha_vesting", ""))
                + _td(e.get("cantidad", ""), True)
                + _td(e.get("coste_usd", ""), True)
                + _td(e.get("ingresos_usd", ""), True)
                + f'<td class="error-text" colspan="5">No se pudo obtener el tipo de cambio: {item.error}</td>'
                + _td(e.get("tipo_accion", ""))
                + _td_source(item.fuente)
                + "</tr>"
            )
        else:
            row = (
                "<tr>"
                + _td(e.get("ticker", ""))
                + _td(e.get("fecha_venta", ""))
                + _td(e.get("fecha_vesting", ""))
                + _td(e.get("cantidad", ""), True)
                + _td(e.get("coste_usd", ""), True)
                + _td(e.get("ingresos_usd", ""), True)
                + _td(e.get("tipo_vesting", ""), True)
                + _td(e.get("tipo_venta", ""), True)
                + _td(e.get("coste_eur", ""), True)
                + _td(e.get("ingresos_eur", ""), True)
                + _td_eur(item.importe_eur, color=True)
                + _td(e.get("tipo_accion", ""))
                + _td_source(item.fuente)
                + "</tr>"
            )
        rows.append(row)

    total_cost = sum(
        Decimal(item.extras["coste_eur"].replace("€", "").replace(",", ""))
        for item in casilla.desglose
        if "coste_eur" in item.extras and not item.error
    )
    total_proceeds = sum(
        Decimal(item.extras["ingresos_eur"].replace("€", "").replace(",", ""))
        for item in casilla.desglose
        if "ingresos_eur" in item.extras and not item.error
    )
    rows.append(
        '<tr class="total-row">'
        + "<td colspan='8'><strong>TOTAL</strong></td>"
        + f'<td class="num"><strong>€{total_cost:,.2f}</strong></td>'
        + f'<td class="num"><strong>€{total_proceeds:,.2f}</strong></td>'
        + _td_eur(casilla.valor, color=True)
        + "<td colspan='2'></td></tr>"
    )

    notas_html = casilla.notas.replace("\n", "<br>")
    return (
        f"<h2>Ventas de acciones (RSUs) — Casillas {casilla.numero}</h2>"
        + f'<div class="note">{notas_html}</div>'
        + f"<details open><summary>Ver detalle de {len(casilla.desglose)} operaciones</summary>"
        + "<table style='margin-top:8px'><thead><tr>"
        + "<th>Ticker</th><th>Fecha venta</th><th>Fecha vesting</th>"
        + '<th class="num">Cantidad</th>'
        + '<th class="num">Coste USD</th><th class="num">Ingresos USD</th>'
        + '<th class="num">TC vesting</th><th class="num">TC venta</th>'
        + '<th class="num">Coste EUR</th><th class="num">Ingresos EUR</th>'
        + '<th class="num">Ganancia EUR</th><th>Tipo</th><th>Origen</th>'
        + "</tr></thead>"
        + "<tbody>" + "".join(rows) + "</tbody>"
        + "</table></details>"
        + _section_total_html(casilla, f"Ganancia neta casillas {casilla.numero}", fmt="+,.2f")
    )


def _section_retenciones(casilla: Casilla) -> str:
    if not casilla or not casilla.desglose:
        return ""
    rows = []
    for item in casilla.desglose:
        e = item.extras
        if item.error:
            row = (
                '<tr class="error-row">'
                + _td(e.get("fecha", ""))
                + _td(e.get("tipo", ""))
                + _td(e.get("importe_usd", ""), True)
                + f'<td class="error-text" colspan="2">No se pudo obtener el tipo de cambio: {item.error}</td>'
                + _td_source(item.fuente)
                + "</tr>"
            )
        else:
            row = (
                "<tr>"
                + _td(e.get("fecha", ""))
                + _td(e.get("tipo", ""))
                + _td(e.get("importe_usd", ""), True)
                + _td(e.get("tipo_cambio", ""), True)
                + _td_eur(item.importe_eur, color=True)
                + _td_source(item.fuente)
                + "</tr>"
            )
        rows.append(row)

    notas_html = casilla.notas.replace("\n", "<br>")
    if casilla.valor is None:
        total_html = f'<span class="error-text">NO CALCULABLE — hay operaciones sin tipo de cambio</span>'
    else:
        total_html = f'<span class="highlight">€{casilla.valor:,.2f}</span>'
    return (
        f"<h2>Retenciones EEUU (doble imposición) — Casillas {casilla.numero}</h2>"
        + f'<div class="note">{notas_html}</div>'
        + f"<details open><summary>Ver detalle de {len(casilla.desglose)} entradas</summary>"
        + "<table style='margin-top:8px'><thead><tr>"
        + "<th>Fecha</th><th>Tipo</th>"
        + '<th class="num">Importe USD</th>'
        + '<th class="num">Tipo cambio BCE</th>'
        + '<th class="num">Importe EUR</th>'
        + "<th>Origen</th>"
        + "</tr></thead>"
        + "<tbody>" + "".join(rows) + "</tbody>"
        + "</table></details>"
        + f'<div class="section-total">Deducción casillas {casilla.numero}: {total_html}</div>'
    )


def _section_ganancias_crypto(casilla: Casilla) -> str:
    if not casilla or not casilla.desglose:
        return ""
    rows = []
    for item in casilla.desglose:
        e = item.extras
        row = (
            "<tr>"
            + _td(e.get("activo", ""))
            + _td(e.get("fecha_venta", ""))
            + _td(e.get("fecha_adquisicion", ""))
            + _td(e.get("cantidad", ""), True)
            + _td(e.get("coste_eur", ""), True)
            + _td(e.get("ingresos_eur", ""), True)
            + _td_eur(item.importe_eur, color=True)
            + _td(e.get("wallet", ""))
            + _td(e.get("notas", ""))
            + _td_source(item.fuente)
            + "</tr>"
        )
        rows.append(row)
    rows.append(
        '<tr class="total-row"><td colspan="6"><strong>TOTAL</strong></td>'
        + _td_eur(casilla.valor, color=True)
        + "<td colspan='3'></td></tr>"
    )
    return (
        f"<h2>Ganancias patrimoniales crypto — Casillas {casilla.numero}</h2>"
        + f'<div class="note">{casilla.notas}</div>'
        + "<table><thead><tr>"
        + "<th>Activo</th><th>Fecha venta</th><th>Fecha adquisición</th>"
        + '<th class="num">Cantidad</th>'
        + '<th class="num">Coste EUR</th><th class="num">Ingresos EUR</th>'
        + '<th class="num">Ganancia EUR</th>'
        + "<th>Wallet</th><th>Notas</th><th>Origen</th>"
        + "</tr></thead>"
        + "<tbody>" + "".join(rows) + "</tbody>"
        + "</table>"
        + _section_total_html(casilla, f"Ganancia neta casillas {casilla.numero}", fmt="+,.2f")
    )


def _section_rendimientos_crypto(casilla: Casilla, rewards_detail) -> str:
    if not casilla:
        return ""

    resumen_rows = []
    for item in casilla.desglose:
        e = item.extras
        resumen_rows.append(
            "<tr>"
            + _td(e.get("activo", ""))
            + _td(e.get("num_operaciones", ""), True)
            + _td_eur(item.importe_eur)
            + "</tr>"
        )
    total_ops = sum(int(item.extras.get("num_operaciones", 0)) for item in casilla.desglose)
    resumen_rows.append(
        '<tr class="total-row">'
        + "<td><strong>TOTAL</strong></td>"
        + f'<td class="num">{total_ops}</td>'
        + _td_eur(casilla.valor)
        + "</tr>"
    )

    detail_rows = []
    for r in rewards_detail:
        row = (
            "<tr>"
            + _td(r.date.strftime("%d/%m/%Y %H:%M"))
            + _td(r.asset)
            + _td(str(r.quantity), True)
            + _td(f"€{r.price_eur:,.4f}", True)
            + _td(r.reward_type)
            + _td(r.description)
            + _td(r.wallet)
            + _td_source(r.source)
            + "</tr>"
        )
        detail_rows.append(row)

    detail_section = ""
    if detail_rows:
        detail_section = (
            f"<details><summary>Ver detalle de {len(rewards_detail)} operaciones de staking/rewards</summary>"
            + "<table style='margin-top:8px'><thead><tr>"
            + "<th>Fecha</th><th>Activo</th>"
            + '<th class="num">Cantidad</th><th class="num">Precio EUR</th>'
            + "<th>Tipo</th><th>Descripción</th><th>Wallet</th><th>Origen</th>"
            + "</tr></thead>"
            + "<tbody>" + "".join(detail_rows) + "</tbody>"
            + "</table></details>"
        )

    return (
        f"<h2>Rendimientos de staking/rewards crypto — {casilla.numero}</h2>"
        + f'<div class="note">{casilla.notas}</div>'
        + "<h3>Resumen por activo</h3>"
        + "<table style='max-width:500px'><thead><tr>"
        + "<th>Activo</th>"
        + '<th class="num">Nº operaciones</th>'
        + '<th class="num">Total EUR</th>'
        + "</tr></thead>"
        + "<tbody>" + "".join(resumen_rows) + "</tbody>"
        + "</table>"
        + detail_section
        + _section_total_html(casilla, f"Total {casilla.numero}")
    )


def _section_tipos_cambio(rates_used: dict) -> str:
    if not rates_used:
        return ""
    rows = []
    for fecha in sorted(rates_used.keys()):
        info = rates_used[fecha]
        rate = info.get("rate", "")
        effective = info.get("effective_date", fecha)
        nota = f"(tipo del {effective})" if effective != fecha else ""
        rows.append(
            "<tr>"
            + _td(fecha.strftime("%d/%m/%Y"))
            + _td(str(rate), True)
            + _td(nota)
            + "</tr>"
        )
    return (
        "<h2>Tipos de cambio BCE utilizados</h2>"
        + '<p style="font-size:11px;color:#666;margin-bottom:8px">'
        + "Fuente: Banco Central Europeo (data-api.ecb.europa.eu). "
        + "Tipo de referencia USD/EUR. Para convertir USD→EUR: EUR = USD ÷ tipo."
        + "</p>"
        + f"<details><summary>Ver {len(rates_used)} tipos de cambio utilizados</summary>"
        + "<table style='max-width:450px;margin-top:8px'><thead><tr>"
        + "<th>Fecha transacción</th>"
        + '<th class="num">Tipo (USD/EUR)</th>'
        + "<th>Nota</th>"
        + "</tr></thead>"
        + "<tbody>" + "".join(rows) + "</tbody>"
        + "</table></details>"
    )


def generate(result: ResultadoRenta, koinly: KoinlyData | None = None) -> str:
    warnings_html = ""
    if result.warnings:
        items = "".join(f"<li>{w}</li>" for w in result.warnings)
        warnings_html = f'<div class="warning">Advertencias:<ul style="margin:4px 0 0 16px">{items}</ul></div>'

    rewards_detail = koinly.rewards if koinly else []

    sections = [
        _section_resumen(result),
        warnings_html,
        _section_dividendos(result.dividendos) if result.dividendos else "",
        _section_ventas_acciones(result.ganancias_acciones) if result.ganancias_acciones else "",
        _section_retenciones(result.doble_imposicion) if result.doble_imposicion else "",
        _section_ganancias_crypto(result.ganancias_crypto) if result.ganancias_crypto else "",
        _section_rendimientos_crypto(result.rendimientos_crypto, rewards_detail) if result.rendimientos_crypto else "",
        _section_tipos_cambio(result.exchange_rates_used),
    ]

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    body = "\n".join(s for s in sections if s)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>Declaración de la Renta {result.year} - Cálculos</title>\n"
        f"  <style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>Declaración de la Renta {result.year}</h1>\n"
        f'  <p class="subtitle">Cálculo de casillas del modelo 100 · Generado el {generated_at}</p>\n'
        f"  {body}\n"
        "  <footer>\n"
        "    Generado con <strong>renta</strong> · Datos del BCE ·\n"
        "    Este documento es orientativo y no constituye asesoramiento fiscal.\n"
        "    Verifique todos los valores antes de presentar la declaración.\n"
        "  </footer>\n"
        "</body>\n"
        "</html>"
    )
