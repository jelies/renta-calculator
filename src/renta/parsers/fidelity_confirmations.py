"""
Parser de Trade Confirmations de Fidelity para generar el CSV ledger del modo --fidelity-fifo.

Reconoce dos tipos de documento:
  - Distribución de RSU («N SHARES WERE DISTRIBUTED»): genera una fila «adquisicion».
  - Venta («YOU SOLD N AT precio»): genera una fila «venta».

FMV/acción en distribuciones:
  - PDFs modernos (2021+): campo explícito «Fair Market Value: $X».
  - PDFs antiguos (2020): se deriva de «Market Value at Distribution $X» ÷ «Shares Distributed N».
    No es un valor inventado: es el mismo cálculo que Fidelity ya resuelve en los PDFs modernos.

Cantidad de adquisición: «Net Shares Deposited» (o «Shares Deposited»), es decir, las acciones
que *realmente* entran en cuenta. Las acciones neteadas para cubrir retenciones (net share
settlement) nunca se depositan y no forman parte del inventario FIFO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber


# ── Constantes ────────────────────────────────────────────────────────────────

_MESES: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Regex para extraer campos clave del texto plano del PDF.
_RE_SYMBOL = re.compile(r"SYMBOL:\s*(\S+)")
_RE_DISTRIBUTED = re.compile(r"\d+\s+SHARES\s+WERE\s+DISTRIBUTED")
_RE_DATE_DIST = re.compile(r"Date of Distribution:\s*([A-Z]{3}/\d{2}/\d{4})")
_RE_FMV_EXPLICIT = re.compile(r"Fair Market Value:\s*\$?([\d.]+)")
_RE_MARKET_VALUE = re.compile(r"Market Value at Distribution\D*\$([\d,]+\.\d+)")
_RE_SHARES_DIST = re.compile(r"Shares Distributed\s+(\d+)")
_RE_SHARES_DEP = re.compile(r"Shares Deposited\s+(\d+)")   # captura ambos rótulos
_RE_YOU_SOLD = re.compile(r"YOU SOLD\s+(\d+)\s+AT\s+([\d.]+)")
_RE_SALE_DATE = re.compile(r"Sale Date:\s*([A-Z]{3}/\d{2}/\d{4})")


# ── Tipos de datos ─────────────────────────────────────────────────────────────

@dataclass
class LedgerRow:
    """Una fila del ledger CSV, extraída de un único PDF."""
    fecha: date
    ticker: str
    tipo: str              # "adquisicion" | "venta"
    cantidad: Decimal
    precio_usd: Decimal
    fmv_derivado: bool     # True cuando el FMV se derivó de Market Value / Shares (PDFs 2020)
    source: str            # nombre del fichero PDF (para trazabilidad)


# ── Funciones de parsing ───────────────────────────────────────────────────────

def _parse_us_date(s: str) -> date:
    """Convierte «AUG/03/2024» a date(2024, 8, 3). Sin dependencia del locale."""
    parts = s.split("/")
    if len(parts) != 3:
        raise ValueError(f"Formato de fecha no reconocido: {s!r}")
    mes_s, dia_s, anio_s = parts
    mes = _MESES.get(mes_s.upper())
    if mes is None:
        raise ValueError(f"Mes desconocido: {mes_s!r}")
    return date(int(anio_s), mes, int(dia_s))


def parse_confirmation_text(text: str, source_name: str = "") -> LedgerRow | None:
    """
    Parsea el texto plano de una Trade Confirmation y devuelve un LedgerRow.

    Devuelve None si el documento no tiene el formato esperado (no es compra ni venta).
    Lanza ValueError si el documento se reconoce pero los campos son inválidos.
    """
    # Ticker — presente en ambos tipos.
    sym_m = _RE_SYMBOL.search(text)
    if not sym_m:
        return None
    ticker = sym_m.group(1).upper()

    # ── Distribución de RSU ──────────────────────────────────────────────────
    if _RE_DISTRIBUTED.search(text):
        fecha_m = _RE_DATE_DIST.search(text)
        if not fecha_m:
            raise ValueError(f"[{source_name}] Distribución sin «Date of Distribution»")
        fecha = _parse_us_date(fecha_m.group(1))

        # Cantidad = acciones netas depositadas (descontadas las retenidas por impuestos).
        dep_m = _RE_SHARES_DEP.search(text)
        if not dep_m:
            raise ValueError(f"[{source_name}] Distribución sin «Shares Deposited»")
        cantidad = Decimal(dep_m.group(1))

        # FMV/acción: campo explícito (PDFs 2021+) o derivado (PDFs 2020).
        fmv_m = _RE_FMV_EXPLICIT.search(text)
        if fmv_m:
            precio_usd = Decimal(fmv_m.group(1))
            fmv_derivado = False
        else:
            mv_m = _RE_MARKET_VALUE.search(text)
            dist_m = _RE_SHARES_DIST.search(text)
            if not mv_m or not dist_m:
                raise ValueError(
                    f"[{source_name}] Distribución sin «Fair Market Value» ni "
                    f"«Market Value at Distribution» + «Shares Distributed»"
                )
            market_value = Decimal(mv_m.group(1).replace(",", ""))
            shares_distributed = Decimal(dist_m.group(1))
            precio_usd = market_value / shares_distributed
            fmv_derivado = True

        _validate(source_name, cantidad, precio_usd)
        return LedgerRow(
            fecha=fecha,
            ticker=ticker,
            tipo="adquisicion",
            cantidad=cantidad,
            precio_usd=precio_usd,
            fmv_derivado=fmv_derivado,
            source=source_name,
        )

    # ── Venta ────────────────────────────────────────────────────────────────
    sold_m = _RE_YOU_SOLD.search(text)
    if sold_m:
        fecha_m = _RE_SALE_DATE.search(text)
        if not fecha_m:
            raise ValueError(f"[{source_name}] Venta sin «Sale Date»")
        fecha = _parse_us_date(fecha_m.group(1))
        cantidad = Decimal(sold_m.group(1))
        # El precio puede terminar en «****» (truncado por el PDF); se limpian los asteriscos.
        precio_usd = Decimal(re.sub(r"[^0-9.]", "", sold_m.group(2)))
        _validate(source_name, cantidad, precio_usd)
        return LedgerRow(
            fecha=fecha,
            ticker=ticker,
            tipo="venta",
            cantidad=cantidad,
            precio_usd=precio_usd,
            fmv_derivado=False,
            source=source_name,
        )

    # Documento reconocible como Trade Confirmation de Fidelity pero sin operación clara.
    return None


def _validate(source: str, cantidad: Decimal, precio: Decimal) -> None:
    """Valida que cantidad > 0 y precio >= 0 (regla CLAUDE.md: nunca inventar ni silenciar)."""
    if cantidad <= 0:
        raise ValueError(f"[{source}] cantidad debe ser > 0 (es {cantidad})")
    if precio < 0:
        raise ValueError(f"[{source}] precio_usd no puede ser negativo (es {precio})")


# ── Extracción de PDF ──────────────────────────────────────────────────────────

def extract_pdf_text(path: str | Path) -> str:
    """Extrae el texto de todas las páginas de un PDF usando pdfplumber."""
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# ── Construcción de la lista de filas ─────────────────────────────────────────

def build_rows(
    pdf_paths: list[str | Path],
) -> tuple[list[LedgerRow], list[str]]:
    """
    Lee una lista de PDFs y devuelve (filas, avisos).

    - filas:  list[LedgerRow] con todas las operaciones reconocidas.
    - avisos: list[str] con PDFs que no produjeron ninguna fila reconocible.
    """
    rows: list[LedgerRow] = []
    warnings: list[str] = []

    for path in pdf_paths:
        path = Path(path)
        name = path.name
        try:
            text = extract_pdf_text(path)
            row = parse_confirmation_text(text, source_name=name)
        except (ValueError, OSError) as exc:
            warnings.append(f"⚠️  {name}: {exc}")
            continue

        if row is None:
            warnings.append(f"⚠️  No reconocido: {name}")
        else:
            rows.append(row)

    return rows, warnings


# ── Generación del CSV ─────────────────────────────────────────────────────────

def rows_to_csv(rows: list[LedgerRow], generated_on: str = "") -> str:
    """
    Convierte una lista de LedgerRow a un string CSV listo para escribir.

    Orden: (fecha ASC, adquisiciones antes que ventas en el mismo día).
    Incluye un bloque de comentarios '#' en la cabecera.
    """
    from datetime import date as _date
    import datetime as _datetime

    if not generated_on:
        generated_on = _datetime.date.today().isoformat()

    # Ordenar: fecha ASC; en empate, adquisicion(0) antes que venta(1).
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.fecha, 0 if r.tipo == "adquisicion" else 1),
    )

    derivados = [r for r in sorted_rows if r.fmv_derivado]
    derivado_nota = ""
    if derivados:
        derivado_nota = (
            "# FMV derivado (Market Value at Distribution / Shares Distributed) en:\n"
            + "".join(f"#   - {r.source}\n" for r in derivados)
        )

    n_adq = sum(1 for r in sorted_rows if r.tipo == "adquisicion")
    n_ven = sum(1 for r in sorted_rows if r.tipo == "venta")

    lines = [
        f"# Ledger FIFO de acciones de Fidelity — generado automáticamente el {generated_on}",
        "# a partir de las Trade Confirmations en input/fidelity_ledger/.",
        f"# Operaciones: {len(sorted_rows)} ({n_adq} adquisiciones + {n_ven} ventas)",
        "#",
        "# Columnas:",
        "#   fecha       YYYY-MM-DD (vesting para adquisiciones; fecha de venta para ventas)",
        "#   ticker      símbolo bursátil",
        "#   tipo        adquisicion | venta",
        "#   cantidad    acciones netas depositadas en cuenta (descontado el neteo de impuestos)",
        "#   precio_usd  FMV/acción al vesting (adquisiciones) o precio/acción recibido (ventas)",
        "#",
        "# NOTA sobre la cantidad de adquisición:",
        "#   Se usa «Net Shares Deposited» (acciones realmente depositadas en cuenta), NO el",
        "#   total distribuido bruto. Las acciones neteadas para cubrir retenciones fiscales",
        "#   (net share settlement) nunca entran en la cuenta y no forman parte del FIFO.",
        "#   En los vestings con sell-to-cover, esas acciones aparecen como «YOU SOLD» en un",
        "#   PDF separado y están incluidas aquí como fila de venta independiente.",
        "#",
    ]
    if derivado_nota:
        for line in derivado_nota.rstrip("\n").splitlines():
            lines.append(line)
        lines.append("#")
    lines.append("fecha,ticker,tipo,cantidad,precio_usd")

    for r in sorted_rows:
        # Normalizar precio a representación sin ceros finales innecesarios pero
        # preservando la precisión exacta del PDF.
        precio_str = str(r.precio_usd.normalize())
        # normalize() puede producir notación científica en ceros exactos;
        # en ese caso usar representación simple.
        if "E" in precio_str or "e" in precio_str:
            precio_str = format(r.precio_usd, "f")
        lines.append(f"{r.fecha.isoformat()},{r.ticker},{r.tipo},{int(r.cantidad)},{precio_str}")

    return "\n".join(lines) + "\n"
