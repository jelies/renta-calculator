"""
Parser para el PDF 'Custom transaction summary' de Fidelity NetBenefits.

El PDF es un 'Save as PDF' de una página web. Cada página tiene 4 celdas:
  0: Cabecera de Fidelity (dirección, fecha)
  1: Cabecera de sección + cabecera de columnas
  2: Datos (todas las filas como texto multilinea separadas por \\n)
  3: Número de página + notas al pie

Los datos se parsean extrayendo la celda de datos y aplicando regex línea a línea.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from renta.models import (
    DividendEntry,
    FidelityData,
    SourceRef,
    StockSale,
    WithholdingEntry,
)

# Marcadores en el texto de la celda de cabecera de sección
_SECTION_MARKERS = {
    "dividends": "Dividend income",
    "interest": "Interest income",
    "stock_sales": "Stock sales",
    "us_backup": "US backup tax withholding",
    "withholding": "Nonresident alien withholding",
}

# Regex para la línea del resumen en la página 1
_SUMMARY_RE = re.compile(
    r"(Dividend income|Stock sales|Nonresident alien withholding)"
    r"\s+\d+\s+transactions?\s+[·•\-]+\s+Total\s+(-?\$?[\d,]+\.?\d*)\s+USD",
)

# Regex para parsear líneas de cada tipo de transacción
_DATE_PAT = r"([A-Za-z]{3}-\d{2}-\d{4})"
_AMOUNT_PAT = r"(-?\+?\s*\$?[\d,]+\.\d+)\s+USD"

# Dividendo: "Jan-25-2024 Dividend / Interest $47.20 USD"
_DIV_RE = re.compile(
    rf"^{_DATE_PAT}\s+Dividend\s*/\s*Interest\s+{_AMOUNT_PAT}$"
)

# Venta de acciones:
# "Mar-12-2024 May-05-2020 15.0000 $776.25 $1,893.73 + $1,117.48 USD RS"
# "Sep-23-2024 Sep-20-2024 8.0000 $1,340.72 $1,324.23 -$16.49 USD RS"
_SALE_RE = re.compile(
    rf"^{_DATE_PAT}\s+{_DATE_PAT}\s+"
    r"([\d.]+)\s+"          # quantity
    r"\$([\d,]+\.\d+)\s+"   # cost basis
    r"\$([\d,]+\.\d+)\s+"   # proceeds
    r"([+\-]?\s*\$?[\d,]+\.\d+)\s+USD\s+"  # gain/loss (con o sin signo)
    r"([A-Z]+)"             # stock source
    r"$"
)

# Retención: "Jan-25-2024 Other -$7.08 USD" o "Jan-31-2024 Other $0.02 USD"
_WITH_RE = re.compile(
    rf"^{_DATE_PAT}\s+Other\s+(-?\$?[\d,]+\.\d+)\s+USD$"
)


def _parse_date(s: str) -> date | None:
    s = s.strip()
    try:
        return datetime.strptime(s, "%b-%d-%Y").date()
    except ValueError:
        return None


def _parse_decimal(s: str) -> Decimal | None:
    s = re.sub(r"[\$\s,]", "", s.strip())
    s = s.replace("+", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None



def _parse_dividends(lines: list[str], page_num: int, filename: str) -> list[DividendEntry]:
    entries = []
    match_count = 0
    for line in lines:
        line = line.strip()
        m = _DIV_RE.match(line)
        if not m:
            continue
        d = _parse_date(m.group(1))
        amount = _parse_decimal(m.group(2))
        if d is None or amount is None:
            continue
        entries.append(DividendEntry(
            date=d,
            amount_usd=amount,
            source=SourceRef(file=filename, page=page_num, row=match_count, section="Dividend income"),
        ))
        match_count += 1
    return entries


def _parse_stock_sales(lines: list[str], page_num: int, filename: str, ticker: str) -> list[StockSale]:
    sales = []
    match_count = 0
    for line in lines:
        line = line.strip()
        m = _SALE_RE.match(line)
        if not m:
            continue
        date_sold = _parse_date(m.group(1))
        date_acq = _parse_date(m.group(2))
        qty = _parse_decimal(m.group(3))
        cost = _parse_decimal(m.group(4))
        proceeds = _parse_decimal(m.group(5))
        gain = _parse_decimal(m.group(6))
        source_code = m.group(7).strip()

        if any(v is None for v in [date_sold, date_acq, qty, cost, proceeds]):
            continue
        if gain is None:
            gain = proceeds - cost

        sales.append(StockSale(
            date_sold=date_sold,
            date_acquired=date_acq,
            quantity=qty,
            cost_basis_usd=cost,
            proceeds_usd=proceeds,
            gain_loss_usd=gain,
            stock_source=source_code,
            ticker=ticker,
            source=SourceRef(file=filename, page=page_num, row=match_count, section="Stock sales"),
        ))
        match_count += 1
    return sales


def _parse_withholdings(lines: list[str], page_num: int, filename: str) -> list[WithholdingEntry]:
    entries = []
    match_count = 0
    for line in lines:
        line = line.strip()
        m = _WITH_RE.match(line)
        if not m:
            continue
        d = _parse_date(m.group(1))
        amount = _parse_decimal(m.group(2))
        if d is None or amount is None:
            continue
        entries.append(WithholdingEntry(
            date=d,
            amount_usd=amount,
            source=SourceRef(file=filename, page=page_num, row=match_count, section="Nonresident alien withholding"),
        ))
        match_count += 1
    return entries


def parse(pdf_path: Path) -> FidelityData:
    filename = pdf_path.name
    data = FidelityData()
    current_section: str | None = None
    current_ticker = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page_num_0, page in enumerate(pdf.pages):
            page_num = page_num_0 + 1
            text = page.extract_text() or ""

            # Página 1: extraer resumen del totales
            if page_num == 1:
                for m in _SUMMARY_RE.finditer(text):
                    key_text = m.group(1)
                    val = _parse_decimal(m.group(2))
                    if val is None:
                        continue
                    if key_text == "Dividend income":
                        data.summary_dividends_usd = val
                    elif key_text == "Stock sales":
                        data.summary_stock_sales_usd = val
                    elif key_text == "Nonresident alien withholding":
                        data.summary_withholding_usd = val
                continue

            # Resto de páginas: escanear línea a línea
            # Contadores de filas de datos por sección (se resetean por página)
            section_counters: dict[str, int] = {}

            for raw_line in text.split("\n"):
                line = raw_line.strip()

                # Detectar cambio de sección
                for section, marker in _SECTION_MARKERS.items():
                    if marker in line:
                        current_section = section
                        break

                # Detectar ticker en cabecera de ventas (ej: "ORCL: ORACLE CORP")
                if current_section == "stock_sales":
                    tm = re.match(r"^([A-Z]{1,6}):\s+[A-Z]", line)
                    if tm:
                        current_ticker = tm.group(1)

                if current_section == "dividends":
                    m = _DIV_RE.match(line)
                    if m:
                        d = _parse_date(m.group(1))
                        amount = _parse_decimal(m.group(2))
                        if d and amount:
                            row = section_counters.get("dividends", 0)
                            src = SourceRef(file=filename, page=page_num, row=row, section="dividends")
                            section_counters["dividends"] = row + 1
                            data.dividends.append(DividendEntry(date=d, amount_usd=amount, source=src))

                elif current_section == "stock_sales":
                    m = _SALE_RE.match(line)
                    if m:
                        date_sold = _parse_date(m.group(1))
                        date_acq = _parse_date(m.group(2))
                        qty = _parse_decimal(m.group(3))
                        cost = _parse_decimal(m.group(4))
                        proceeds = _parse_decimal(m.group(5))
                        gain = _parse_decimal(m.group(6))
                        source_code = m.group(7).strip()
                        if all(v is not None for v in [date_sold, date_acq, qty, cost, proceeds]):
                            if gain is None:
                                gain = proceeds - cost
                            row = section_counters.get("stock_sales", 0)
                            src = SourceRef(file=filename, page=page_num, row=row, section="stock_sales")
                            section_counters["stock_sales"] = row + 1
                            data.stock_sales.append(StockSale(
                                date_sold=date_sold, date_acquired=date_acq,
                                quantity=qty, cost_basis_usd=cost,
                                proceeds_usd=proceeds, gain_loss_usd=gain,
                                stock_source=source_code, ticker=current_ticker,
                                source=src,
                            ))

                elif current_section == "withholding":
                    m = _WITH_RE.match(line)
                    if m:
                        d = _parse_date(m.group(1))
                        amount = _parse_decimal(m.group(2))
                        if d and amount:
                            row = section_counters.get("withholding", 0)
                            src = SourceRef(file=filename, page=page_num, row=row, section="withholding")
                            section_counters["withholding"] = row + 1
                            data.withholdings.append(WithholdingEntry(date=d, amount_usd=amount, source=src))

    return data


def validate(data: FidelityData) -> list[str]:
    warnings = []
    tolerance = Decimal("0.05")

    if data.summary_dividends_usd is not None:
        parsed = sum((e.amount_usd for e in data.dividends), Decimal("0"))
        diff = abs(parsed - data.summary_dividends_usd)
        if diff > tolerance:
            warnings.append(
                f"Fidelity dividendos: total parseado ${parsed:.2f} USD ≠ "
                f"resumen PDF ${data.summary_dividends_usd:.2f} USD (diff ${diff:.2f})"
            )

    if data.summary_stock_sales_usd is not None:
        # El "Total" del resumen de Fidelity es la ganancia/pérdida neta, no los ingresos
        parsed = sum((s.gain_loss_usd for s in data.stock_sales), Decimal("0"))
        diff = abs(parsed - data.summary_stock_sales_usd)
        if diff > tolerance:
            warnings.append(
                f"Fidelity ventas: ganancia/pérdida neta parseada ${parsed:.2f} USD ≠ "
                f"resumen PDF ${data.summary_stock_sales_usd:.2f} USD (diff ${diff:.2f})"
            )

    if data.summary_withholding_usd is not None:
        parsed = sum((e.amount_usd for e in data.withholdings), Decimal("0"))
        diff = abs(parsed - data.summary_withholding_usd)
        if diff > tolerance:
            warnings.append(
                f"Fidelity retenciones: total parseado ${parsed:.2f} USD ≠ "
                f"resumen PDF ${data.summary_withholding_usd:.2f} USD (diff ${diff:.2f})"
            )

    return warnings


# ---------------------------------------------------------------------------
# Funciones del contrato de parser (usadas por el registry)
# ---------------------------------------------------------------------------

def detect(first_page_text: str) -> bool:
    """Devuelve True si el PDF pertenece a Fidelity NetBenefits."""
    return "fidelity" in first_page_text.lower()


def stats_summary(data: FidelityData) -> str:
    """Resumen de una línea para la salida del CLI tras parsear."""
    return (
        f"{len(data.dividends)} dividendos, "
        f"{len(data.stock_sales)} ventas, "
        f"{len(data.withholdings)} retenciones"
    )


def year_hint(data: FidelityData) -> int | None:
    """Devuelve el año fiscal de los datos, o None si no hay transacciones."""
    if data.dividends:
        return data.dividends[0].date.year
    if data.stock_sales:
        return data.stock_sales[0].date_sold.year
    return None


def usd_dates(data: FidelityData) -> set[date]:
    """Devuelve todas las fechas que necesitan conversión USD→EUR."""
    dates: set[date] = set()
    for d in data.dividends:
        dates.add(d.date)
    for s in data.stock_sales:
        dates.add(s.date_sold)
        dates.add(s.date_acquired)
    for w in data.withholdings:
        dates.add(w.date)
    return dates
