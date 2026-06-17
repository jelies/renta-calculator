"""Tests para el cálculo FIFO de ventas de acciones de Fidelity."""

from datetime import date
from decimal import Decimal

import pytest

from renta.parsers import fidelity_fifo


def _write_csv(tmp_path, body: str):
    p = tmp_path / "ledger.csv"
    p.write_text(body, encoding="utf-8")
    return p


_HEADER = "fecha,ticker,tipo,cantidad,precio_usd\n"


# ---------------------------------------------------------------------------
# parse_ledger
# ---------------------------------------------------------------------------


class TestParseLedger:
    def test_parsea_filas_validas(self, tmp_path):
        csv = _write_csv(tmp_path, _HEADER + "2020-05-05,ORCL,adquisicion,15,52.10\n")
        entries = fidelity_fifo.parse_ledger(csv)
        assert len(entries) == 1
        e = entries[0]
        assert e.fecha == date(2020, 5, 5)
        assert e.ticker == "ORCL"
        assert e.tipo == "adquisicion"
        assert e.cantidad == Decimal("15")
        assert e.precio_usd == Decimal("52.10")
        assert e.row == 2

    def test_ignora_comentarios_y_lineas_en_blanco(self, tmp_path):
        body = (
            "# comentario\n"
            "\n"
            + _HEADER
            + "2020-05-05,orcl,VENTA,10,100\n"
        )
        entries = fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))
        assert len(entries) == 1
        assert entries[0].ticker == "ORCL"  # normalizado a mayúsculas
        assert entries[0].tipo == "venta"   # normalizado
        # nº de línea original conservado (comentario=1, blanco=2, header=3, dato=4)
        assert entries[0].row == 4

    def test_acepta_alias_de_tipo(self, tmp_path):
        body = _HEADER + "2020-05-05,ORCL,vesting,1,1\n2021-05-05,ORCL,compra,1,1\n"
        entries = fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))
        assert [e.tipo for e in entries] == ["adquisicion", "adquisicion"]

    def test_fichero_inexistente(self, tmp_path):
        with pytest.raises(ValueError, match="No se encontró"):
            fidelity_fifo.parse_ledger(tmp_path / "no_existe.csv")

    def test_fichero_vacio(self, tmp_path):
        with pytest.raises(ValueError, match="vacío"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, "# solo comentarios\n"))

    def test_cabeceras_invalidas(self, tmp_path):
        body = "fecha,ticker,tipo,cantidad\n2020-05-05,ORCL,venta,1\n"
        with pytest.raises(ValueError, match="Cabeceras"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))

    def test_fecha_invalida(self, tmp_path):
        body = _HEADER + "05/05/2020,ORCL,venta,1,1\n"
        with pytest.raises(ValueError, match="fecha inválida"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))

    def test_tipo_invalido(self, tmp_path):
        body = _HEADER + "2020-05-05,ORCL,dividendo,1,1\n"
        with pytest.raises(ValueError, match="tipo inválido"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))

    def test_cantidad_no_numerica(self, tmp_path):
        body = _HEADER + "2020-05-05,ORCL,venta,abc,1\n"
        with pytest.raises(ValueError, match="no numéricos"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))

    def test_cantidad_no_positiva(self, tmp_path):
        body = _HEADER + "2020-05-05,ORCL,venta,0,1\n"
        with pytest.raises(ValueError, match="cantidad debe ser"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))

    def test_precio_negativo(self, tmp_path):
        body = _HEADER + "2020-05-05,ORCL,venta,1,-5\n"
        with pytest.raises(ValueError, match="no puede ser negativo"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))

    def test_numero_columnas_incorrecto(self, tmp_path):
        body = _HEADER + "2020-05-05,ORCL,venta,1\n"
        with pytest.raises(ValueError, match="columnas"):
            fidelity_fifo.parse_ledger(_write_csv(tmp_path, body))


# ---------------------------------------------------------------------------
# compute_fifo
# ---------------------------------------------------------------------------


def _entries(*rows) -> list:
    """rows: tuplas (fecha_iso, ticker, tipo, cantidad, precio)."""
    out = []
    for i, (f, t, tp, c, p) in enumerate(rows, start=1):
        out.append(fidelity_fifo.LedgerEntry(
            fecha=date.fromisoformat(f),
            ticker=t,
            tipo=tp,
            cantidad=Decimal(c),
            precio_usd=Decimal(p),
            row=i,
        ))
    return out


