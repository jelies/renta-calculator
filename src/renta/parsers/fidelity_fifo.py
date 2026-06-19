"""
Cálculo FIFO de ganancias/pérdidas por venta de acciones de Fidelity.

Modo alternativo al cálculo por lotes del bróker (activable con --fidelity-fifo).
Se alimenta de un CSV "ledger" mantenido por el usuario: una fila por evento
(adquisición o venta), por ticker. El programa reconstruye el inventario FIFO
(art. 37.2 LIRPF para valores homogéneos) desde el origen y emite, para el año
fiscal indicado, una operación (StockSale) por cada lote consumido en cada venta
("fragmento").

Formato del CSV (cabeceras obligatorias):

    fecha,ticker,tipo,cantidad,precio_usd

- fecha:      YYYY-MM-DD
- ticker:     símbolo (FIFO se aplica por ticker, valores homogéneos)
- tipo:       adquisicion | venta
- cantidad:   nº de acciones
- precio_usd: precio por acción en USD (FMV/acción al vesting; precio recibido en venta)

Las líneas en blanco y las que empiezan por '#' se ignoran.

Reglas (CLAUDE.md): nunca se inventan datos. Si el CSV tiene datos inválidos, o una
venta no tiene inventario FIFO suficiente, se marca como error y no se calcula.
"""

import csv
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from renta.models import SourceRef, StockSale


_HEADERS = ["fecha", "ticker", "tipo", "cantidad", "precio_usd"]
_TIPO_ADQUISICION = {"adquisicion", "adquisición", "compra", "vesting"}
_TIPO_VENTA = {"venta"}
_STOCK_SOURCE_DEFAULT = "RS"  # RSU; el ledger no distingue clase de acción


@dataclass
class LedgerEntry:
    fecha: date
    ticker: str
    tipo: str  # "adquisicion" | "venta" (normalizado)
    cantidad: Decimal
    precio_usd: Decimal
    row: int  # nº de línea en el CSV (1-based) para trazabilidad


