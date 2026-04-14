"""
Parser para el "Informe Fiscal Anual" de DEGIRO (flatexDEGIRO).

Estructura del PDF:
- Pág 1: cabecera con "flatexDEGIRO" + "Informe Fiscal para el año YYYY"
- Pág 2: resumen "Ganancias / Pérdidas Realizadas"
- Pág N: tabla de dividendos (País | Producto | Ingreso bruto | Retenciones | Ingreso neto)
         Filas CON código de país = pagos individuales
         Filas SIN país = running totals acumulados (ignorar; la última es el gran total)
- Pág M: tabla de ventas detallada "Beneficios y pérdidas derivadas de la transmisión"
         (si no existe, fallback a sección resumida con solo totales)

Todos los importes ya están en EUR: no se necesita conversión de divisa.
"""

import bisect
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import pdfplumber

from renta.models import DegiroData, DegiroDividend, DegiroStockSale, SourceRef

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Número con coma decimal (formato español): -1.234,56 → 1234.56
# El sufijo " EUR" es opcional (presente en PDFs reales, ausente en el sample sintético)
_NUM = r'-?[\d\.]+,\d+(?:\s+EUR)?'

# Fila de dividendo con código de país (2 letras mayúsculas al inicio)
# Ej: "US ARES CAPITAL CORPORATI 0,89 EUR -0,13 EUR 0,76 EUR"
_DIV_DATA_RE = re.compile(
    r'^([A-Z]{2})\s+(.+?)\s+(-?[\d\.]+,\d+)(?:\s+EUR)?\s+(-?[\d\.]+,\d+)(?:\s+EUR)?\s+(-?[\d\.]+,\d+)(?:\s+EUR)?\s*$'
)

# Fila de running total de dividendos: solo 3 números sin etiqueta
# Ej: "0,89 EUR -0,13 EUR 0,76 EUR"  o  "4,06 -0,59 3,48"
_DIV_TOTAL_PURE_RE = re.compile(
    r'^(-?[\d\.]+,\d+)(?:\s+EUR)?\s+(-?[\d\.]+,\d+)(?:\s+EUR)?\s+(-?[\d\.]+,\d+)(?:\s+EUR)?\s*$'
)

# Fila de venta detallada: fecha DD/MM/YYYY al inicio
_DATE_PAT = r'\d{2}/\d{2}/\d{4}'
_ISIN_PAT = r'[A-Z]{2}[A-Z0-9]{10}'
_SALE_DATA_RE = re.compile(
    rf'^({_DATE_PAT})\s+(.+?)\s+({_ISIN_PAT})\s+([A-Z])\s+(\d+(?:,\d+)?)\s+'
    rf'({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s*$'
)

# Año fiscal
_YEAR_RE = re.compile(r'(?:Informe\s+Anual|Informe\s+Fiscal\s+para\s+el\s+año)\s+(\d{4})', re.IGNORECASE)

