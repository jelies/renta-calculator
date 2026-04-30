"""
Generador del informe HTML autocontenido.

- CSS inline, sin JS, sin dependencias externas
- Imprimible
- Usa <details>/<summary> para las secciones de detalle largas (staking rewards)
"""

import re
from datetime import datetime
from decimal import Decimal
from importlib.resources import files

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from renta.models import ResultadoRenta


def _filter_color_class(amount: Decimal | None) -> str:
    if amount is None or amount == 0:
        return "zero"
    return "gain" if amount > 0 else "loss"


def _filter_format_num(amount: Decimal) -> str:
    s = f"{amount:,.2f}"
    return s.replace(",", "·").replace(".", ",").replace("·", ".")


def _filter_format_qty(amount: Decimal) -> str:
    s = f"{amount:,}"
    return s.replace(",", "·").replace(".", ",").replace("·", ".")


def _filter_clipboard_value_str(eur_str: str) -> str:
    return eur_str.replace("€", "").strip()


def _filter_nl2br(text: str) -> Markup:
    return Markup.escape(text).replace("\n", Markup("<br>"))


def _filter_casilla_inline(text: str) -> Markup:
    """Sustituye 'casilla(s) NNNN' por el badge HTML inline."""
    def _replace(m: re.Match) -> str:
        prefix = m.group(1)
        num = int(m.group(2))
        return f'{prefix} <span class="casilla-badge">{num:04d}</span>'
    escaped = str(Markup.escape(text))
    return Markup(re.sub(r'(casillas?)\s+(\d{4})', _replace, escaped, flags=re.IGNORECASE))


def _create_env() -> Environment:
    env = Environment(
        loader=PackageLoader("renta", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["color_class"] = _filter_color_class
    env.filters["format_num"] = _filter_format_num
    env.filters["format_qty"] = _filter_format_qty
    env.filters["clipboard_value_str"] = _filter_clipboard_value_str
    env.filters["nl2br"] = _filter_nl2br
    env.filters["casilla_inline"] = _filter_casilla_inline
    return env


def _build_context(result: ResultadoRenta) -> dict:
    css = (files("renta") / "report.css").read_text(encoding="utf-8")

    return {
        "result": result,
        "year": result.year,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "css": css,
    }


def generate(result: ResultadoRenta) -> str:
    env = _create_env()
    template = env.get_template("report.html")
    ctx = _build_context(result)
    return template.render(**ctx)
