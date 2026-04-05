from renta.parsers import fidelity, koinly

# Registry de parsers disponibles.
# Cada módulo debe exponer: detect(), parse(), validate(), stats_summary(), year_hint(), usd_dates()
# Para añadir un nuevo parser: crear el módulo y añadir una línea aquí.
REGISTRY: list[tuple[str, object]] = [
    ("fidelity", fidelity),
    ("koinly", koinly),
]
