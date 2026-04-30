from renta.parsers import degiro, fidelity, koinly, koinly_spain

# Registry de parsers disponibles.
# Cada módulo debe exponer: detect(), parse(), validate(), stats_summary(), year_hint(), usd_dates()
# Para añadir un nuevo parser: crear el módulo y añadir una línea aquí.
# optional=True: no se emite aviso si el PDF no está presente.
REGISTRY: list[tuple[str, object, bool]] = [
    ("fidelity", fidelity, False),
    ("koinly", koinly, False),
    ("degiro", degiro, False),
    ("koinly_spain", koinly_spain, True),
]
