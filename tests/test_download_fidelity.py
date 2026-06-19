"""Tests para las utilidades de nombrado de scripts/download_fidelity.py."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from scripts.download_fidelity import parse_confirmation_date, unique_path


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
