"""
Calculadora fiscal: convierte los datos parseados a casillas del modelo 100.

Reglas aplicadas:
- Dividendos: convertir USD a EUR al tipo BCE de la fecha del dividendo → casilla 0029
- Ventas de acciones (RSUs):
    · Cost basis convertido al tipo BCE de la fecha de VESTING (date acquired)
    · Proceeds convertidos al tipo BCE de la fecha de VENTA (date sold)
    → casillas 0328-0337 (ganancias patrimoniales)
- Retenciones EEUU (nonresident alien withholding):
    · Sumar todos los importes (negativos = retención, positivos = ajuste/devolución)
    · El neto es la deducción por doble imposición internacional → casillas 0588-0589
    · NOTA: la deducción está limitada al tipo medio efectivo español sobre esas rentas
- Ganancias crypto: ya en EUR, directo → casillas 0328-0337
- Rewards staking: ya en EUR, sumar total → rendimientos del capital mobiliario

Si no se puede obtener el tipo de cambio para una fecha, la fila se marca con error
y se excluye del total. El total de la casilla se marca como None si hay errores.
NUNCA se usa un tipo de cambio ficticio (como 1:1) para producir un valor incorrecto.
"""

from decimal import Decimal
from typing import Any

from renta.exchange import ExchangeRateProvider
from renta.models import (
    Casilla,
    CryptoCapitalGain,
    CryptoReward,
    DegiroData,
    DegiroDividend,
    DegiroStockSale,
    DividendEntry,
    FidelityData,
    KoinlyData,
    LineaDetalle,
    ResultadoRenta,
    StockSale,
    WithholdingEntry,
)


def _fmt_eur(amount: Decimal) -> str:
    return f"{amount:,.2f}€"


def _fmt_usd(amount: Decimal) -> str:
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return f"${amount:,.2f}"


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
        else:
            total_coste_eur = gd["coste"].quantize(Decimal("0.01"))
            total_ingresos_eur = gd["ingresos"].quantize(Decimal("0.01"))
            total_ganancia_eur = (total_ingresos_eur - total_coste_eur)
        grupos_activo.append({
            "ticker": ticker,
            "operaciones": ops_sorted,
            "total_coste_eur": total_coste_eur,
            "total_ingresos_eur": total_ingresos_eur,
            "total_ganancia_eur": total_ganancia_eur,
            "num_ops": len(ops_sorted),
            "tiene_errores": gd["tiene_errores"],
        })
    return grupos_activo


