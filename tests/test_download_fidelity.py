"""Tests para las utilidades de nombrado de renta.fidelity_download."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from renta.fidelity_download import parse_confirmation_date, parse_year_options, unique_path


# ── parse_confirmation_date ────────────────────────────────────────────────────

class TestParseConfirmationDate:
    def test_mes_abreviado(self):
        result = parse_confirmation_date("Trade Confirmation (pdf) May 5, 2022")
        assert result == datetime.date(2022, 5, 5)

    def test_mes_abreviado_un_digito(self):
        result = parse_confirmation_date("Trade Confirmation (pdf) Jan 3, 2024")
        assert result == datetime.date(2024, 1, 3)

    def test_mes_abreviado_dos_digitos(self):
        result = parse_confirmation_date("Trade Confirmation (pdf) Mar 12, 2024")
        assert result == datetime.date(2024, 3, 12)

    def test_mes_completo(self):
        result = parse_confirmation_date("Trade Confirmation (pdf) December 31, 2023")
        assert result == datetime.date(2023, 12, 31)

    def test_sin_prefijo(self):
        """Funciona aunque el texto empiece directamente por la fecha."""
        result = parse_confirmation_date("August 3, 2024")
        assert result == datetime.date(2024, 8, 3)

    def test_texto_sin_fecha(self):
        assert parse_confirmation_date("Trade Confirmation (pdf)") is None

    def test_texto_vacio(self):
        assert parse_confirmation_date("") is None

    def test_mes_invalido(self):
        assert parse_confirmation_date("Xyz 5, 2022") is None


# ── parse_year_options ────────────────────────────────────────────────────────

class TestParseYearOptions:
    def test_extrae_años_validos(self):
        result = parse_year_options(["2025", "2024", "2023"])
        assert result == [2025, 2024, 2023]

    def test_ignora_textos_no_año(self):
        result = parse_year_options(["2025", "2024", "Last 90 days", "Custom range", ""])
        assert result == [2025, 2024]

    def test_orden_descendente(self):
        result = parse_year_options(["2022", "2025", "2023", "2024"])
        assert result == [2025, 2024, 2023, 2022]

    def test_deduplica_años(self):
        result = parse_year_options(["2024", "2024", "2023"])
        assert result == [2024, 2023]

    def test_espacios_alrededor_del_año(self):
        result = parse_year_options(["  2024  ", "2023"])
        assert result == [2024, 2023]

    def test_lista_vacia(self):
        assert parse_year_options([]) == []

    def test_sin_años_en_la_lista(self):
        assert parse_year_options(["Last 90 days", "Custom range"]) == []


# ── unique_path ────────────────────────────────────────────────────────────────

class TestUniquePath:
    def test_sin_colision(self, tmp_path: Path):
        result = unique_path(tmp_path, "trade-confirmation-2022.05.05")
        assert result == tmp_path / "trade-confirmation-2022.05.05.pdf"

    def test_primera_colision_genera_001(self, tmp_path: Path):
        (tmp_path / "trade-confirmation-2022.05.05.pdf").touch()
        result = unique_path(tmp_path, "trade-confirmation-2022.05.05")
        assert result == tmp_path / "trade-confirmation-2022.05.05-001.pdf"

    def test_segunda_colision_genera_002(self, tmp_path: Path):
        (tmp_path / "trade-confirmation-2022.05.05.pdf").touch()
        (tmp_path / "trade-confirmation-2022.05.05-001.pdf").touch()
        result = unique_path(tmp_path, "trade-confirmation-2022.05.05")
        assert result == tmp_path / "trade-confirmation-2022.05.05-002.pdf"

    def test_sufijo_personalizado(self, tmp_path: Path):
        result = unique_path(tmp_path, "stem", suffix=".txt")
        assert result == tmp_path / "stem.txt"
