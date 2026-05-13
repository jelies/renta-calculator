"""Formateo de números e importes en estilo español (1.234,56)."""

import os
import sys
from decimal import Decimal

_RESET = "\x1b[0m"
_CODES = {
    "red":      "\x1b[31m",
    "yellow":   "\x1b[33m",
    "green":    "\x1b[32m",
    "cyan":     "\x1b[36m",
    "bold":     "\x1b[1m",
    "dim":      "\x1b[2m",
    "primary":  "\x1b[38;2;41;128;185m",  # #2980b9 — azul claro, visible en fondo oscuro y claro
}


def _color_enabled(stream) -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if "FORCE_COLOR" in os.environ:
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _wrap(code: str, s: str, stream) -> str:
    return f"{code}{s}{_RESET}" if _color_enabled(stream) else s


def red(s: str, stream=sys.stderr) -> str:
    return _wrap(_CODES["red"], s, stream)


def yellow(s: str, stream=sys.stderr) -> str:
    return _wrap(_CODES["yellow"], s, stream)


def green(s: str, stream=sys.stdout) -> str:
    return _wrap(_CODES["green"], s, stream)


def cyan(s: str, stream=sys.stdout) -> str:
    return _wrap(_CODES["cyan"], s, stream)


def bold(s: str, stream=sys.stdout) -> str:
    return _wrap(_CODES["bold"], s, stream)


def dim(s: str, stream=sys.stdout) -> str:
    return _wrap(_CODES["dim"], s, stream)


def primary(s: str, stream=sys.stdout) -> str:
    """Azul oscuro #1a5276 — igual que --primary del report HTML."""
    return _wrap(_CODES["primary"], s, stream)


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