class TestComputeFifo:
    def test_lote_completo_un_fragmento(self):
        entries = _entries(
            ("2020-05-05", "ORCL", "adquisicion", "10", "50"),
            ("2024-03-12", "ORCL", "venta", "10", "120"),
        )
        frags, errores = fidelity_fifo.compute_fifo(entries, 2024)
        assert errores == []
        assert len(frags) == 1
        f = frags[0]
        assert f.date_acquired == date(2020, 5, 5)
        assert f.date_sold == date(2024, 3, 12)
        assert f.quantity == Decimal("10")
        assert f.cost_basis_usd == Decimal("500")
        assert f.proceeds_usd == Decimal("1200")

    def test_venta_multi_lote_se_divide(self):
        # Una venta que abarca varios lotes se divide en un fragmento por lote
        entries = _entries(
            ("2020-05-05", "ORCL", "adquisicion", "15", "52.10"),
            ("2021-05-05", "ORCL", "adquisicion", "12", "68.40"),
            ("2022-05-05", "ORCL", "adquisicion", "10", "77.25"),
            ("2024-03-12", "ORCL", "venta", "20", "126.25"),
            ("2024-09-23", "ORCL", "venta", "5", "118.40"),
        )
        frags, errores = fidelity_fifo.compute_fifo(entries, 2024)
        assert errores == []
        assert len(frags) == 3
        # Fragmento 1: lote 2020 completo (15)
        assert frags[0].date_acquired == date(2020, 5, 5)
        assert frags[0].quantity == Decimal("15")
        assert frags[0].cost_basis_usd == Decimal("781.50")
        assert frags[0].proceeds_usd == Decimal("1893.75")
        # Fragmento 2: 5 del lote 2021, misma venta de marzo
        assert frags[1].date_acquired == date(2021, 5, 5)
        assert frags[1].date_sold == date(2024, 3, 12)
        assert frags[1].quantity == Decimal("5")
        assert frags[1].cost_basis_usd == Decimal("342.00")
        # Fragmento 3: 5 del lote 2021, venta de septiembre
        assert frags[2].date_acquired == date(2021, 5, 5)
        assert frags[2].date_sold == date(2024, 9, 23)
        assert frags[2].quantity == Decimal("5")
        assert frags[2].proceeds_usd == Decimal("592.00")

    def test_inventario_insuficiente_genera_error_sin_fragmento(self):
        entries = _entries(
            ("2020-05-05", "ORCL", "adquisicion", "5", "50"),
            ("2024-03-12", "ORCL", "venta", "10", "120"),
        )
        frags, errores = fidelity_fifo.compute_fifo(entries, 2024)
        assert frags == []
        assert len(errores) == 1
        assert "inventario FIFO insuficiente" in errores[0]
        assert "faltan 5" in errores[0]

    def test_consumo_de_venta_de_anio_anterior_afecta_inventario(self):
        # Venta 2023 consume el lote más antiguo; la venta 2024 debe usar el siguiente lote (FIFO entre años)
        entries = _entries(
            ("2020-05-05", "ORCL", "adquisicion", "10", "50"),
            ("2021-05-05", "ORCL", "adquisicion", "10", "80"),
            ("2023-06-01", "ORCL", "venta", "10", "100"),   # consume lote 2020, no se reporta
            ("2024-03-12", "ORCL", "venta", "10", "120"),   # debe consumir lote 2021
        )
        frags, errores = fidelity_fifo.compute_fifo(entries, 2024)
        assert errores == []
        assert len(frags) == 1
        assert frags[0].date_acquired == date(2021, 5, 5)
        assert frags[0].cost_basis_usd == Decimal("800")  # 10 * 80

    def test_solo_reporta_ventas_del_anio_fiscal(self):
        entries = _entries(
            ("2020-05-05", "ORCL", "adquisicion", "20", "50"),
            ("2024-03-12", "ORCL", "venta", "5", "120"),
            ("2025-03-12", "ORCL", "venta", "5", "130"),
        )
        frags, _ = fidelity_fifo.compute_fifo(entries, 2024)
        assert len(frags) == 1
        assert frags[0].date_sold == date(2024, 3, 12)

    def test_fifo_por_ticker_independiente(self):
        entries = _entries(
            ("2020-05-05", "AAA", "adquisicion", "10", "10"),
            ("2020-05-05", "BBB", "adquisicion", "10", "20"),
            ("2024-03-12", "AAA", "venta", "10", "15"),
            ("2024-03-12", "BBB", "venta", "10", "25"),
        )
        frags, errores = fidelity_fifo.compute_fifo(entries, 2024)
        assert errores == []
        tickers = {f.ticker for f in frags}
        assert tickers == {"AAA", "BBB"}

    def test_adquisicion_mismo_dia_disponible_para_venta(self):
        # En empate de fecha, la adquisición se ordena antes que la venta
        entries = _entries(
            ("2024-03-12", "ORCL", "adquisicion", "10", "50"),
            ("2024-03-12", "ORCL", "venta", "10", "120"),
        )
        frags, errores = fidelity_fifo.compute_fifo(entries, 2024)
        assert errores == []
        assert len(frags) == 1

    def test_source_ref_apunta_a_la_linea_de_venta(self):
        entries = _entries(
            ("2020-05-05", "ORCL", "adquisicion", "10", "50"),
            ("2024-03-12", "ORCL", "venta", "10", "120"),
        )
        frags, _ = fidelity_fifo.compute_fifo(entries, 2024, csv_file="/x/ledger.csv")
        assert frags[0].source.file == "/x/ledger.csv"
        assert frags[0].source.section == "ledger FIFO"
        # row=1 (0-based) → SourceRef muestra fila 2 (la venta está en la línea 2)
        assert frags[0].source.row == 1


# ---------------------------------------------------------------------------
# usd_dates
# ---------------------------------------------------------------------------


def test_usd_dates_incluye_adquisicion_y_venta():
    entries = _entries(
        ("2020-05-05", "ORCL", "adquisicion", "10", "50"),
        ("2024-03-12", "ORCL", "venta", "10", "120"),
    )
    frags, _ = fidelity_fifo.compute_fifo(entries, 2024)
    assert fidelity_fifo.usd_dates(frags) == {date(2020, 5, 5), date(2024, 3, 12)}
