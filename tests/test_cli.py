import pytest
from unittest.mock import MagicMock

from renta.cli import _detect_year
from renta.parsers import REGISTRY


def _make_module(hint):
    m = MagicMock()
    m.year_hint.return_value = hint
    return m


def test_detect_year_returns_hint_from_first_matching_parser():
    parsed_data = {REGISTRY[0][0]: object()}
    original_module = REGISTRY[0][1]
    mock_module = _make_module(2025)
    REGISTRY[0] = (REGISTRY[0][0], mock_module, REGISTRY[0][2])
    try:
        assert _detect_year(parsed_data) == 2025
    finally:
        REGISTRY[0] = (REGISTRY[0][0], original_module, REGISTRY[0][2])


def test_detect_year_returns_none_when_no_hints():
    # Datos vacíos: ningún parser tiene datos parseados
    result = _detect_year({})
    assert result is None


def test_detect_year_returns_none_when_all_parsers_return_none():
    # Todos los parsers devuelven None como hint
    parsed_data = {}
    saved = []
    for i, (name, module, optional) in enumerate(REGISTRY):
        mock = _make_module(None)
        parsed_data[name] = object()
        saved.append((i, module))
        REGISTRY[i] = (name, mock, optional)
    try:
        assert _detect_year(parsed_data) is None
    finally:
        for i, original_module in saved:
            name, _, optional = REGISTRY[i]
            REGISTRY[i] = (name, original_module, optional)
