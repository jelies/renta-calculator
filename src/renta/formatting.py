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


def format_crypto_qty(qty: Decimal) -> str:
    """Formatea una cantidad de crypto eliminando ceros finales y aplicando estilo español.

    Ejemplos: 2.0000 → "2", 0.00006762 → "0,00006762", 12345.5 → "12.345,5"
    """
    if qty == qty.to_integral_value():
        return format_es_number(qty, decimals=0)
    s = f"{qty:f}"
    if "." in s:
        s = s.rstrip("0")
    int_str, _, dec_str = s.partition(".")
    int_formatted = f"{int(int_str):,}".replace(",", ".")
    return f"{int_formatted},{dec_str}"