# Totales del resumen pág 2
_SUMMARY_GAINS_RE = re.compile(r'Ganancias\s+patrimoniales\s+totales[:\s]+(-?[\d\.]*,\d+)', re.IGNORECASE)
_SUMMARY_LOSSES_RE = re.compile(r'Pérdidas\s+totales[:\s]+(-?[\d\.]*,\d+)', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Utilidades de parseo numérico
# ---------------------------------------------------------------------------

def _parse_decimal(s: str) -> Decimal | None:
    """Convierte número en formato español (coma decimal, punto miles) a Decimal."""
    s = s.strip()
    if not s or s in ('-', '—'):
        return None
    try:
        # Eliminar separadores de miles (puntos antes de la coma decimal)
        # y convertir coma decimal a punto
        normalized = s.replace('.', '').replace(',', '.')
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _parse_date(s: str) -> date | None:
    """Parsea DD/MM/YYYY."""
    s = s.strip()
    try:
        d, m, y = s.split('/')
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Localización de página por offset en all_text
# ---------------------------------------------------------------------------

def _build_page_locator(pages_text: list[str]) -> Callable[[int], int]:
    """Devuelve una función que mapea un offset en all_text al número de página (1-based).

    all_text se construye como '\\n'.join(pages_text), así que el offset de inicio
    de la página i es la suma de len(pages_text[j]) + 1 para j < i.
    """
    starts: list[int] = []
    offset = 0
    for txt in pages_text:
        starts.append(offset)
        offset += len(txt) + 1  # +1 por el '\\n' del join

    def locate(abs_offset: int) -> int:
        idx = bisect.bisect_right(starts, abs_offset) - 1
        return max(idx, 0) + 1  # 1-based

    return locate


# ---------------------------------------------------------------------------
# Contrato del parser
# ---------------------------------------------------------------------------

def detect(first_page_text: str) -> bool:
    """Detecta si el PDF es un informe fiscal de DEGIRO."""
    lower = first_page_text.lower()
    return "degiro" in lower


def parse(pdf_path: Path) -> DegiroData:
    """Parsea el PDF y devuelve DegiroData."""
    filename = pdf_path.name
    data = DegiroData()

    with pdfplumber.open(pdf_path) as pdf:
        pages_text = []
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")

    all_text = "\n".join(pages_text)
    page_for_offset = _build_page_locator(pages_text)

    # --- Año ---
    m = _YEAR_RE.search(all_text)
    if m:
        data.year = int(m.group(1))

    # --- Totales del resumen (pág 2) ---
    m = _SUMMARY_GAINS_RE.search(all_text)
    if m:
        data.summary_gains_eur = _parse_decimal(m.group(1))
    m = _SUMMARY_LOSSES_RE.search(all_text)
    if m:
        data.summary_losses_eur = _parse_decimal(m.group(1))

    # --- Dividendos ---
    _parse_dividends(all_text, filename, data, page_for_offset)

    # --- Ventas (sección detallada primero; fallback a resumida) ---
    if "Beneficios y pérdidas derivadas de la transmisión" in all_text:
        _parse_sales_detailed(all_text, filename, data, page_for_offset)
    else:
        _parse_sales_summary(all_text, filename, data)

    return data


def _parse_dividends(all_text: str, filename: str, data: DegiroData,
                     page_for_offset: Callable[[int], int]) -> None:
    """Extrae dividendos individuales y los totales de validación."""
    # Buscar sección de dividendos (el marcador varía según la versión del PDF)
    section_markers = [
        "Dividendos, Cupones y otras remuneraciones",
        "Dividendos recibidos",
        "Dividendos",
    ]
    section_start = -1
    for marker in section_markers:
        idx = all_text.find(marker)
        if idx != -1:
            section_start = idx
            break

    if section_start == -1:
        return

    # Delimitar la sección: hasta la siguiente sección mayor o fin del texto
    next_section_markers = [
        "Beneficios y pérdidas derivadas",
        "Relación de ganancias",
        "Impuesto sobre",
    ]
    section_end = len(all_text)
    for marker in next_section_markers:
        idx = all_text.find(marker, section_start + 50)
        if idx != -1:
            section_end = idx
            break
    section_text = all_text[section_start:section_end]

    last_total: tuple[Decimal, Decimal, Decimal] | None = None
    row_num = 0
    pos = 0

    for raw_line in section_text.splitlines(keepends=True):
        line_offset = section_start + pos
        pos += len(raw_line)
        line = raw_line.rstrip()
        if not line:
            continue

        # ¿Es una fila de dato individual (tiene código de país al inicio)?
        m = _DIV_DATA_RE.match(line)
        if m:
            country = m.group(1)
            product = m.group(2).strip()
            gross = _parse_decimal(m.group(3))
            withholding = _parse_decimal(m.group(4))
            net = _parse_decimal(m.group(5))
            if gross is not None and withholding is not None and net is not None:
                data.dividends.append(DegiroDividend(
                    country=country,
                    product=product,
                    gross_eur=gross,
                    withholding_eur=withholding,
                    net_eur=net,
                    source=SourceRef(
                        file=filename,
                        page=page_for_offset(line_offset),
                        row=row_num,
                        section="Dividendos recibidos",
                    ),
                ))
                row_num += 1
            continue

        # ¿Es una running total? Solo 3 números sin etiqueta de país
        # Ej: "0,89 EUR -0,13 EUR 0,76 EUR"  o  "4,06 -0,59 3,48"
        m = _DIV_TOTAL_PURE_RE.match(line)
        if m:
            gross = _parse_decimal(m.group(1))
            withholding = _parse_decimal(m.group(2))
            net = _parse_decimal(m.group(3))
            if gross is not None and withholding is not None and net is not None:
                last_total = (gross, withholding, net)

    # La última running total es el gran total para validación
    if last_total:
        data.summary_dividends_gross_eur = last_total[0]
        data.summary_dividends_withholding_eur = last_total[1]
        data.summary_dividends_net_eur = last_total[2]


def _parse_sales_detailed(all_text: str, filename: str, data: DegiroData,
                          page_for_offset: Callable[[int], int]) -> None:
    """Extrae ventas de la sección detallada (2025+)."""
    marker = "Beneficios y pérdidas derivadas de la transmisión"
    section_start = all_text.find(marker)
    if section_start == -1:
        return

    section_text = all_text[section_start:]
    last_total: Decimal | None = None
    row_num = 0
    pos = 0

    for raw_line in section_text.splitlines(keepends=True):
        line_offset = section_start + pos
        pos += len(raw_line)
        line = raw_line.rstrip()
        if not line:
            continue

        m = _SALE_DATA_RE.match(line)
        if m:
            dt = _parse_date(m.group(1))
            product = m.group(2).strip()
            symbol_isin = m.group(3)
            order_type = m.group(4)
            quantity = _parse_decimal(m.group(5))
            price = _parse_decimal(m.group(6))
            value_local = _parse_decimal(m.group(7))
            value_eur = _parse_decimal(m.group(8))
            commission = _parse_decimal(m.group(9))
            exchange_rate = _parse_decimal(m.group(10))
            gain_loss = _parse_decimal(m.group(11))

            if (dt and quantity is not None and price is not None
                    and value_local is not None and value_eur is not None
                    and commission is not None and exchange_rate is not None
                    and gain_loss is not None):
                data.stock_sales.append(DegiroStockSale(
                    date_sold=dt,
                    product=product,
                    symbol_isin=symbol_isin,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    value_local=value_local,
                    value_eur=value_eur,
                    commission_eur=commission,
                    exchange_rate=exchange_rate,
                    gain_loss_eur=gain_loss,
                    source=SourceRef(
                        file=filename,
                        page=page_for_offset(line_offset),
                        row=row_num,
                        section="Beneficios y pérdidas derivadas de la transmisión",
                    ),
                ))
                row_num += 1
            continue

        # Fila Total de la sección de ventas (contiene 3 números al final)
        # Formato: "Total VALUE_EUR COMMISSION GAIN_LOSS" o " Total ..."
        if re.match(r'^\s*[Tt]otal', line):
            nums = re.findall(_NUM, line)
            if len(nums) >= 1:
                # El último número es el total de ganancias/pérdidas
                last_total = _parse_decimal(nums[-1])

    if last_total is not None:
        data.summary_stock_sales_total_eur = last_total


def _parse_sales_summary(all_text: str, filename: str, data: DegiroData) -> None:
    """Extrae totales de la sección resumida (2024 sin ventas)."""
    # Esta sección solo tiene una fila "Total" con 0,00 EUR
    # Solo actualizamos el summary, no añadimos ventas individuales
    marker = "Relación de ganancias y pérdidas por producto"
    idx = all_text.find(marker)
    if idx == -1:
        return

    # Buscar fila Total hasta el final del texto (puede estar en la página siguiente)
    section_text = all_text[idx:]
    _NUM_BARE = r'-?[\d\.]+,\d+'
    for line in section_text.splitlines():
        line_stripped = line.strip()
        if re.match(r'^[Tt]otal\b', line_stripped):
            nums = re.findall(_NUM_BARE, line)
            if nums:
                data.summary_stock_sales_total_eur = _parse_decimal(nums[-1])
            break


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def validate(data: DegiroData) -> list[str]:
    """Compara totales parseados con los del resumen del PDF."""
    warnings = []
    tol = Decimal("0.05")

    # Validar total bruto de dividendos
    if data.summary_dividends_gross_eur is not None and data.dividends:
        parsed_total = sum(d.gross_eur for d in data.dividends)
        diff = abs(parsed_total - data.summary_dividends_gross_eur)
        if diff > tol:
            warnings.append(
                f"DEGIRO dividendos: suma bruta parseada ({parsed_total:.2f}€) "
                f"difiere del total del PDF ({data.summary_dividends_gross_eur:.2f}€) "
                f"en {diff:.2f}€"
            )

    # Validar total de retenciones
    if data.summary_dividends_withholding_eur is not None and data.dividends:
        parsed_wh = sum(d.withholding_eur for d in data.dividends)
        diff = abs(parsed_wh - data.summary_dividends_withholding_eur)
        if diff > tol:
            warnings.append(
                f"DEGIRO retenciones: suma parseada ({parsed_wh:.2f}€) "
                f"difiere del total del PDF ({data.summary_dividends_withholding_eur:.2f}€) "
                f"en {diff:.2f}€"
            )

    # Validar total de ganancias/pérdidas de ventas
    if data.summary_stock_sales_total_eur is not None and data.stock_sales:
        parsed_gain = sum(s.gain_loss_eur for s in data.stock_sales)
        diff = abs(parsed_gain - data.summary_stock_sales_total_eur)
        if diff > tol:
            warnings.append(
                f"DEGIRO ventas: suma ganancias parseada ({parsed_gain:.4f}€) "
                f"difiere del total del PDF ({data.summary_stock_sales_total_eur:.4f}€) "
                f"en {diff:.4f}€"
            )

    return warnings


# ---------------------------------------------------------------------------
# Funciones de metadatos
# ---------------------------------------------------------------------------

def stats_summary(data: DegiroData) -> str:
    return f"{len(data.dividends)} dividendos, {len(data.stock_sales)} ventas (DEGIRO)"


def year_hint(data: DegiroData) -> int | None:
    return data.year


def usd_dates(data: DegiroData) -> set:
    """DEGIRO ya está en EUR, no necesita conversión."""
    return set()