class Calculator:
    def __init__(self, rates: ExchangeRateProvider):
        self.rates = rates
        self._rates_used: dict = {}
        self._warnings: list[str] = []

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
                self._warnings.append(
                    f"Tipo de cambio para {on_date} no disponible ({motivo}), "
                    f"usando el de {eff} ({rate})"
                )
            return eur, rate, None
        except ValueError as e:
            msg = str(e)
            self._warnings.append(f"ERROR tipo de cambio: {msg}")
            return None, None, msg

    def calculate(
        self,
        parsed_data: dict[str, Any],
        year: int,
    ) -> ResultadoRenta:
        fidelity = parsed_data.get("fidelity", FidelityData())
        koinly = parsed_data.get("koinly", KoinlyData())
        degiro = parsed_data.get("degiro", DegiroData())

        result = ResultadoRenta(year=year)

        result.dividendos = self._merge_casillas(
            self._calc_dividendos(fidelity.dividends),
            self._calc_dividendos_degiro(degiro.dividends),
        )
        result.ganancias_acciones = self._merge_casillas(
            self._calc_ganancias_acciones(fidelity.stock_sales),
            self._calc_ganancias_degiro(degiro.stock_sales),
        )
        result.doble_imposicion = self._merge_casillas(
            self._calc_doble_imposicion(fidelity.withholdings),
            self._calc_doble_imposicion_degiro(degiro.dividends),
        )
        result.ganancias_crypto = self._calc_ganancias_crypto(koinly.capital_gains)
        result.rendimientos_crypto = self._calc_rendimientos_crypto(koinly.rewards)

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
            if c.notas:
                merged_notas_parts.append(c.notas)

        # Combinar extras (total_cost, total_proceeds) sumando si existen
        merged_extras: dict = {}
        for key in ("total_cost", "total_proceeds"):
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

        base = non_empty[0]
        return Casilla(
            numero=base.numero,
            nombre=base.nombre,
            valor=merged_valor,
            desglose=merged_desglose,
            notas="\n\n".join(merged_notas_parts),
            errores=merged_errores,
            template=base.template,
            extras=merged_extras,
        )

    def _calc_dividendos(self, dividends: list[DividendEntry]) -> Casilla:
        desglose = []
        total = Decimal("0")
        errores = []

        for div in dividends:
            eur, rate, err = self._convert_usd(div.amount_usd, div.date)
            div.amount_eur = eur
            div.exchange_rate = rate

            if err:
                error_msg = f"{div.date.strftime('%d/%m/%Y')} ({_fmt_usd(div.amount_usd)}): {err}"
                errores.append(error_msg)
                desglose.append(LineaDetalle(
                    descripcion=str(div.date),
                    importe_eur=None,
                    fuente=div.source,
                    extras={
                        "activo": "ORCL / FYIXX (US)",
                        "fecha": div.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(div.amount_usd),
                        "tipo_cambio": "—",
                        "importe_eur": "—",
                    },
                    error=err,
                ))
            else:
                total += eur
                desglose.append(LineaDetalle(
                    descripcion=str(div.date),
                    importe_eur=eur,
                    fuente=div.source,
                    extras={
                        "activo": "ORCL / FYIXX (US)",
                        "fecha": div.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(div.amount_usd),
                        "tipo_cambio": str(rate),
                        "importe_eur": _fmt_eur(eur),
                    },
                ))

        valor = None if errores else total.quantize(Decimal("0.01"))

        return Casilla(
            numero="0029",
            nombre="Dividendos - Rendimientos del capital mobiliario",
            valor=valor,
            desglose=desglose,
            notas=(
                "Los dividendos de acciones USA tributan como rendimientos del capital "
                "mobiliario. Cada importe se ha convertido al tipo de cambio BCE del "
                "día del dividendo."
            ),
            errores=errores,
            template="_dividendos.html",
        )

    def _calc_ganancias_acciones(self, sales: list[StockSale]) -> Casilla:
        desglose = []
        total_proceeds = Decimal("0")
        total_cost = Decimal("0")
        errores = []
        # ticker -> {ops_with_date, coste, ingresos, tiene_errores}
        grupos_data: dict[str, dict[str, Any]] = {}

        for sale in sales:
            cost_eur, rate_acq, err_acq = self._convert_usd(sale.cost_basis_usd, sale.date_acquired)
            proceeds_eur, rate_sold, err_sold = self._convert_usd(sale.proceeds_usd, sale.date_sold)

            err = err_acq or err_sold

            if sale.ticker not in grupos_data:
                grupos_data[sale.ticker] = {
                    "ops_with_date": [],
                    "coste": Decimal("0"),
                    "ingresos": Decimal("0"),
                    "tiene_errores": False,
                }

            if err:
                error_msg = (
                    f"{sale.ticker} vendido {sale.date_sold.strftime('%d/%m/%Y')}: "
                    + (f"tipo vesting ({sale.date_acquired}): {err_acq}" if err_acq else "")
                    + (f"tipo venta ({sale.date_sold}): {err_sold}" if err_sold else "")
                )
                errores.append(error_msg)
                sale.cost_basis_eur = None
                sale.proceeds_eur = None
                sale.gain_loss_eur = None
                linea: LineaDetalle = LineaDetalle(
                    descripcion=f"{sale.ticker} · {sale.date_sold}",
                    importe_eur=None,
                    fuente=sale.source,
                    extras={
                        "ticker": f"{sale.ticker} (US)",
                        "fecha_venta": sale.date_sold.strftime("%d/%m/%Y"),
                        "fecha_vesting": sale.date_acquired.strftime("%d/%m/%Y"),
                        "cantidad": str(sale.quantity),
                        "coste_usd": _fmt_usd(sale.cost_basis_usd),
                        "ingresos_usd": _fmt_usd(sale.proceeds_usd),
                        "tipo_vesting": "—",
                        "tipo_venta": "—",
                        "coste_eur": "—",
                        "ingresos_eur": "—",
                        "ganancia_eur": "—",
                        "tipo_accion": sale.stock_source,
                    },
                    error=err,
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
                    descripcion=f"{sale.ticker} · {sale.date_sold}",
                    importe_eur=gain_eur,
                    fuente=sale.source,
                    extras={
                        "ticker": f"{sale.ticker} (US)",
                        "fecha_venta": sale.date_sold.strftime("%d/%m/%Y"),
                        "fecha_vesting": sale.date_acquired.strftime("%d/%m/%Y"),
                        "cantidad": str(sale.quantity),
                        "coste_usd": _fmt_usd(sale.cost_basis_usd),
                        "ingresos_usd": _fmt_usd(sale.proceeds_usd),
                        "tipo_vesting": str(rate_acq),
                        "tipo_venta": str(rate_sold),
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

        return Casilla(
            numero="0328-0337",
            nombre="Ganancias/pérdidas patrimoniales - Ventas de acciones (RSUs)",
            valor=valor,
            desglose=desglose,
            notas=(
                "Acciones RSU de Fidelity NetBenefits. El valor de adquisición (coste) "
                "se ha convertido al tipo BCE del día de vesting. El valor de transmisión "
                "(ingresos) se ha convertido al tipo BCE del día de venta.\n"
                "AVISO: Para RSUs, el valor de adquisición fiscalmente correcto es el FMV "
                "en EUR a fecha de vesting, que es cuando tributaron como rendimiento del "
                "trabajo. Se ha utilizado el cost basis de Fidelity (FMV al vesting en USD) "
                "convertido al tipo BCE de esa fecha. Verifique con su asesor fiscal."
            ),
            errores=errores,
            template="_ventas_acciones.html",
            extras={
                "total_cost": total_cost.quantize(Decimal("0.01")),
                "total_proceeds": total_proceeds.quantize(Decimal("0.01")),
                "grupos_activo": grupos_activo,
            },
        )

    def _calc_doble_imposicion(self, withholdings: list[WithholdingEntry]) -> Casilla:
        desglose = []
        total = Decimal("0")
        errores = []

        for wh in withholdings:
            eur, rate, err = self._convert_usd(wh.amount_usd, wh.date)
            wh.amount_eur = eur
            wh.exchange_rate = rate

            if err:
                error_msg = f"{wh.date.strftime('%d/%m/%Y')} ({_fmt_usd(wh.amount_usd)}): {err}"
                errores.append(error_msg)
                desglose.append(LineaDetalle(
                    descripcion=str(wh.date),
                    importe_eur=None,
                    fuente=wh.source,
                    extras={
                        "activo": "ORCL / FYIXX (US)",
                        "fecha": wh.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(wh.amount_usd),
                        "tipo_cambio": "—",
                        "importe_eur": "—",
                        "tipo": "Retención" if wh.amount_usd < 0 else "Ajuste/devolución",
                    },
                    error=err,
                ))
            else:
                total += eur
                desglose.append(LineaDetalle(
                    descripcion=str(wh.date),
                    importe_eur=eur,
                    fuente=wh.source,
                    extras={
                        "activo": "ORCL / FYIXX (US)",
                        "fecha": wh.date.strftime("%d/%m/%Y"),
                        "importe_usd": _fmt_usd(wh.amount_usd),
                        "tipo_cambio": str(rate),
                        "importe_eur": _fmt_eur(eur),
                        "tipo": "Retención" if wh.amount_usd < 0 else "Ajuste/devolución",
                    },
                ))

        if errores:
            valor = None
            notas_neto = ""
        else:
            valor = abs(total).quantize(Decimal("0.01"))
            notas_neto = f"Retenciones netas en EEUU sobre dividendos: {_fmt_eur(total)} (negativo = retención, positivo = ajuste/devolución).\n"

        return Casilla(
            numero="0588-0589",
            nombre="Deducción por doble imposición internacional",
            valor=valor,
            desglose=desglose,
            notas=(
                notas_neto
                + "La deducción aplicable es el MENOR de: (a) impuesto efectivamente "
                "pagado en EEUU, o (b) tipo medio efectivo español aplicado a esas rentas. "
                "Este cálculo muestra solo (a). Consulte el límite con su asesor fiscal."
            ),
            errores=errores,
            template="_retenciones.html",
        )

    def _calc_dividendos_degiro(self, dividends: list[DegiroDividend]) -> Casilla:
        """Dividendos DEGIRO ya en EUR (sin conversión de divisa)."""
        desglose = []
        total = Decimal("0")

        for div in dividends:
            total += div.gross_eur
            desglose.append(LineaDetalle(
                descripcion=f"{div.product} ({div.country})",
                importe_eur=div.gross_eur,
                fuente=div.source,
                extras={
                    "activo": f"{div.product} ({div.country})",
                    "fecha": "—",
                    "importe_usd": "—",
                    "tipo_cambio": "—",
                    "importe_eur": _fmt_eur(div.gross_eur),
                },
            ))

        return Casilla(
            numero="0029",
            nombre="Dividendos - Rendimientos del capital mobiliario",
            valor=total.quantize(Decimal("0.01")),
            desglose=desglose,
            notas=(
                "Dividendos de DEGIRO. Los importes ya están en EUR según el "
                "informe fiscal anual de DEGIRO."
            ),
            errores=[],
            template="_dividendos.html",
        )

    def _calc_doble_imposicion_degiro(self, dividends: list[DegiroDividend]) -> Casilla:
        """Retenciones en origen de dividendos DEGIRO (ya en EUR)."""
        desglose = []
        total = Decimal("0")

        for div in dividends:
            if div.withholding_eur == Decimal("0"):
                continue
            # withholding_eur es negativo (retención); mantener negativo en desglose
            total += div.withholding_eur
            desglose.append(LineaDetalle(
                descripcion=f"{div.product} ({div.country})",
                importe_eur=div.withholding_eur,
                fuente=div.source,
                extras={
                    "activo": f"{div.product} ({div.country})",
                    "fecha": "—",
                    "tipo": "Retención en origen",
                    "importe_usd": "—",
                    "tipo_cambio": "—",
                    "importe_eur": _fmt_eur(div.withholding_eur),
                },
            ))

        return Casilla(
            numero="0588-0589",
            nombre="Deducción por doble imposición internacional",
            valor=abs(total).quantize(Decimal("0.01")),
            desglose=desglose,
            notas=(
                "Retenciones en origen sobre dividendos DEGIRO. Los importes ya "
                "están en EUR según el informe fiscal anual de DEGIRO.\n"
                "La deducción aplicable es el MENOR de: (a) impuesto efectivamente "
                "pagado en origen, o (b) tipo medio efectivo español aplicado a esas "
                "rentas. Consulte el límite con su asesor fiscal."
            ),
            errores=[],
            template="_retenciones.html",
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
                    "cantidad": str(sale.quantity),
                    "coste_usd": "—",
                    "ingresos_usd": "—",
                    "tipo_vesting": "—",
                    "tipo_venta": str(sale.exchange_rate),
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

        return Casilla(
            numero="0328-0337",
            nombre="Ganancias/pérdidas patrimoniales - Ventas de acciones (RSUs)",
            valor=total_gain.quantize(Decimal("0.01")),
            desglose=desglose,
            notas=(
                "Ventas de acciones DEGIRO. Los importes ya están en EUR según el "
                "informe fiscal anual de DEGIRO.\n"
                "AVISO: El coste de adquisición mostrado es una estimación (ingresos - "
                "ganancia/pérdida según DEGIRO). Verifique el coste real con los "
                "extractos de compra y consulte a su asesor fiscal."
            ),
            errores=[],
            template="_ventas_acciones.html",
            extras={
                "total_cost": total_cost.quantize(Decimal("0.01")),
                "total_proceeds": total_proceeds.quantize(Decimal("0.01")),
                "grupos_activo": grupos_activo,
            },
        )

    def _calc_ganancias_crypto(self, gains: list[CryptoCapitalGain]) -> Casilla:
        desglose = []
        total_proceeds = Decimal("0")
        total_cost = Decimal("0")

        for g in gains:
            total_proceeds += g.proceeds_eur
            total_cost += g.cost_eur
            gain = g.gain_loss_eur

            desglose.append(LineaDetalle(
                descripcion=f"{g.asset} · {g.date_sold.strftime('%d/%m/%Y')}",
                importe_eur=gain,
                fuente=g.source,
                extras={
                    "activo": g.asset,
                    "fecha_venta": g.date_sold.strftime("%d/%m/%Y %H:%M"),
                    "fecha_adquisicion": g.date_acquired.strftime("%d/%m/%Y %H:%M"),
                    "cantidad": str(g.quantity),
                    "coste_eur": _fmt_eur(g.cost_eur),
                    "ingresos_eur": _fmt_eur(g.proceeds_eur),
                    "ganancia_eur": _fmt_eur(gain),
                    "wallet": g.wallet,
                    "notas": g.notes,
                },
            ))

        total_gain = (total_proceeds - total_cost).quantize(Decimal("0.01"))

        return Casilla(
            numero="0328-0337",
            nombre="Ganancias/pérdidas patrimoniales - Criptomonedas",
            valor=total_gain,
            desglose=desglose,
            notas=(
                "Ganancias de criptomonedas según informe Koinly (método FIFO). "
                "Todos los valores ya están en EUR según Koinly. "
                "Verifique la exactitud del informe Koinly antes de usar estos datos."
            ),
            template="_ganancias_crypto.html",
        )

    def _calc_rendimientos_crypto(self, rewards: list[CryptoReward]) -> Casilla:
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

        total = sum((r.price_eur for r in rewards), Decimal("0")).quantize(Decimal("0.01"))
        total_ops = len(rewards)

        return Casilla(
            numero="Rend. cap. mob.",
            nombre="Rendimientos de capital mobiliario - Staking/Rewards crypto",
            valor=total,
            desglose=desglose,
            notas=(
                "Rendimientos de staking y recompensas de criptomonedas según informe Koinly. "
                "La calificación fiscal de estos rendimientos en España no está completamente "
                "clara. Consulte con su asesor fiscal si deben declararse como rendimientos "
                "del capital mobiliario u otro tipo de renta."
            ),
            template="_rendimientos_crypto.html",
            extras={
                "rewards": rewards,
                "total_ops": total_ops,
            },
        )
