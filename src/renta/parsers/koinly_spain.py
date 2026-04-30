"""
Parser para el Informe de plusvalías para España de Koinly.

Solo extrae la tabla de totales por activo (Activo / Valor EUR / Ingresos EUR / Ganancia).
Las sub-filas por categoría (p. ej. "XRP fue vendido por fiat ...") se ignoran porque
no encajan con el patrón de 4 tokens: ticker + 3 números.
"""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from renta.models import KoinlySpainData, SourceRef

_YEAR_RE = re.compile(r"para el año (\d{4})", re.IGNORECASE)

# Fila de activo total: ticker seguido de exactamente 3 números (formato europeo con coma)
_NUM = r"(-?[\d]+[.,][\d]+)"
_ASSET_ROW_RE = re.compile(
    rf"^([A-Z][A-Z0-9]*)\s+{_NUM}\s+{_NUM}\s+{_NUM}$"
)


def _parse_decimal(s: str) -> Decimal | None:
    s = s.strip()
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse(pdf_path: Path) -> KoinlySpainData:
    filename = pdf_path.name
    data = KoinlySpainData()

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""

            # Año fiscal desde el título
            if data.year is None:
                m = _YEAR_RE.search(text)
                if m:
                    data.year = int(m.group(1))

            for row_idx, line in enumerate(text.split("\n")):
                line = line.strip()
                m = _ASSET_ROW_RE.match(line)
                if not m:
                    continue
                ticker = m.group(1)
                valor = _parse_decimal(m.group(2))
                ingresos = _parse_decimal(m.group(3))
                ganancia = _parse_decimal(m.group(4))
                if valor is None or ingresos is None or ganancia is None:
                    continue
                data.asset_totals[ticker] = {
                    "valor_eur": valor,
                    "ingresos_eur": ingresos,
                    "ganancia_eur": ganancia,
                    "source": SourceRef(
                        file=filename,
                        page=page_num,
                        row=row_idx,
                        section="Informe de plusvalías para España",
                    ),
                }

    return data


def validate(data: KoinlySpainData) -> list[str]:
    if not data.asset_totals:
        return ["Koinly Spain report: no se encontraron activos en la tabla de totales"]
    return []


def detect(first_page_text: str) -> bool:
    t = first_page_text.lower()
    return "koinly" in t and "informe de plusval" in t


def stats_summary(data: KoinlySpainData) -> str:
    return f"{len(data.asset_totals)} activos (totales oficiales)"


def year_hint(data: KoinlySpainData) -> int | None:
    return data.year


def usd_dates(data: KoinlySpainData) -> set:
    return set()
