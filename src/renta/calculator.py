"""
Calculadora fiscal: convierte los datos parseados a casillas del modelo 100.

Reglas aplicadas:
- Dividendos: convertir USD a EUR al tipo BCE de la fecha del dividendo → casilla 0029
- Ventas de acciones (RSUs):
    · Cost basis convertido al tipo BCE de la fecha de VESTING (date acquired)
    · Proceeds convertidos al tipo BCE de la fecha de VENTA (date sold)
    → casillas 0326-0340 (ganancias patrimoniales)
- Retenciones EEUU (nonresident alien withholding):
    · Sumar todos los importes (negativos = retención, positivos = ajuste/devolución)
    · El neto es la deducción por doble imposición internacional → casilla 0588
    · NOTA: la deducción está limitada al tipo medio efectivo español sobre esas rentas
- Ganancias crypto: ya en EUR, directo → casillas 0326-0340
- Rewards staking: ya en EUR, sumar total → rendimientos del capital mobiliario

Si no se puede obtener el tipo de cambio para una fecha, la fila se marca con error
y se excluye del total. El total de la casilla se marca como None si hay errores.
NUNCA se usa un tipo de cambio ficticio (como 1:1) para producir un valor incorrecto.
"""

from decimal import Decimal
from typing import Any

from renta.exchange import ExchangeRateProvider
from renta.formatting import format_crypto_qty as _fmt_qty
from renta.formatting import format_eur as _fmt_eur
from renta.formatting import format_rate as _fmt_rate
from renta.formatting import format_usd as _fmt_usd
from renta.models import (
    BceWarning,
    Casilla,
    CryptoCapitalGain,
    CryptoReward,
    DegiroData,
    DegiroDividend,
    DegiroStockSale,
    DividendEntry,
    FidelityData,
    KoinlyData,
    KoinlySpainData,
    LineaDetalle,
    ResultadoRenta,
    StockSale,
    WithholdingEntry,
)


_NOTA_CASILLA_0588 = (
    "Impuestos retenidos en el extranjero sobre dividendos y otros rendimientos. "
    "Declarándolos aquí se aplica la deducción por doble imposición internacional: "
    "el importe ya tributado fuera se descuenta de lo que correspondería pagar en España."
)



def _build_grupos_dividendos(grupos_data: dict) -> list[dict]:
    """Construye la lista de grupos de dividendos por activo ordenada alfabéticamente."""
    grupos = []
    for activo in sorted(grupos_data.keys()):
        gd = grupos_data[activo]
        ops_sorted = [linea for _, linea in sorted(gd["ops_with_date"], key=lambda x: x[0])]
        total_eur = None if gd["tiene_errores"] else gd["total"].quantize(Decimal("0.01"))
        grupos.append({
            "ticker": activo,
            "operaciones": ops_sorted,
            "total_eur": total_eur,
            "num_ops": len(ops_sorted),
            "tiene_errores": gd["tiene_errores"],
            "tiene_avisos": gd.get("tiene_avisos", False),
        })
    return grupos


def _build_grupos_retenciones(grupos_data: dict) -> list[dict]:
    """Construye la lista de grupos de retenciones por activo ordenada alfabéticamente."""
    grupos = []
    for activo in sorted(grupos_data.keys()):
        gd = grupos_data[activo]
        ops_sorted = [linea for _, linea in sorted(gd["ops_with_date"], key=lambda x: x[0])]
        total_eur = None if gd["tiene_errores"] else abs(gd["total"]).quantize(Decimal("0.01"))
        grupos.append({
            "ticker": activo,
            "operaciones": ops_sorted,
            "total_eur": total_eur,
            "num_ops": len(ops_sorted),
            "tiene_errores": gd["tiene_errores"],
            "tiene_avisos": gd.get("tiene_avisos", False),
        })
    return grupos


def _build_grupos_activo(grupos_data: dict) -> list[dict]:
    """Construye la lista de grupos por activo ordenada alfabéticamente por ticker."""
    grupos_activo = []
    for ticker in sorted(grupos_data.keys()):
        gd = grupos_data[ticker]
        ops_sorted = [linea for _, linea in sorted(gd["ops_with_date"], key=lambda x: x[0])]
        if gd["tiene_errores"]:
            total_coste_eur = None
            total_ingresos_eur = None
            total_ganancia_eur = None
            ganancias_activo = None
            perdidas_activo = None
        else:
            total_coste_eur = gd["coste"].quantize(Decimal("0.01"))
            total_ingresos_eur = gd["ingresos"].quantize(Decimal("0.01"))
            total_ganancia_eur = (total_ingresos_eur - total_coste_eur)
            ganancias_activo = sum(
                (l.importe_eur for _, l in gd["ops_with_date"] if l.importe_eur is not None and l.importe_eur > 0),
                Decimal("0"),
            ).quantize(Decimal("0.01"))
            perdidas_activo = sum(
                (l.importe_eur for _, l in gd["ops_with_date"] if l.importe_eur is not None and l.importe_eur < 0),
                Decimal("0"),
            ).quantize(Decimal("0.01"))
        grupos_activo.append({
            "ticker": ticker,
            "operaciones": ops_sorted,
            "total_coste_eur": total_coste_eur,
            "total_ingresos_eur": total_ingresos_eur,
            "total_ganancia_eur": total_ganancia_eur,
            "ganancias_activo": ganancias_activo,
            "perdidas_activo": perdidas_activo,
            "num_ops": len(ops_sorted),
            "tiene_errores": gd["tiene_errores"],
            "tiene_avisos": gd.get("tiene_avisos", False),
        })
    return grupos_activo


