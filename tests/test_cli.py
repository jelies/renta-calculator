import sys
import pytest
from unittest.mock import MagicMock, patch

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


# ── Tests de despacho de subcomandos ──────────────────────────────────────────

class TestMainDispatch:
    """Verifica que main() enruta cada subcomando al handler correcto."""

    def _run_main(self, argv: list[str]):
        """Ejecuta main() con sys.argv parcheado, capturando SystemExit."""
        from renta.cli import main
        with patch.object(sys, "argv", ["renta-calculator"] + argv):
            with pytest.raises(SystemExit) as exc:
                main()
        return exc.value.code

    def test_download_trades_enruta_a_cmd_download(self):
        """download-trades llama a _cmd_download (stub de run_download y build_ledger)."""
        with patch("renta.fidelity_download.run_download", return_value=0) as mock_dl, \
             patch("renta.fidelity_ledger.build_ledger", return_value=0):
            code = self._run_main(["download-trades", "--years", "2024"])
        assert code == 0
        mock_dl.assert_called_once()

    def test_generate_ledger_enruta_a_cmd_ledger(self, tmp_path):
        """generate-ledger llama a build_ledger con la carpeta indicada."""
        # Necesita una carpeta válida para que argparse no falle en validaciones internas
        with patch("renta.fidelity_ledger.build_ledger", return_value=0) as mock_lg:
            code = self._run_main(["generate-ledger", "--input", str(tmp_path)])
        assert code == 0
        mock_lg.assert_called_once_with(
            input_dir=str(tmp_path),
            out=None,
            to_stdout=False,
        )

    def test_sin_subcomando_enruta_a_report(self):
        """Sin subcomando explícito, main() invoca cmd_calcular (comportamiento anterior)."""
        with patch("renta.cli.cmd_calcular") as mock_calc:
            with patch.object(sys, "argv", ["renta-calculator", "-i", "/alguna/carpeta"]):
                from renta.cli import main
                main()
        mock_calc.assert_called_once()

    def test_report_explicito_enruta_a_report(self):
        """'report' explícito también invoca cmd_calcular."""
        with patch("renta.cli.cmd_calcular") as mock_calc:
            with patch.object(sys, "argv", ["renta-calculator", "report", "-i", "/alguna/carpeta"]):
                from renta.cli import main
                main()
        mock_calc.assert_called_once()
