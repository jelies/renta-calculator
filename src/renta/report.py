"""
Generador del informe HTML autocontenido.

- CSS inline, sin JS, sin dependencias externas
- Imprimible
- Usa <details>/<summary> para las secciones de detalle largas (staking rewards)
"""

from datetime import datetime
from decimal import Decimal
from importlib.resources import files

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from renta.models import KoinlyData, ResultadoRenta


def _filter_color_class(amount: Decimal | None) -> str:
    if amount is None or amount == 0:
        return "zero"
    return "gain" if amount > 0 else "loss"


def _filter_format_num(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def _filter_clipboard_value(amount: Decimal) -> str:
    return f"{abs(amount):.2f}".replace(".", ",")


def _filter_clipboard_value_str(eur_str: str) -> str:
    """Convierte un string como '1,234.56€' o '-99.50€' al formato portapapeles '1234,56'."""
    clean = eur_str.replace("€", "").replace(",", "").replace("+", "").replace("-", "").strip()
    return clean.replace(".", ",")


def _filter_nl2br(text: str) -> Markup:
    return Markup.escape(text).replace("\n", Markup("<br>"))


def _create_env() -> Environment:
    env = Environment(
        loader=PackageLoader("renta", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["color_class"] = _filter_color_class
    env.filters["format_num"] = _filter_format_num
    env.filters["clipboard_value"] = _filter_clipboard_value
    env.filters["clipboard_value_str"] = _filter_clipboard_value_str
    env.filters["nl2br"] = _filter_nl2br
    return env


def _build_context(result: ResultadoRenta, koinly: KoinlyData | None) -> dict:
    ventas_total_cost = Decimal(0)
    ventas_total_proceeds = Decimal(0)
    if result.ganancias_acciones:
        for item in result.ganancias_acciones.desglose:
            if "coste_eur" in item.extras and not item.error:
                ventas_total_cost += Decimal(
                    item.extras["coste_eur"].replace("€", "").replace(",", "")
                )
            if "ingresos_eur" in item.extras and not item.error:
                ventas_total_proceeds += Decimal(
                    item.extras["ingresos_eur"].replace("€", "").replace(",", "")
                )

    rendimientos_total_ops = 0
    if result.rendimientos_crypto:
        rendimientos_total_ops = sum(
            int(item.extras.get("num_operaciones", 0))
            for item in result.rendimientos_crypto.desglose
        )

    css = (files("renta") / "report.css").read_text(encoding="utf-8")

    return {
        "result": result,
        "year": result.year,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "css": css,
        "koinly_rewards": koinly.rewards if koinly else [],
        "ventas_total_cost": ventas_total_cost,
        "ventas_total_proceeds": ventas_total_proceeds,
        "rendimientos_total_ops": rendimientos_total_ops,
    }


def generate(result: ResultadoRenta, koinly: KoinlyData | None = None) -> str:
    env = _create_env()
    template = env.get_template("report.html")
    ctx = _build_context(result, koinly)
    return template.render(**ctx)
