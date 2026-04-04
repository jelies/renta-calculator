"""Fixtures compartidas para los tests."""

from datetime import date
from decimal import Decimal

import pytest

from renta.exchange import ExchangeRateProvider

# Tipos de cambio de referencia: 1.25 USD por 1 EUR, días laborables
DEFAULT_RATES: dict[date, Decimal] = {
    date(2024, 1, 2): Decimal("1.2500"),
    date(2024, 1, 3): Decimal("1.2500"),
    date(2024, 1, 4): Decimal("1.2500"),
    date(2024, 1, 5): Decimal("1.2500"),
    date(2024, 1, 8): Decimal("1.2500"),
    date(2024, 1, 9): Decimal("1.2500"),
    date(2024, 1, 10): Decimal("1.2500"),
    date(2024, 1, 11): Decimal("1.2500"),
    date(2024, 1, 12): Decimal("1.2500"),
    date(2024, 1, 15): Decimal("1.2500"),
    date(2024, 1, 16): Decimal("1.2500"),
    date(2024, 1, 17): Decimal("1.2500"),
    date(2024, 1, 18): Decimal("1.2500"),
    date(2024, 1, 19): Decimal("1.2500"),
    date(2024, 3, 12): Decimal("1.2500"),
    date(2024, 5, 5): Decimal("1.2500"),
    date(2020, 5, 5): Decimal("1.2500"),
}


@pytest.fixture
def provider():
    """ExchangeRateProvider con tipos fijos 1.25, sin red."""
    return ExchangeRateProvider(DEFAULT_RATES)


@pytest.fixture
def empty_provider():
    """ExchangeRateProvider sin tipos — cualquier consulta falla."""
    return ExchangeRateProvider({})