class Calculator:
    def __init__(self, rates: ExchangeRateProvider):
        self.rates = rates
        self._rates_used: dict = {}
        self._warnings: list[str] = []
        self._current_section_warns: list[str] | None = None
        self._current_section_bce: list[BceWarning] | None = None

    def _record_rate(self, d, rate, effective):
        self._rates_used[d] = {"rate": rate, "effective_date": effective}

    def _convert_usd(self, amount_usd: Decimal, on_date) -> tuple[Decimal | None, Decimal | None, str | None]:
        """
        Convierte USD a EUR usando el tipo BCE de on_date.
        Devuelve (eur, rate, error_msg).
        Si no se puede obtener el tipo, devuelve (None, None, mensaje_error).
        NUNCA devuelve un tipo ficticio.
        """
        try:
            eur, rate, eff = self.rates.usd_to_eur(amount_usd, on_date)
            self._record_rate(on_date, rate, eff)
            if eff != on_date:
                motivo = "fin de semana" if on_date.weekday() >= 5 else "día festivo/sin cotización del BCE"
                warn_msg = (
                    f"Tipo de cambio para {on_date.strftime('%d/%m/%Y')} no disponible ({motivo}), "
                    f"usando el de {eff.strftime('%d/%m/%Y')} ({_fmt_rate(rate)})"
                )
                self._warnings.append(warn_msg)
                if self._current_section_bce is not None:
                    key = (on_date, eff)
                    if not any((w.original_date, w.effective_date) == key for w in self._current_section_bce):
                        self._current_section_bce.append(BceWarning(
                            original_date=on_date,
                            effective_date=eff,
                            rate=rate,
                            motivo=motivo,
                        ))
            return eur, rate, None
        except ValueError as e:
            msg = str(e)
            err_msg = f"Error al obtener tipo de cambio: {msg}"
            self._warnings.append(err_msg)
            if self._current_section_warns is not None and err_msg not in self._current_section_warns:
                self._current_section_warns.append(err_msg)
            return None, None, msg

    def calculate(
        self,
        parsed_data: dict[str, Any],
        year: int,
    ) -> ResultadoRenta:
        fidelity = parsed_data.get("fidelity", FidelityData())
        koinly = parsed_data.get("koinly", KoinlyData())
        degiro = parsed_data.get("degiro", DegiroData())
        koinly_spain: KoinlySpainData | None = parsed_data.get("koinly_spain")

        result = ResultadoRenta(year=year)

        result.dividendos = self._merge_casillas(
            self._calc_dividendos(fidelity.dividends, year),
            self._calc_dividendos_degiro(degiro.dividends),
        )
        result.ganancias_acciones = self._merge_casillas(
            self._calc_ganancias_acciones(fidelity.stock_sales, year),
            self._calc_ganancias_degiro(degiro.stock_sales),
        )
        result.doble_imposicion = self._merge_casillas(
            self._calc_doble_imposicion(fidelity.withholdings, year),
            self._calc_doble_imposicion_degiro(degiro.dividends),
        )

        # Enriquecer grupos_retenciones con el total de dividendos por activo (casilla 0029)
        div_por_ticker = {
            g["ticker"]: g["total_eur"]
            for g in result.dividendos.extras.get("grupos_dividendos", [])
        }
        grupos_ret = result.doble_imposicion.extras.get("grupos_retenciones", [])
        for g in grupos_ret:
            g["rentas_base_ahorro_eur"] = div_por_ticker.get(g["ticker"])
        total_rentas = result.dividendos.valor
        result.doble_imposicion.extras["total_rentas_base_ahorro"] = total_rentas

        result.ganancias_crypto = self._calc_ganancias_crypto(
            koinly.capital_gains,
            koinly.asset_summary,
            asset_totals_official=koinly_spain.asset_totals if koinly_spain else None,
            summary_costs_eur=koinly.summary_costs_eur,
        )
        result.rendimientos_crypto = self._calc_rendimientos_crypto(koinly)
        result.airdrops_crypto = self._calc_airdrops_crypto(koinly)

        result.exchange_rates_used = dict(self._rates_used)
        result.warnings = list(self._warnings)

        return result

    def _merge_casillas(self, *casillas: Casilla) -> Casilla:
        """Combina varias casillas del mismo tipo en una sola."""
        non_empty = [c for c in casillas if c.desglose]
        if len(non_empty) == 0:
            return casillas[0]
        if len(non_empty) == 1:
            return non_empty[0]

        # Concatenar desgloses
        merged_desglose = []
        for c in non_empty:
            merged_desglose.extend(c.desglose)

        # Sumar valores (None si alguno es None)
        merged_valor: Decimal | None = Decimal("0")
        for c in non_empty:
            if c.valor is None:
                merged_valor = None
                break
            merged_valor += c.valor  # type: ignore[operator]
        if merged_valor is not None:
            merged_valor = merged_valor.quantize(Decimal("0.01"))

        # Combinar errores y notas
        merged_errores = []
        merged_notas_parts = []
        for c in non_empty:
            merged_errores.extend(c.errores)
            if c.notas and c.notas not in merged_notas_parts:
                merged_notas_parts.append(c.notas)

        # Combinar extras (total_cost, total_proceeds, total_ganancias, total_perdidas) sumando si existen
        merged_extras: dict = {}
        for key in ("total_cost", "total_proceeds", "total_ganancias", "total_perdidas"):
            vals = [c.extras[key] for c in non_empty if key in c.extras]
            if vals:
                merged_extras[key] = sum(vals, Decimal("0")).quantize(Decimal("0.01"))

        # Combinar grupos_activo concatenando y reordenando alfabéticamente
        all_grupos = []
        for c in non_empty:
            if "grupos_activo" in c.extras:
                all_grupos.extend(c.extras["grupos_activo"])
        if all_grupos:
            merged_extras["grupos_activo"] = sorted(all_grupos, key=lambda g: g["ticker"])

        # Combinar grupos_dividendos concatenando y reordenando alfabéticamente
        all_grupos_div = []
        for c in non_empty:
            if "grupos_dividendos" in c.extras:
                all_grupos_div.extend(c.extras["grupos_dividendos"])
        if all_grupos_div:
            merged_extras["grupos_dividendos"] = sorted(all_grupos_div, key=lambda g: g["ticker"])

        # Combinar grupos_retenciones concatenando y reordenando alfabéticamente
        all_grupos_ret = []
        for c in non_empty:
            if "grupos_retenciones" in c.extras:
                all_grupos_ret.extend(c.extras["grupos_retenciones"])
        if all_grupos_ret:
            merged_extras["grupos_retenciones"] = sorted(all_grupos_ret, key=lambda g: g["ticker"])

        merged_advertencias = []
        for c in non_empty:
            merged_advertencias.extend(c.advertencias)

        merged_bce: list = []
        seen_bce: set = set()
        for c in non_empty:
            for w in c.bce_warnings:
                key = (w.original_date, w.effective_date)
                if key not in seen_bce:
                    seen_bce.add(key)
                    merged_bce.append(w)

        # Construir notas_secciones si hay 2+ fuentes con notas distintas
        notas_secciones: list[dict] = []
        distinct_notas = list(dict.fromkeys(merged_notas_parts))  # preserva orden, dedup
        if len(distinct_notas) > 1:
            for c in non_empty:
                if c.notas:
                    notas_secciones.append({"fuente": c.fuente or "", "notas": c.notas})
            merged_notas_str = ""
        else:
            merged_notas_str = "\n\n".join(merged_notas_parts)

        base = non_empty[0]
        return Casilla(
            numero=base.numero,
            nombre=base.nombre,
            valor=merged_valor,
            desglose=merged_desglose,
            notas=merged_notas_str,
            errores=merged_errores,
            advertencias=merged_advertencias,
            bce_warnings=merged_bce,
            template=base.template,
            extras=merged_extras,
            notas_secciones=notas_secciones,
        )

    def _calc_dividendos(self, dividends: list[DividendEntry], year: int) -> Casilla:
        self._current_section_warns = []
        self._current_section_bce = []
        desglose = []
        total = Decimal("0")
        errores = []
        _sec_warns: list[str] = []
        grupos_data: dict = {}

        for div in dividends:
            activo = "ORCL / FYIXX (US)"
            if activo not in grupos_data:
                grupos_data[activo] = {"ops_with_date": [], "total": Decimal("0"), "tiene_errores": False, "tiene_avisos": False}

            if div.date.year != year:
                aviso_msg = f"Operación fuera del año fiscal {year}"
                _sec_warns.append(
                    f"Dividendo del {div.date.strftime('%d/%m/%Y')} excluido: no pertenece al año fiscal {year}"
                )
                linea = LineaDetalle(
                    descripcion=div.date.strftime("%d/%m/%Y"),
                    importe_eur=None,
                    fuente=div.source,
                    extras={
                        "activo": activo,
                        "fecha": div.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(div.amount_usd),
                        "tipo_cambio": "—",
                        "importe_eur": "—",
                    },
                    aviso=aviso_msg,
                )
                grupos_data[activo]["tiene_avisos"] = True
                desglose.append(linea)
                grupos_data[activo]["ops_with_date"].append((div.date, linea))
                continue

            eur, rate, err = self._convert_usd(div.amount_usd, div.date)
            div.amount_eur = eur
            div.exchange_rate = rate

            if err:
                error_msg = f"No se pudo obtener el tipo de cambio: {err}"
                errores.append(f"{div.date.strftime('%d/%m/%Y')} ({_fmt_usd(div.amount_usd)}): {err}")
                linea = LineaDetalle(
                    descripcion=div.date.strftime("%d/%m/%Y"),
                    importe_eur=None,
                    fuente=div.source,
                    extras={
                        "activo": activo,
                        "fecha": div.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(div.amount_usd),
                        "tipo_cambio": "—",
                        "importe_eur": "—",
                    },
                    error=error_msg,
                )
                grupos_data[activo]["tiene_errores"] = True
            else:
                total += eur
                linea = LineaDetalle(
                    descripcion=div.date.strftime("%d/%m/%Y"),
                    importe_eur=eur,
                    fuente=div.source,
                    extras={
                        "activo": activo,
                        "fecha": div.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(div.amount_usd),
                        "tipo_cambio": _fmt_rate(rate),
                        "importe_eur": _fmt_eur(eur),
                    },
                )
                grupos_data[activo]["total"] += eur
            desglose.append(linea)
            grupos_data[activo]["ops_with_date"].append((div.date, linea))

        valor = None if errores else total.quantize(Decimal("0.01"))
        bce_warns = self._current_section_bce or []
        self._current_section_warns = None
        self._current_section_bce = None
        return Casilla(
            numero="0029",
            nombre="Rendimientos del capital mobiliario - Dividendos",
            valor=valor,
            desglose=desglose,
            notas=(
                "Los dividendos de acciones USA tributan como rendimientos del capital "
                "mobiliario. Cada importe se ha convertido al tipo de cambio BCE del "
                "día del dividendo."
            ),
            errores=errores,
            advertencias=_sec_warns,
            bce_warnings=bce_warns,
            template="_dividendos.html",
            extras={"grupos_dividendos": _build_grupos_dividendos(grupos_data)},
            fuente="Fidelity",
        )

    def _calc_ganancias_acciones(self, sales: list[StockSale], year: int) -> Casilla:
        self._current_section_warns = []
        self._current_section_bce = []
        desglose = []
        total_proceeds = Decimal("0")
        total_cost = Decimal("0")
        errores = []
        _sec_warns: list[str] = []
        # ticker -> {ops_with_date, coste, ingresos, tiene_errores}
        grupos_data: dict[str, dict[str, Any]] = {}

        for sale in sales:
            if sale.ticker not in grupos_data:
                grupos_data[sale.ticker] = {
                    "ops_with_date": [],
                    "coste": Decimal("0"),
                    "ingresos": Decimal("0"),
                    "tiene_errores": False,
                    "tiene_avisos": False,
                }

            if sale.date_sold.year != year:
                aviso_msg = f"Operación fuera del año fiscal {year}"
                _sec_warns.append(
                    f"Venta del {sale.date_sold.strftime('%d/%m/%Y')} excluida: no pertenece al año fiscal {year}"
                )
                sale.cost_basis_eur = None
                sale.proceeds_eur = None
                sale.gain_loss_eur = None
                linea: LineaDetalle = LineaDetalle(
                    descripcion=f"{sale.ticker} · {sale.date_sold.strftime('%d/%m/%Y')}",
                    importe_eur=None,
                    fuente=sale.source,
                    extras={
                        "ticker": f"{sale.ticker} (US)",
                        "fecha_venta": sale.date_sold.strftime("%d/%m/%Y"),
                        "fecha_vesting": sale.date_acquired.strftime("%d/%m/%Y"),
                        "cantidad": _fmt_qty(sale.quantity),
                        "coste_usd": _fmt_usd(sale.cost_basis_usd),
                        "ingresos_usd": _fmt_usd(sale.proceeds_usd),
                        "tipo_vesting": "—",
                        "tipo_venta": "—",
                        "coste_eur": "—",
                        "ingresos_eur": "—",
                        "ganancia_eur": "—",
                        "tipo_accion": sale.stock_source,
                    },
                    aviso=aviso_msg,
                )
                grupos_data[sale.ticker]["tiene_avisos"] = True
                desglose.append(linea)
                grupos_data[sale.ticker]["ops_with_date"].append((sale.date_sold, linea))
                continue

            cost_eur, rate_acq, err_acq = self._convert_usd(sale.cost_basis_usd, sale.date_acquired)
            proceeds_eur, rate_sold, err_sold = self._convert_usd(sale.proceeds_usd, sale.date_sold)

            err = err_acq or err_sold

            if err:
                err_detail = (
                    (f"tipo vesting ({sale.date_acquired.strftime('%d/%m/%Y')}): {err_acq}" if err_acq else "")
                    + (f"tipo venta ({sale.date_sold.strftime('%d/%m/%Y')}): {err_sold}" if err_sold else "")
                )
                error_msg = f"No se pudo obtener el tipo de cambio: {err_detail}"
                errores.append(
                    f"{sale.ticker} vendido {sale.date_sold.strftime('%d/%m/%Y')}: {err_detail}"
                )
                sale.cost_basis_eur = None
                sale.proceeds_eur = None
                sale.gain_loss_eur = None
                linea = LineaDetalle(
                    descripcion=f"{sale.ticker} · {sale.date_sold.strftime('%d/%m/%Y')}",
                    importe_eur=None,
                    fuente=sale.source,
                    extras={
                        "ticker": f"{sale.ticker} (US)",
                        "fecha_venta": sale.date_sold.strftime("%d/%m/%Y"),
                        "fecha_vesting": sale.date_acquired.strftime("%d/%m/%Y"),
                        "cantidad": _fmt_qty(sale.quantity),
                        "coste_usd": _fmt_usd(sale.cost_basis_usd),
                        "ingresos_usd": _fmt_usd(sale.proceeds_usd),
                        "tipo_vesting": "—",
                        "tipo_venta": "—",
                        "coste_eur": "—",
                        "ingresos_eur": "—",
                        "ganancia_eur": "—",
                        "tipo_accion": sale.stock_source,
                    },
                    error=error_msg,
                )
                grupos_data[sale.ticker]["tiene_errores"] = True
            else:
                gain_eur = proceeds_eur - cost_eur
                sale.cost_basis_eur = cost_eur
                sale.proceeds_eur = proceeds_eur
                sale.gain_loss_eur = gain_eur
                sale.exchange_rate_acquired = rate_acq
                sale.exchange_rate_sold = rate_sold
                total_proceeds += proceeds_eur
                total_cost += cost_eur
                linea = LineaDetalle(
                    descripcion=f"{sale.ticker} · {sale.date_sold.strftime('%d/%m/%Y')}",
                    importe_eur=gain_eur,
                    fuente=sale.source,
                    extras={
                        "ticker": f"{sale.ticker} (US)",
                        "fecha_venta": sale.date_sold.strftime("%d/%m/%Y"),
                        "fecha_vesting": sale.date_acquired.strftime("%d/%m/%Y"),
                        "cantidad": _fmt_qty(sale.quantity),
                        "coste_usd": _fmt_usd(sale.cost_basis_usd),
                        "ingresos_usd": _fmt_usd(sale.proceeds_usd),
                        "tipo_vesting": _fmt_rate(rate_acq),
                        "tipo_venta": _fmt_rate(rate_sold),
                        "coste_eur": _fmt_eur(cost_eur),
                        "ingresos_eur": _fmt_eur(proceeds_eur),
                        "ganancia_eur": _fmt_eur(gain_eur),
                        "tipo_accion": sale.stock_source,
                    },
                )
                grupos_data[sale.ticker]["coste"] += cost_eur
                grupos_data[sale.ticker]["ingresos"] += proceeds_eur

            desglose.append(linea)
            grupos_data[sale.ticker]["ops_with_date"].append((sale.date_sold, linea))

        grupos_data = {f"{k} (US)": v for k, v in grupos_data.items()}
        grupos_activo = _build_grupos_activo(grupos_data)
        valor = None if errores else (total_proceeds - total_cost).quantize(Decimal("0.01"))

        if errores:
            total_ganancias = None
            total_perdidas = None
        else:
            total_ganancias = sum(
                (l.importe_eur for l in desglose if l.importe_eur is not None and l.importe_eur > 0),
                Decimal("0"),
            ).quantize(Decimal("0.01"))
            total_perdidas = sum(
                (l.importe_eur for l in desglose if l.importe_eur is not None and l.importe_eur < 0),
                Decimal("0"),
            ).quantize(Decimal("0.01"))

        bce_warns = self._current_section_bce or []
        self._current_section_warns = None
        self._current_section_bce = None
        return Casilla(
            numero="0326-0340",
            nombre="Ganancias/pérdidas patrimoniales - Ventas de acciones",
            valor=valor,
            desglose=desglose,
            notas=(
                "Acciones RSU de Fidelity NetBenefits. El valor de adquisición (coste) "
                "se ha convertido al tipo BCE del día de vesting. El valor de transmisión "
                "(ingresos) se ha convertido al tipo BCE del día de venta.\n"
                "Para RSUs, el valor de adquisición fiscalmente correcto es el FMV en EUR "
                "a fecha de vesting, que es cuando tributaron como rendimiento del trabajo. "
                "Se ha utilizado el cost basis de Fidelity (FMV al vesting en USD) convertido "
                "al tipo BCE de esa fecha. Consulta con tu asesor fiscal."
            ),
            errores=errores,
            advertencias=_sec_warns,
            bce_warnings=bce_warns,
            template="_ventas_acciones.html",
            fuente="Fidelity",
            extras={
                "total_cost": total_cost.quantize(Decimal("0.01")),
                "total_proceeds": total_proceeds.quantize(Decimal("0.01")),
                "total_ganancias": total_ganancias,
                "total_perdidas": total_perdidas,
                "grupos_activo": grupos_activo,
            },
        )

    def _calc_doble_imposicion(self, withholdings: list[WithholdingEntry], year: int) -> Casilla:
        self._current_section_warns = []
        self._current_section_bce = []
        desglose = []
        total = Decimal("0")
        errores = []
        _sec_warns: list[str] = []
        activo = "ORCL / FYIXX (US)"
        grupos_data: dict = {}

        for wh in withholdings:
            if activo not in grupos_data:
                grupos_data[activo] = {"ops_with_date": [], "total": Decimal("0"), "tiene_errores": False, "tiene_avisos": False}
            tipo_str = "Retención" if wh.amount_usd < 0 else "Ajuste/devolución"

            if wh.date.year != year:
                aviso_msg = f"Operación fuera del año fiscal {year}"
                _sec_warns.append(
                    f"Retención del {wh.date.strftime('%d/%m/%Y')} excluida: no pertenece al año fiscal {year}"
                )
                linea = LineaDetalle(
                    descripcion=wh.date.strftime("%d/%m/%Y"),
                    importe_eur=None,
                    fuente=wh.source,
                    extras={
                        "activo": activo,
                        "fecha": wh.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(wh.amount_usd),
                        "tipo_cambio": "—",
                        "importe_eur": "—",
                        "tipo": tipo_str,
                    },
                    aviso=aviso_msg,
                )
                grupos_data[activo]["tiene_avisos"] = True
                desglose.append(linea)
                grupos_data[activo]["ops_with_date"].append((wh.date, linea))
                continue

            eur, rate, err = self._convert_usd(wh.amount_usd, wh.date)
            wh.amount_eur = eur
            wh.exchange_rate = rate

            if err:
                error_msg = f"No se pudo obtener el tipo de cambio: {err}"
                errores.append(f"{wh.date.strftime('%d/%m/%Y')} ({_fmt_usd(wh.amount_usd)}): {err}")
                linea = LineaDetalle(
                    descripcion=wh.date.strftime("%d/%m/%Y"),
                    importe_eur=None,
                    fuente=wh.source,
                    extras={
                        "activo": activo,
                        "fecha": wh.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(wh.amount_usd),
                        "tipo_cambio": "—",
                        "importe_eur": "—",
                        "tipo": tipo_str,
                    },
                    error=error_msg,
                )
                grupos_data[activo]["tiene_errores"] = True
            else:
                total += eur
                linea = LineaDetalle(
                    descripcion=wh.date.strftime("%d/%m/%Y"),
                    importe_eur=eur,
                    fuente=wh.source,
                    extras={
                        "activo": activo,
                        "fecha": wh.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(wh.amount_usd),
                        "tipo_cambio": _fmt_rate(rate),
                        "importe_eur": _fmt_eur(eur),
                        "tipo": tipo_str,
                    },
                )
                grupos_data[activo]["total"] += eur
            desglose.append(linea)
            grupos_data[activo]["ops_with_date"].append((wh.date, linea))

        if errores:
            valor = None
        else:
            valor = abs(total).quantize(Decimal("0.01"))

        bce_warns = self._current_section_bce or []
        self._current_section_warns = None
        self._current_section_bce = None
        return Casilla(
            numero="0588",
            nombre="Deducción por doble imposición internacional",
            valor=valor,
            desglose=desglose,
            notas=_NOTA_CASILLA_0588,
            errores=errores,
            advertencias=_sec_warns,
            bce_warnings=bce_warns,
            template="_retenciones.html",
            extras={"grupos_retenciones": _build_grupos_retenciones(grupos_data)},
            fuente="Fidelity",
        )

    def _calc_dividendos_degiro(self, dividends: list[DegiroDividend]) -> Casilla:
        """Dividendos DEGIRO ya en EUR (sin conversión de divisa)."""
        desglose = []
        total = Decimal("0")
        grupos_data: dict = {}

        for div in dividends:
            activo = f"{div.product} ({div.country})"
            if activo not in grupos_data:
                grupos_data[activo] = {"ops_with_date": [], "total": Decimal("0"), "tiene_errores": False}
            total += div.gross_eur
            linea = LineaDetalle(
                descripcion=activo,
                importe_eur=div.gross_eur,
                fuente=div.source,
                extras={
                    "activo": activo,
                    "fecha": "—",
                    "importe_usd": "—",
                    "tipo_cambio": "—",
                    "importe_eur": _fmt_eur(div.gross_eur),
                },
            )
            desglose.append(linea)
            grupos_data[activo]["total"] += div.gross_eur
            idx = len(grupos_data[activo]["ops_with_date"])
            grupos_data[activo]["ops_with_date"].append((idx, linea))

        return Casilla(
            numero="0029",
            nombre="Rendimientos del capital mobiliario - Dividendos",
            valor=total.quantize(Decimal("0.01")),
            desglose=desglose,
            notas=(
                "Dividendos de DEGIRO. Los importes ya están en EUR según el "
                "informe fiscal anual de DEGIRO."
            ),
            errores=[],
            template="_dividendos.html",
            extras={"grupos_dividendos": _build_grupos_dividendos(grupos_data)},
            fuente="DEGIRO",
        )

    def _calc_doble_imposicion_degiro(self, dividends: list[DegiroDividend]) -> Casilla:
        """Retenciones en origen de dividendos DEGIRO (ya en EUR)."""
        desglose = []
        total = Decimal("0")
        grupos_data: dict = {}

        for div in dividends:
            if div.withholding_eur == Decimal("0"):
                continue
            activo = f"{div.product} ({div.country})"
            if activo not in grupos_data:
                grupos_data[activo] = {"ops_with_date": [], "total": Decimal("0"), "tiene_errores": False}
            # withholding_eur es negativo (retención); mantener negativo en desglose
            total += div.withholding_eur
            linea = LineaDetalle(
                descripcion=activo,
                importe_eur=div.withholding_eur,
                fuente=div.source,
                extras={
                    "activo": activo,
                    "fecha": "—",
                    "tipo": "Retención en origen",
                    "importe_usd": "—",
                    "tipo_cambio": "—",
                    "importe_eur": _fmt_eur(div.withholding_eur),
                },
            )
            desglose.append(linea)
            grupos_data[activo]["total"] += div.withholding_eur
            idx = len(grupos_data[activo]["ops_with_date"])
            grupos_data[activo]["ops_with_date"].append((idx, linea))

        return Casilla(
            numero="0588",
            nombre="Deducción por doble imposición internacional",
            valor=abs(total).quantize(Decimal("0.01")),
            desglose=desglose,
            notas=_NOTA_CASILLA_0588,
            errores=[],
            template="_retenciones.html",
            extras={"grupos_retenciones": _build_grupos_retenciones(grupos_data)},
            fuente="DEGIRO",
        )

    def _calc_ganancias_degiro(self, sales: list[DegiroStockSale]) -> Casilla:
        """Ganancias/pérdidas de ventas DEGIRO (ya en EUR)."""
        desglose = []
        total_proceeds = Decimal("0")
        total_cost = Decimal("0")
        # isin -> {ops_with_date, coste, ingresos, tiene_errores}
        grupos_data: dict[str, dict[str, Any]] = {}

        for sale in sales:
            total_proceeds += sale.value_eur
            # Coste estimado = proceeds - gain_loss (el PDF no da coste directamente)
            cost_eur = sale.value_eur - sale.gain_loss_eur
            total_cost += cost_eur

            label = f"{sale.product} ({sale.symbol_isin[:2]})"
            if label not in grupos_data:
                grupos_data[label] = {
                    "ops_with_date": [],
                    "coste": Decimal("0"),
                    "ingresos": Decimal("0"),
                    "tiene_errores": False,
                }

            linea = LineaDetalle(
                descripcion=f"{sale.product} · {sale.date_sold.strftime('%d/%m/%Y')}",
                importe_eur=sale.gain_loss_eur,
                fuente=sale.source,
                extras={
                    "ticker": label,
                    "fecha_venta": sale.date_sold.strftime("%d/%m/%Y"),
                    "fecha_vesting": "—",
                    "cantidad": _fmt_qty(sale.quantity),
                    "coste_usd": "—",
                    "ingresos_usd": "—",
                    "tipo_vesting": "—",
                    "tipo_venta": _fmt_rate(sale.exchange_rate),
                    "coste_eur": _fmt_eur(cost_eur),
                    "ingresos_eur": _fmt_eur(sale.value_eur),
                    "ganancia_eur": _fmt_eur(sale.gain_loss_eur),
                    "tipo_accion": "DEGIRO",
                },
            )
            grupos_data[label]["coste"] += cost_eur
            grupos_data[label]["ingresos"] += sale.value_eur
            desglose.append(linea)
            grupos_data[label]["ops_with_date"].append((sale.date_sold, linea))

        grupos_activo = _build_grupos_activo(grupos_data)
        total_gain = sum(s.gain_loss_eur for s in sales) if sales else Decimal("0")
        total_ganancias = sum(
            (l.importe_eur for l in desglose if l.importe_eur is not None and l.importe_eur > 0),
            Decimal("0"),
        ).quantize(Decimal("0.01"))
        total_perdidas = sum(
            (l.importe_eur for l in desglose if l.importe_eur is not None and l.importe_eur < 0),
            Decimal("0"),
        ).quantize(Decimal("0.01"))

        return Casilla(
            numero="0326-0340",
            nombre="Ganancias/pérdidas patrimoniales - Ventas de acciones",
            valor=total_gain.quantize(Decimal("0.01")),
            desglose=desglose,
            notas=(
                "Ventas de acciones DEGIRO. Los importes ya están en EUR según el "
                "informe fiscal anual de DEGIRO.\n"
                "El coste de adquisición mostrado es una estimación (ingresos − "
                "ganancia/pérdida según DEGIRO). Verifica el coste real con los "
                "extractos de compra. Consulta con tu asesor fiscal."
            ),
            errores=[],
            template="_ventas_acciones.html",
            fuente="DEGIRO",
            extras={
                "total_cost": total_cost.quantize(Decimal("0.01")),
                "total_proceeds": total_proceeds.quantize(Decimal("0.01")),
                "total_ganancias": total_ganancias,
                "total_perdidas": total_perdidas,
                "grupos_activo": grupos_activo,
            },
        )

    def _calc_ganancias_crypto(
        self,
        gains: list[CryptoCapitalGain],
        asset_summary: dict | None = None,
        asset_totals_official: dict | None = None,
        summary_costs_eur: Decimal | None = None,
    ) -> Casilla:
        desglose = []
        total_proceeds = Decimal("0")
        total_cost = Decimal("0")
        grupos_data: dict[str, dict[str, Any]] = {}

        for g in gains:
            total_proceeds += g.proceeds_eur
            total_cost += g.cost_eur
            gain = g.gain_loss_eur

            if g.asset not in grupos_data:
                grupos_data[g.asset] = {
                    "ops_with_date": [],
                    "coste": Decimal("0"),
                    "ingresos": Decimal("0"),
                    "tiene_errores": False,
                    "wallets": set(),
                }

            linea = LineaDetalle(
                descripcion=f"{g.asset} · {g.date_sold.strftime('%d/%m/%Y')}",
                importe_eur=gain,
                fuente=g.source,
                extras={
                    "activo": g.asset,
                    "fecha_venta": g.date_sold.strftime("%d/%m/%Y"),
                    "fecha_adquisicion": g.date_acquired.strftime("%d/%m/%Y"),
                    "cantidad": _fmt_qty(g.quantity),
                    "coste_eur": _fmt_eur(g.cost_eur),
                    "ingresos_eur": _fmt_eur(g.proceeds_eur),
                    "ganancia_eur": _fmt_eur(gain),
                    "wallet": g.wallet,
                    "notas": g.notes,
                },
            )
            grupos_data[g.asset]["coste"] += g.cost_eur
            grupos_data[g.asset]["ingresos"] += g.proceeds_eur
            grupos_data[g.asset]["wallets"].add(g.wallet)
            grupos_data[g.asset]["ops_with_date"].append((g.date_sold, linea))
            desglose.append(linea)

        grupos_activo = _build_grupos_activo(grupos_data)
        for grupo in grupos_activo:
            asset = grupo["ticker"]
            grupo["wallets"] = sorted(grupos_data[asset]["wallets"])
            # Si el PDF tiene resumen oficial de ganancias/pérdidas para este activo, usarlo
            if asset_summary and asset in asset_summary:
                pdf = asset_summary[asset]
                grupo["ganancias_activo"] = pdf["ganancias"].quantize(Decimal("0.01"))
                grupo["perdidas_activo"] = (-pdf["perdidas"]).quantize(Decimal("0.01"))
            # Si el Spain report tiene totales oficiales de coste/ingresos, sobrescribir
            if asset_totals_official and asset in asset_totals_official:
                oficial = asset_totals_official[asset]
                grupo["total_coste_eur"] = oficial["valor_eur"].quantize(Decimal("0.01"))
                grupo["total_ingresos_eur"] = oficial["ingresos_eur"].quantize(Decimal("0.01"))
                grupo["total_ganancia_eur"] = (
                    grupo["total_ingresos_eur"] - grupo["total_coste_eur"]
                )

        # Totales a nivel casilla: sumar oficial por activo cuando disponible, si no el calculado
        agg_cost = Decimal("0")
        agg_proceeds = Decimal("0")
        for grupo in grupos_activo:
            if asset_totals_official and grupo["ticker"] in asset_totals_official:
                agg_cost += grupo["total_coste_eur"] or Decimal("0")
                agg_proceeds += grupo["total_ingresos_eur"] or Decimal("0")
            else:
                agg_cost += grupos_data[grupo["ticker"]]["coste"]
                agg_proceeds += grupos_data[grupo["ticker"]]["ingresos"]
        agg_cost = agg_cost.quantize(Decimal("0.01"))
        agg_proceeds = agg_proceeds.quantize(Decimal("0.01"))
        total_gain = (agg_proceeds - agg_cost).quantize(Decimal("0.01"))

        total_ganancias = sum(
            (g["ganancias_activo"] for g in grupos_activo if g["ganancias_activo"] is not None),
            Decimal("0"),
        ).quantize(Decimal("0.01"))
        total_perdidas = sum(
            (g["perdidas_activo"] for g in grupos_activo if g["perdidas_activo"] is not None),
            Decimal("0"),
        ).quantize(Decimal("0.01"))

        _notas_crypto = [{"fuente": "Koinly", "notas": (
            "Ganancias de criptomonedas según informe Koinly (método FIFO). "
            "Todos los valores ya están en EUR según Koinly. "
            "Los fees de compra/venta ya están incluidos en las operaciones "
            "(como parte del coste de adquisición o del ingreso de venta) y no se declaran por separado."
        )}]
        if summary_costs_eur is not None:
            _notas_crypto.append({"fuente": "Koinly (gastos)", "notas": (
                f"Total de gastos según el «Resumen de gastos» del reporte de Koinly: "
                f"{_fmt_eur(summary_costs_eur)}. "
                "Estos gastos no están incluidos en las ganancias patrimoniales y podrían ser deducibles "
                "en otro apartado de la declaración. Consulta con tu asesor fiscal."
            )})

        return Casilla(
            numero="1800-1814",
            nombre="Ganancias/pérdidas patrimoniales - Venta de cryptos",
            valor=total_gain,
            desglose=desglose,
            fuente="Koinly",
            notas_secciones=_notas_crypto,
            advertencias=[
                "Verifica la exactitud del informe Koinly antes de usar estos datos. "
                "Otros costes (p. ej. comisiones por transferir dinero a exchanges) tienen un tratamiento "
                "fiscal poco claro; consulta con tu asesor fiscal si la cantidad es significativa. "
                "Para el detalle de costes, revisa el reporte completo de Koinly."
            ],
            template="_ganancias_crypto.html",
            extras={
                "total_cost": agg_cost,
                "total_proceeds": agg_proceeds,
                "total_ganancias": total_ganancias,
                "total_perdidas": total_perdidas,
                "grupos_activo": grupos_activo,
                "total_costes_koinly": summary_costs_eur,
            },
        )

    def _calc_rendimientos_crypto(self, koinly: KoinlyData) -> Casilla:
        rewards = koinly.rewards
        by_asset: dict[str, Decimal] = {}
        desglose = []

        for r in rewards:
            by_asset[r.asset] = by_asset.get(r.asset, Decimal("0")) + r.price_eur

        for asset, total_asset in sorted(by_asset.items()):
            desglose.append(LineaDetalle(
                descripcion=f"Staking rewards {asset}",
                importe_eur=total_asset.quantize(Decimal("0.01")),
                extras={
                    "activo": asset,
                    "total_eur": _fmt_eur(total_asset),
                    "num_operaciones": str(sum(1 for r in rewards if r.asset == asset)),
                },
            ))

        suma_filas = sum((r.price_eur for r in rewards), Decimal("0")).quantize(Decimal("0.01"))
        total_ops = len(rewards)

        if koinly.summary_rewards_eur is not None:
            total = koinly.summary_rewards_eur.quantize(Decimal("0.01"))
        else:
            total = suma_filas

        return Casilla(
            numero="0033",
            nombre="Rendimientos de capital mobiliario - Staking/Rewards crypto",
            valor=total,
            desglose=desglose,
            fuente="Koinly",
            notas_secciones=[{"fuente": "Koinly", "notas": (
                "Rendimientos de staking y recompensas de criptomonedas según informe Koinly. "
                "La calificación fiscal de estos rendimientos en España no está completamente clara. "
                "Consulta con tu asesor fiscal si deben declararse como rendimientos del capital "
                "mobiliario u otro tipo de renta."
            )}],
            template="_rendimientos_crypto.html",
            extras={
                "rewards": rewards,
                "total_ops": total_ops,
                "total_filas": suma_filas,
                "total_pdf": koinly.summary_rewards_eur,
            },
        )

    def _calc_airdrops_crypto(self, koinly: KoinlyData) -> Casilla:
        airdrops = koinly.airdrops
        by_asset: dict[str, Decimal] = {}
        desglose = []

        for a in airdrops:
            by_asset[a.asset] = by_asset.get(a.asset, Decimal("0")) + a.price_eur

        for asset, total_asset in sorted(by_asset.items()):
            desglose.append(LineaDetalle(
                descripcion=f"Airdrops {asset}",
                importe_eur=total_asset.quantize(Decimal("0.01")),
                extras={
                    "activo": asset,
                    "total_eur": _fmt_eur(total_asset),
                    "num_operaciones": str(sum(1 for a in airdrops if a.asset == asset)),
                },
            ))

        suma_filas = sum((a.price_eur for a in airdrops), Decimal("0")).quantize(Decimal("0.01"))
        total_ops = len(airdrops)

        if koinly.summary_airdrops_eur is not None:
            total = koinly.summary_airdrops_eur.quantize(Decimal("0.01"))
        else:
            total = suma_filas

        return Casilla(
            numero="0034",
            nombre="Rendimientos de capital mobiliario - Airdrops crypto",
            valor=total,
            desglose=desglose,
            fuente="Koinly",
            notas_secciones=[{"fuente": "Koinly", "notas": (
                "Airdrops de criptomonedas según informe Koinly. "
                "La calificación fiscal de los airdrops en España puede variar en función de su origen y condiciones. "
                "Consulta con tu asesor fiscal si deben declararse como rendimientos del capital mobiliario, "
                "ganancia patrimonial u otro tipo de renta."
            )}],
            template="_airdrops_crypto.html",
            extras={
                "airdrops": airdrops,
                "total_ops": total_ops,
                "total_filas": suma_filas,
                "total_pdf": koinly.summary_airdrops_eur,
            },
        )
