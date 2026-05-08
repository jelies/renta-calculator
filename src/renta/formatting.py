"""Formateo de números e importes en estilo español (1.234,56)."""

from decimal import Decimal


def format_es_number(amount: Decimal, decimals: int = 2) -> str:
    """Formatea con `.` como separador de miles y `,` como decimal."""
    sign = "-" if amount < 0 else ""
    int_part, _, dec_part = f"{abs(amount):,.{decimals}f}".partition(".")
    int_part = int_part.replace(",", ".")
    if dec_part:
        return f"{sign}{int_part},{dec_part}"
    return f"{sign}{int_part}"


def format_eur(amount: Decimal) -> str:
    return f"{format_es_number(amount)} €"


def format_usd(amount: Decimal) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}${format_es_number(abs(amount))}"


def format_rate(rate: Decimal) -> str:
    """Formatea un tipo de cambio con 4 decimales en estilo español (p.ej. 1,0782)."""
    return format_es_number(rate, decimals=4)
