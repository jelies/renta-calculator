"""
Parser para el Tax Report de Koinly.

El PDF de Koinly no tiene tablas detectables por pdfplumber; los datos están
en texto plano con columnas separadas por espacios. Se parsea línea a línea
con regex.

Secciones detectadas por texto marcador en el texto de la página.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from renta.models import (
    CryptoCapitalGain,
    CryptoReward,
    KoinlyData,
    SourceRef,
)

_SECTION_MARKERS = {
    "capital_gains": "Operaciones de Ganancias Patrimoniales",
    "rewards": "Operaciones de rendimientos",
}

# Fecha con hora: DD/MM/YYYY HH:MM
_DT_PAT = r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})"

# Número decimal (positivo o negativo); acepta punto o coma como separador decimal
_NUM = r"(-?[\d]+[.,][\d]+)"

# Ganancias patrimoniales:
# "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken"
# "date_sold date_acq ASSET qty cost proceeds gain [notes] wallet"
# wallet puede ser varias palabras (ej: "Cardano (ADA) - stake1...kd")
_GAIN_RE = re.compile(
    rf"^{_DT_PAT}\s+{_DT_PAT}\s+"
    r"([A-Z]+)\s+"          # asset
    rf"{_NUM}\s+"           # quantity
    rf"{_NUM}\s+"           # cost (Valor EUR)
    rf"{_NUM}\s+"           # proceeds (Ingresos EUR)
    rf"({_NUM})\s+"         # gain/loss
    r"(.*)$"                # notes + wallet (lo separamos después)
)

# Rendimientos/rewards:
# "01/01/2024 01:00 ADA 0.00006762 0.00 Reward Flexible REALTIME Binance"
# "01/01/2024 13:22 STETH 0.00004390 0.09 Reward stETH"
# formato: datetime ASSET qty price TYPE [description] wallet
_REWARD_RE = re.compile(
    rf"^{_DT_PAT}\s+"
    r"([A-Z]+)\s+"          # asset
    rf"{_NUM}\s+"           # quantity
    rf"{_NUM}\s+"           # price EUR
    r"(Reward)\s+"          # type (siempre "Reward" en los datos observados)
    r"(.*)$"                # description + wallet
)


def _parse_datetime(s: str) -> datetime | None:
    s = s.strip()
    try:
        return datetime.strptime(s, "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def _parse_decimal(s: str) -> Decimal | None:
    s = s.strip()
    if "," in s and "." in s:
        # Formato mixto: el último separador es el decimal
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")   # 1.234,56 → 1234.56
        else:
            s = s.replace(",", "")                     # 1,234.56 → 1234.56
    elif "," in s:
        s = s.replace(",", ".")                        # 1,41 → 1.41
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _split_description_wallet(tail: str, known_wallets: list[str]) -> tuple[str, str]:
    """
    Separa la descripción del nombre de wallet al final de la línea.
    En Koinly, el wallet es el último 'token' tras la descripción.
    Heurística: el wallet suele ser una sola palabra o nombre conocido.
    """
    tail = tail.strip()
    if not tail:
        return "", ""
    parts = tail.rsplit(None, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", tail


def _extract_summary(pages_text: list[str]) -> dict[str, Decimal | None]:
    """Extrae totales de las páginas de resumen de Koinly."""
    result: dict[str, Decimal | None] = {"net_gains": None, "rewards": None}

    # Buscar "Ganancias netas" seguido de un número; acepta coma o punto y negativos
    net_gains_re = re.compile(r"Ganancias netas\s+€?(-?[\d]+[.,][\d]+)")
    # Patrón para múltiples Total en la misma página: buscamos el mayor
    total_re = re.compile(r"Total\s+€(-?[\d]+[.,][\d]+)")

    for i, text in enumerate(pages_text[:6]):
        # Ganancias netas crypto (la mayor de las que aparecen, ignorando 0.00)
        if result["net_gains"] is None:
            for m in net_gains_re.finditer(text):
                val = _parse_decimal(m.group(1))
                if val and val > 0:
                    result["net_gains"] = val
                    break

        # Rewards total: la página de resumen de rendimientos tiene dos "Total"
        # (uno para gastos =0 y otro para rendimientos). Tomamos el mayor.
        if "Resumen de rendimientos" in text and result["rewards"] is None:
            candidates = [
                _parse_decimal(m.group(1))
                for m in total_re.finditer(text)
                if _parse_decimal(m.group(1)) is not None
            ]
            if candidates:
                best = max(candidates)
                if best > 0:
                    result["rewards"] = best

    return result


def _find_section_pages(pages_text: list[str]) -> dict[str, list[int]]:
    """
    Localiza las páginas de cada sección.
    Requiere que el marcador sea una línea propia para evitar falsos positivos
    en el índice/tabla de contenidos.
    """
    ordered = ["capital_gains", "rewards"]
    first_page: dict[str, int] = {}
    for i, text in enumerate(pages_text):
        for section, marker in _SECTION_MARKERS.items():
            if section not in first_page:
                # El marcador debe ser una línea propia (cabecera de sección)
                for line in text.split("\n"):
                    if line.strip() == marker:
                        first_page[section] = i
                        break

    result: dict[str, list[int]] = {}
    found_sections = sorted(first_page.items(), key=lambda x: x[1])
    for idx, (section, start_page) in enumerate(found_sections):
        if idx + 1 < len(found_sections):
            end_page = found_sections[idx + 1][1]
        else:
            end_page = len(pages_text)
        result[section] = list(range(start_page, end_page))

    return result


def _parse_capital_gains(
    pages: list[int], pages_text: list[str], filename: str
) -> list[CryptoCapitalGain]:
    gains = []
    row_idx = 0
    for page_num_0 in pages:
        page_num = page_num_0 + 1
        text = pages_text[page_num_0]
        for line in text.split("\n"):
            line = line.strip()
            m = _GAIN_RE.match(line)
            if not m:
                continue
            date_sold = _parse_datetime(m.group(1))
            date_acq = _parse_datetime(m.group(2))
            asset = m.group(3)
            qty = _parse_decimal(m.group(4))
            cost = _parse_decimal(m.group(5))
            proceeds = _parse_decimal(m.group(6))
            gain = _parse_decimal(m.group(7))

            if any(v is None for v in [date_sold, date_acq, qty, cost, proceeds, gain]):
                continue

            tail = m.group(9).strip()  # notes + wallet
            notes, wallet = _split_description_wallet(tail, [])

            gains.append(CryptoCapitalGain(
                date_sold=date_sold,
                date_acquired=date_acq,
                asset=asset,
                quantity=qty,
                cost_eur=cost,
                proceeds_eur=proceeds,
                gain_loss_eur=gain,
                notes=notes,
                wallet=wallet,
                source=SourceRef(
                    file=filename,
                    page=page_num,
                    row=row_idx,
                    section="Operaciones de Ganancias Patrimoniales",
                ),
            ))
            row_idx += 1
    return gains


def _parse_rewards(
    pages: list[int], pages_text: list[str], filename: str
) -> list[CryptoReward]:
    rewards = []
    row_idx = 0
    for page_num_0 in pages:
        page_num = page_num_0 + 1
        text = pages_text[page_num_0]
        for line in text.split("\n"):
            line = line.strip()
            m = _REWARD_RE.match(line)
            if not m:
                continue
            dt = _parse_datetime(m.group(1))
            asset = m.group(2)
            qty = _parse_decimal(m.group(3))
            price = _parse_decimal(m.group(4))
            reward_type = m.group(5)
            tail = m.group(6).strip()
            description, wallet = _split_description_wallet(tail, [])

            if any(v is None for v in [dt, qty, price]):
                continue

            rewards.append(CryptoReward(
                date=dt,
                asset=asset,
                quantity=qty,
                price_eur=price,
                reward_type=reward_type,
                description=description,
                wallet=wallet,
                source=SourceRef(
                    file=filename,
                    page=page_num,
                    row=row_idx,
                    section="Operaciones de rendimientos",
                ),
            ))
            row_idx += 1
    return rewards


def parse(pdf_path: Path) -> KoinlyData:
    filename = pdf_path.name
    data = KoinlyData()

    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [p.extract_text() or "" for p in pdf.pages]

    summary = _extract_summary(pages_text)
    data.summary_net_gains_eur = summary.get("net_gains")
    data.summary_rewards_eur = summary.get("rewards")

    section_pages = _find_section_pages(pages_text)

    if "capital_gains" in section_pages:
        data.capital_gains = _parse_capital_gains(
            section_pages["capital_gains"], pages_text, filename
        )

    if "rewards" in section_pages:
        data.rewards = _parse_rewards(
            section_pages["rewards"], pages_text, filename
        )

    return data


def validate(data: KoinlyData) -> list[str]:
    warnings = []
    tolerance = Decimal("0.10")

    if data.summary_net_gains_eur is not None and data.capital_gains:
        parsed = sum((g.gain_loss_eur for g in data.capital_gains), Decimal("0"))
        diff = abs(parsed - data.summary_net_gains_eur)
        if diff > tolerance:
            warnings.append(
                f"Koinly ganancias crypto: total parseado €{parsed:.2f} ≠ "
                f"resumen PDF €{data.summary_net_gains_eur:.2f} (diff €{diff:.2f})"
            )

    if data.summary_rewards_eur is not None and data.rewards:
        parsed = sum((r.price_eur for r in data.rewards), Decimal("0"))
        diff = abs(parsed - data.summary_rewards_eur)
        if diff > tolerance:
            warnings.append(
                f"Koinly rendimientos/staking: total parseado €{parsed:.2f} ≠ "
                f"resumen PDF €{data.summary_rewards_eur:.2f} (diff €{diff:.2f})"
            )

    return warnings


# ---------------------------------------------------------------------------
# Funciones del contrato de parser (usadas por el registry)
# ---------------------------------------------------------------------------

def detect(first_page_text: str) -> bool:
    """Devuelve True si el PDF pertenece a Koinly."""
    return "koinly" in first_page_text.lower()


def stats_summary(data: KoinlyData) -> str:
    """Resumen de una línea para la salida del CLI tras parsear."""
    return f"{len(data.capital_gains)} ganancias crypto, {len(data.rewards)} rewards"


def year_hint(data: KoinlyData) -> int | None:
    """Devuelve el año fiscal de los datos, o None si no hay transacciones."""
    if data.capital_gains:
        return data.capital_gains[0].date_sold.year
    if data.rewards:
        return data.rewards[0].date.year
    return None


def usd_dates(data: KoinlyData) -> set:
    """Koinly ya provee los datos en EUR, no se necesitan conversiones USD→EUR."""
    return set()
