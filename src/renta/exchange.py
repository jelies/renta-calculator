"""
Cliente para obtener tipos de cambio históricos del BCE (Banco Central Europeo).

El BCE publica el tipo de referencia USD/EUR diario. La API devuelve CSV con
el formato: TIME_PERIOD,OBS_VALUE donde OBS_VALUE es el número de USD por 1 EUR.

Para convertir USD a EUR: eur = usd / rate
Para convertir EUR a USD: usd = eur * rate

Los fines de semana y festivos no tienen tipo publicado. En esos casos se usa
el tipo del último día hábil anterior.
"""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import requests

_BCE_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
    "?startPeriod={start}&endPeriod={end}&format=csvdata"
)

# Caché en memoria para la sesión actual: {(start, end): {date: Decimal}}
_cache: dict[tuple[str, str], dict[date, Decimal]] = {}


def _fetch_rates(start: date, end: date) -> dict[date, Decimal]:
    """Descarga los tipos de cambio del BCE para el rango dado."""
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    cache_key = (start_str, end_str)

    if cache_key in _cache:
        return _cache[cache_key]

    url = _BCE_URL.format(start=start_str, end=end_str)
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    rates: dict[date, Decimal] = {}
    reader = csv.DictReader(io.StringIO(response.text))
    for row in reader:
        period = row.get("TIME_PERIOD", "").strip()
        value = row.get("OBS_VALUE", "").strip()
        if not period or not value:
            continue
        try:
            d = date.fromisoformat(period)
            rates[d] = Decimal(value)
        except (ValueError, Exception):
            continue

    _cache[cache_key] = rates
    return rates


class ExchangeRateProvider:
    """
    Proveedor de tipos de cambio USD/EUR del BCE.

    Uso:
        provider = ExchangeRateProvider.for_year(2024)
        eur_amount, rate = provider.usd_to_eur(Decimal("100"), some_date)
    """

    def __init__(self, rates: dict[date, Decimal]):
        self._rates = rates
        # Días ordenados para el fallback
        self._sorted_days = sorted(rates.keys())

    @classmethod
    def for_year(cls, year: int) -> "ExchangeRateProvider":
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        rates = _fetch_rates(start, end)
        if not rates:
            raise RuntimeError(
                f"No se pudieron obtener tipos de cambio del BCE para el año {year}. "
                "Comprueba la conexión a internet."
            )
        return cls(rates)

    @classmethod
    def for_dates(cls, dates: set[date]) -> "ExchangeRateProvider":
        """Descarga tipos para el rango mínimo necesario para cubrir las fechas dadas."""
        if not dates:
            return cls({})
        min_date = min(dates)
        max_date = max(dates)
        # Ampliar el rango algunos días antes por si hay fines de semana al inicio
        start = min_date - timedelta(days=7)
        end = max_date
        rates = _fetch_rates(start, end)
        return cls(rates)

    def get_rate(self, on_date: date) -> tuple[Decimal, date]:
        """
        Devuelve (tipo_de_cambio, fecha_efectiva).
        Si on_date es festivo/fin de semana, retrocede al último día hábil.
        Lanza ValueError si no hay ningún tipo disponible.
        """
        if on_date in self._rates:
            return self._rates[on_date], on_date

        # Buscar el último día hábil anterior
        d = on_date - timedelta(days=1)
        for _ in range(14):  # máximo 2 semanas atrás
            if d in self._rates:
                return self._rates[d], d
            d -= timedelta(days=1)

        raise ValueError(
            f"No hay tipo de cambio BCE disponible para {on_date} "
            f"ni en los 14 días anteriores."
        )

    def usd_to_eur(self, amount_usd: Decimal, on_date: date) -> tuple[Decimal, Decimal, date]:
        """
        Convierte USD a EUR usando el tipo BCE de on_date.

        Devuelve (amount_eur, rate, fecha_efectiva_del_tipo).
        """
        rate, effective_date = self.get_rate(on_date)
        amount_eur = (amount_usd / rate).quantize(Decimal("0.01"))
        return amount_eur, rate, effective_date

    def all_rates_used(self) -> dict[date, Decimal]:
        """Devuelve todos los tipos que están en la caché interna."""
        return dict(self._rates)