def parse_ledger(csv_path) -> list[LedgerEntry]:
    """Lee y valida el CSV ledger. Falla con mensaje claro ante datos inválidos."""
    path = Path(csv_path)
    if not path.is_file():
        raise ValueError(f"No se encontró el fichero CSV de lotes: {path}")

    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    # Filtrar comentarios y líneas en blanco, conservando el nº de línea original.
    indexed = [
        (i + 1, line)
        for i, line in enumerate(raw_lines)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not indexed:
        raise ValueError(f"El CSV de lotes está vacío: {path}")

    rows = list(csv.reader([line for _, line in indexed]))

    header = [h.strip().lower() for h in rows[0]]
    if header != _HEADERS:
        raise ValueError(
            f"Cabeceras del CSV inválidas en {path}. "
            f"Esperado: {','.join(_HEADERS)}. Encontrado: {','.join(rows[0])}"
        )

    entries: list[LedgerEntry] = []
    for (line_no, _), values in zip(indexed[1:], rows[1:]):
        if len(values) != len(_HEADERS):
            raise ValueError(
                f"Línea {line_no} del CSV: se esperaban {len(_HEADERS)} columnas, "
                f"se encontraron {len(values)}: {values}"
            )
        fecha_s, ticker_s, tipo_s, cantidad_s, precio_s = (v.strip() for v in values)

        try:
            fecha = datetime.strptime(fecha_s, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(
                f"Línea {line_no} del CSV: fecha inválida '{fecha_s}' (formato esperado YYYY-MM-DD)"
            )

        ticker = ticker_s.upper()
        if not ticker:
            raise ValueError(f"Línea {line_no} del CSV: ticker vacío")

        tipo_norm = tipo_s.lower()
        if tipo_norm in _TIPO_ADQUISICION:
            tipo = "adquisicion"
        elif tipo_norm in _TIPO_VENTA:
            tipo = "venta"
        else:
            raise ValueError(
                f"Línea {line_no} del CSV: tipo inválido '{tipo_s}' (usa 'adquisicion' o 'venta')"
            )

        try:
            cantidad = Decimal(cantidad_s)
            precio_usd = Decimal(precio_s)
        except InvalidOperation:
            raise ValueError(
                f"Línea {line_no} del CSV: cantidad o precio_usd no numéricos "
                f"('{cantidad_s}', '{precio_s}')"
            )
        if cantidad <= 0:
            raise ValueError(f"Línea {line_no} del CSV: cantidad debe ser > 0 (es {cantidad})")
        if precio_usd < 0:
            raise ValueError(
                f"Línea {line_no} del CSV: precio_usd no puede ser negativo (es {precio_usd})"
            )

        entries.append(LedgerEntry(
            fecha=fecha,
            ticker=ticker,
            tipo=tipo,
            cantidad=cantidad,
            precio_usd=precio_usd,
            row=line_no,
        ))

    return entries


def compute_fifo(
    entries: list[LedgerEntry],
    year: int,
    csv_file: str = "",
) -> tuple[list[StockSale], list[str]]:
    """
    Reconstruye el inventario FIFO por ticker y devuelve (fragmentos, errores).

    - fragmentos: list[StockSale], una por cada lote consumido en las ventas del
      año fiscal `year`. Las ventas de otros años solo consumen inventario.
    - errores: list[str], ventas del año fiscal sin inventario FIFO suficiente
      (no calculables). No se emiten fragmentos para ellas ni se inventa coste.
    """
    fragments: list[StockSale] = []
    errores: list[str] = []

    by_ticker: dict[str, list[LedgerEntry]] = {}
    for e in entries:
        by_ticker.setdefault(e.ticker, []).append(e)

    for ticker in sorted(by_ticker):
        # Orden cronológico; en empate de fecha, adquisiciones antes que ventas.
        eventos_orden = sorted(
            enumerate(by_ticker[ticker]),
            key=lambda ie: (ie[1].fecha, 0 if ie[1].tipo == "adquisicion" else 1, ie[0]),
        )
        lotes: deque = deque()  # cada lote: [fecha, restante, precio]
        for _, ev in eventos_orden:
            if ev.tipo == "adquisicion":
                lotes.append([ev.fecha, ev.cantidad, ev.precio_usd])
                continue

            # Venta: consumir lotes más antiguos primero (FIFO).
            restante = ev.cantidad
            consumos: list[tuple[date, Decimal, Decimal]] = []  # (fecha_lote, cantidad, precio_lote)
            while restante > 0 and lotes:
                lote = lotes[0]
                usar = lote[1] if lote[1] <= restante else restante
                consumos.append((lote[0], usar, lote[2]))
                lote[1] -= usar
                restante -= usar
                if lote[1] == 0:
                    lotes.popleft()

            es_year = ev.fecha.year == year

            if restante > 0:
                # Inventario insuficiente: no se inventa coste (regla CLAUDE.md).
                if es_year:
                    errores.append(
                        f"{ticker} vendido {ev.fecha.strftime('%d/%m/%Y')} (línea {ev.row}): "
                        f"inventario FIFO insuficiente, faltan {restante} acciones. "
                        f"Revisa el CSV de lotes."
                    )
                # No se emiten fragmentos de una venta incompleta (evita un cálculo parcial).
                continue

            if not es_year:
                continue  # ventas de otros años: solo consumen inventario

            for fecha_lote, cantidad, precio_lote in consumos:
                cost_usd = cantidad * precio_lote
                proceeds_usd = cantidad * ev.precio_usd
                fragments.append(StockSale(
                    date_sold=ev.fecha,
                    date_acquired=fecha_lote,
                    quantity=cantidad,
                    cost_basis_usd=cost_usd,
                    proceeds_usd=proceeds_usd,
                    gain_loss_usd=proceeds_usd - cost_usd,
                    stock_source=_STOCK_SOURCE_DEFAULT,
                    ticker=ticker,
                    source=SourceRef(
                        file=csv_file or "ledger.csv",
                        page=1,
                        row=ev.row - 1,  # SourceRef muestra fila = row + 1
                        section="ledger FIFO",
                    ),
                ))

    return fragments, errores


def usd_dates(fragments: list[StockSale]) -> set[date]:
    """Fechas (adquisición y venta) de los fragmentos, para la descarga de tipos BCE."""
    dates: set[date] = set()
    for f in fragments:
        dates.add(f.date_sold)
        dates.add(f.date_acquired)
    return dates
