"""Tests para renta.fidelity_ledger (subcomando generate-ledger)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from renta.fidelity_ledger import _find_pdfs, build_ledger


class TestFindPdfs:
    def test_sin_pdfs_devuelve_lista_vacia(self, tmp_path: Path):
        assert _find_pdfs(tmp_path) == []

    def test_encuentra_pdfs_recursivamente(self, tmp_path: Path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "a.pdf").touch()
        (sub / "b.pdf").touch()
        result = _find_pdfs(tmp_path)
        assert len(result) == 2

    def test_solo_pdfs_no_otros_tipos(self, tmp_path: Path):
        (tmp_path / "a.pdf").touch()
        (tmp_path / "b.csv").touch()
        (tmp_path / "c.txt").touch()
        result = _find_pdfs(tmp_path)
        assert result == [tmp_path / "a.pdf"]

    def test_orden_alfabetico(self, tmp_path: Path):
        (tmp_path / "c.pdf").touch()
        (tmp_path / "a.pdf").touch()
        (tmp_path / "b.pdf").touch()
        result = _find_pdfs(tmp_path)
        assert result == [tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"]


class TestBuildLedger:
    def test_error_si_directorio_no_existe(self, tmp_path: Path):
        code = build_ledger(input_dir=tmp_path / "no_existe")
        assert code == 1

    def test_error_si_no_hay_pdfs(self, tmp_path: Path):
        code = build_ledger(input_dir=tmp_path)
        assert code == 1

    def test_error_si_build_rows_no_extrae_filas(self, tmp_path: Path):
        """Si hay PDFs pero build_rows devuelve 0 filas, debe retornar 1."""
        (tmp_path / "dummy.pdf").write_bytes(b"%PDF-fake")
        with patch("renta.fidelity_ledger.build_ledger") as mock:
            # Probamos la lógica interna: stub de build_rows devuelve lista vacía
            pass  # cobertura básica ya la dan los tests de integración de parsers

        # Test real: build_rows retorna vacío para un PDF inválido
        from unittest.mock import patch as _patch
        with _patch("renta.parsers.fidelity_confirmations.build_rows", return_value=([], [])):
            code = build_ledger(input_dir=tmp_path)
        assert code == 1

    def _make_fake_row(self, fecha=None):
        """Helper: crea un LedgerRow mínimo para tests."""
        from renta.parsers.fidelity_confirmations import LedgerRow
        import datetime
        return LedgerRow(
            fecha=fecha or datetime.date(2024, 3, 12),
            ticker="AAPL",
            tipo="adquisicion",
            cantidad=10.0,
            precio_usd=150.0,
            fmv_derivado=False,
            source="fake.pdf",
        )

    def test_genera_csv_con_filas_validas(self, tmp_path: Path):
        """Con build_rows y rows_to_csv mockeados, debe escribir el CSV y retornar 0."""
        fake_row = self._make_fake_row()

        (tmp_path / "dummy.pdf").write_bytes(b"%PDF-fake")

        csv_content = (
            "fecha,ticker,tipo,cantidad,precio_usd\n"
            "2024-03-12,AAPL,adquisicion,10.0,150.0\n"
        )

        with patch("renta.parsers.fidelity_confirmations.build_rows", return_value=([fake_row], [])), \
             patch("renta.parsers.fidelity_confirmations.rows_to_csv", return_value=csv_content), \
             patch("renta.parsers.fidelity_fifo.parse_ledger") as mock_parse, \
             patch("renta.parsers.fidelity_fifo.compute_fifo", return_value=([], [])):

            import datetime as _dt
            mock_entry = MagicMock()
            mock_entry.tipo = "adquisicion"
            mock_entry.fecha = _dt.date(2024, 3, 12)
            mock_parse.return_value = [mock_entry]

            out_csv = tmp_path / "fidelity_ledger.csv"
            code = build_ledger(input_dir=tmp_path, out=out_csv)

        assert code == 0
        assert out_csv.exists()

    def test_default_escribe_en_output_raiz_con_fecha(self, tmp_path: Path, monkeypatch):
        """Sin --out, el CSV se escribe en output/ raíz con la fecha de la operación más reciente."""
        import datetime
        fake_row = self._make_fake_row(fecha=datetime.date(2024, 8, 15))

        (tmp_path / "dummy.pdf").write_bytes(b"%PDF-fake")

        csv_content = "fecha,ticker,tipo,cantidad,precio_usd\n2024-08-15,AAPL,adquisicion,10,150.0\n"

        monkeypatch.chdir(tmp_path)  # "output/" se crea dentro de tmp_path

        with patch("renta.parsers.fidelity_confirmations.build_rows", return_value=([fake_row], [])), \
             patch("renta.parsers.fidelity_confirmations.rows_to_csv", return_value=csv_content), \
             patch("renta.parsers.fidelity_fifo.parse_ledger") as mock_parse, \
             patch("renta.parsers.fidelity_fifo.compute_fifo", return_value=([], [])):

            mock_entry = MagicMock()
            mock_entry.tipo = "adquisicion"
            mock_entry.fecha = datetime.date(2024, 8, 15)
            mock_parse.return_value = [mock_entry]

            code = build_ledger(input_dir=tmp_path)

        assert code == 0
        expected = tmp_path / "output" / "fidelity_ledger_2024.08.15.csv"
        assert expected.exists(), f"No se creó el fichero esperado: {expected}"
        # No debe haber CSV en la carpeta de entrada
        assert not list(tmp_path.glob("fidelity_ledger*.csv"))

    def test_stdout_no_escribe_fichero(self, tmp_path: Path, monkeypatch):
        """Con to_stdout=True, retorna 0 sin crear fichero CSV en disco."""
        import datetime
        fake_row = self._make_fake_row()
        csv_content = "fecha,ticker,tipo,cantidad,precio_usd\n2024-03-12,AAPL,adquisicion,10.0,150.0\n"

        (tmp_path / "dummy.pdf").write_bytes(b"%PDF-fake")

        monkeypatch.chdir(tmp_path)

        with patch("renta.parsers.fidelity_confirmations.build_rows", return_value=([fake_row], [])), \
             patch("renta.parsers.fidelity_confirmations.rows_to_csv", return_value=csv_content):
            code = build_ledger(input_dir=tmp_path, to_stdout=True)

        assert code == 0
        # No debe haber creado ningún CSV en disco (ni en input ni en output/)
        assert not list(tmp_path.glob("**/*.csv"))


# ── Necesario para el test de integración con mock ───────────────────────────
from unittest.mock import MagicMock  # noqa: E402
