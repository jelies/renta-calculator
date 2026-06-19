"""Tests para el parser de Trade Confirmations de Fidelity."""

from datetime import date
from decimal import Decimal

import pytest

from renta.parsers.fidelity_confirmations import (
    LedgerRow,
    _parse_us_date,
    parse_confirmation_text,
    build_rows,
    rows_to_csv,
)
from renta.parsers import fidelity_fifo


# ── Textos fixture (extraídos directamente de los PDFs reales) ────────────────

_VENTA_SIMPLE = (
    "PARTICIPANT NO.\nI01182756\n90047969\nJORDI ELIES VIDAL\nMERCE 38\nBADALONA\n"
    "BARCELONA FIDELITY STOCK PLAN SERVICES, LLC\nSPAIN 08911 P.O. BOX 770001\n"
    "CINCINNATI, OH 45277-0003\nTELEPHONE NUMBER:(800) 544-0275\n"
    "REF # 24072-0BXM7W\n"
    "CUSTOMER NO. PARTICIPANT ID. TYPE REG.REP. TRADE DATE SETTLEMENT DATE TRANS NO. CUSIP NO. ORIG.\n"
    "I01182756 1 WI# 03-12-24 03-14-24 0BXM7W 68389X105\n"
    "YOU SOLD 58 AT 126.2500\n"
    "EXPLANATION OF PROCEEDS\n"
    "SECURITY DESCRIPTION SYMBOL: ORCL Sale Proceeds $7,322.50\n"
    "ORACLE CORP\nDETAILS: Total Fees $0.06\n"
    "Sale Date: MAR/12/2024\n"
    "Proceeds Available: MAR/14/2024\nPlan Type: COMPANY STOCK PLAN\n"
    "Net Cash Proceeds¹ -$7,322.44\nPLEASE RETAIN THIS STATEMENT FOR YOUR RECORDS"
)

_VENTA_ASTERISCOS = (
    "PARTICIPANT NO.\nI01182756\n90035120\nJORDI ELIES VIDAL\nMERCE 38\nBADALONA\n"
    "BARCELONA FIDELITY STOCK PLAN SERVICES, LLC\nSPAIN 08911 P.O. BOX 770001\n"
    "CINCINNATI, OH 45277-0003\nTELEPHONE NUMBER:(800) 544-0275\n"
    "REF # 24270-M40K3N\n"
    "CUSTOMER NO. PARTICIPANT ID. TYPE REG.REP. TRADE DATE SETTLEMENT DATE TRANS NO. CUSIP NO. ORIG.\n"
    "I01182756 1 W## 09-26-24 09-27-24 2M471 68389X105\n"
    "YOU SOLD 8 AT 167.5992****\n"
    "EXPLANATION OF PROCEEDS\n"
    "SECURITY DESCRIPTION SYMBOL: ORCL Sale Proceeds $1,340.79\n"
    "ORACLE CORP\nDETAILS: Total Fees $0.04\n"
    "Sale Date: SEP/26/2024\n"
    "Proceeds Available: SEP/27/2024\nPlan Type: COMPANY STOCK PLAN\n"
    "Net Cash Proceeds¹ -$1,340.75\n"
    "**** Represents a weighted average price as multiple executions were involved."
)

_ADQ_SHARES_DEP = (
    "ORACLE CORPORATION TRANSACTION CONFIRMATION\nPARTICIPANT NO.\nI01182756\n90048803\n"
    "JORDI ELIES VIDAL\nMERCE 38\nBADALONA\n"
    "BARCELONA FIDELITY STOCK PLAN SERVICES, LLC\nSPAIN 08911 P.O. BOX 770001\n"
    "CINCINNATI, OH 45277-0003\nTELEPHONE NUMBER:(800) 544-0275\n"
    "REF # 24260-0G4ZFX\n"
    "CUSTOMER NO. PARTICIPANT ID. TYPE REG.REP. TRADE DATE SETTLEMENT DATE TRANS NO. CUSIP NO. ORIG.\n"
    "I01182756 1 000 09-16-24 09-17-24 0G4ZFX 68389X105\n"
    "9 SHARES WERE DISTRIBUTED TAX INFORMATION\n"
    "Shares Sold for Tax Withholding, Commission & Fees°: 5 Market Value at Distribution¹ $1,458.27\n"
    "Taxable Income² $1,458.27\nSale Price: 167.896900\n"
    "EXPLANATION OF PROCEEDS\nShares Distributed 9\n"
    "SECURITY DESCRIPTION SYMBOL: ORCL\nORACLE CORP\n"
    "SPAIN TAX ³ $612.47\nTotal Cost $612.47\nDISTRIBUTION DETAILS:\n"
    "Date of Grant: SEP/15/2023 Date of Distribution: SEP/15/2024\n"
    "Grant ID: 2020IOLRS Grant Type: RSU\n"
    "Fair Market Value: $162.03000 Shares Deposited 9"
)

_ADQ_NET_SHARES = (
    "ORACLE CORPORATION TRANSACTION CONFIRMATION\nPARTICIPANT NO.\nI01182756\n90047146\n"
    "JORDI ELIES VIDAL\nMERCE 38\nBADALONA\n"
    "BARCELONA FIDELITY STOCK PLAN SERVICES, LLC\nSPAIN 08911 P.O. BOX 770001\n"
    "CINCINNATI, OH 45277-0003\nTELEPHONE NUMBER:(800) 544-0275\n"
    "REF # 24218-0BKJJX\n"
    "CUSTOMER NO. PARTICIPANT ID. TYPE REG.REP. TRADE DATE SETTLEMENT DATE TRANS NO. CUSIP NO. ORIG.\n"
    "I01182756 1 000 08-05-24 08-06-24 0BKJJX 68389X105\n"
    "75 SHARES WERE DISTRIBUTED TAX INFORMATION\n"
    "Market Value at Distribution¹ $9,996.00\nTaxable Income² $9,996.00\n"
    "32 SHARES WERE NETTED TO COVER YOUR TAX\nWITHHOLDING\n"
    "EXPLANATION OF PROCEEDS\nShares Distributed 75\n"
    "SECURITY DESCRIPTION SYMBOL: ORCL\nORACLE CORP\n"
    "SPAIN TAX ³ $4,264.96\nTotal Cost $4,264.96\nDISTRIBUTION DETAILS:\n"
    "Date of Grant: AUG/03/2021 Date of Distribution: AUG/03/2024\n"
    "Grant ID: 2020IOLRS Grant Type: RSU Shares Netted at Fair Market Value\n"
    "Fair Market Value: $133.28000 for Tax Withholding 32\n"
    "Net Shares Deposited 43"
)

_ADQ_2020_DERIVADO = (
    "ORACLE CORPORATION TRANSACTION CONFIRMATION\nPARTICIPANT NO.\nI01182756\n11004868\n"
    "JORDI ELIES VIDAL\nMENDEZ NUNEZ 10\nBADALONA\n"
    "BARCELONA FIDELITY STOCK PLAN SERVICES, LLC\nSPAIN 08911 P.O. BOX 770001\n"
    "CINCINNATI, OH 45277-0003\nTELEPHONE NUMBER:(800) 544-0275\n"
    "REF # 20126-0BQDNF\n"
    "CUSTOMER NO. PARTICIPANT ID. TYPE REG.REP. TRADE DATE SETTLEMENT DATE TRANS NO. CUSIP NO. ORIG.\n"
    "I01182756 1 000 05-05-20 05-07-20 0BQDNF 68389X105\n"
    "100 SHARES WERE DISTRIBUTED TAX INFORMATION\n"
    "Market Value at Distribution¹ $5,175.00\nTaxable Income² $5,175.00\n"
    "42 SHARES WERE NETTED TO COVER YOUR TAX\nWITHHOLDING\n"
    "EXPLANATION OF PROCEEDS\nShares Distributed 100\n"
    "SECURITY DESCRIPTION SYMBOL: ORCL\nORACLE CORP COM\n"
    "SPAIN TAX ³ $2,173.50\nTotal Cost $2,173.50\nDISTRIBUTION DETAILS:\n"
    "Date of Grant: MAY/05/2019 Date of Distribution: MAY/05/2020\n"
    "Grant ID: 2000IOLRS Grant Type: RSU Shares Netted at Fair Market Value\n"
    "for Tax Withholding 42\nNet Shares Deposited 58"
)

_DESCONOCIDO = "SOME UNRELATED DOCUMENT WITHOUT SYMBOL OR KNOWN PATTERNS"


# ── _parse_us_date ─────────────────────────────────────────────────────────────

class TestParseUsDate:
    def test_fecha_valida(self):
        assert _parse_us_date("AUG/03/2024") == date(2024, 8, 3)

    def test_fecha_mayo(self):
        assert _parse_us_date("MAY/05/2020") == date(2020, 5, 5)

    def test_fecha_enero(self):
        assert _parse_us_date("JAN/01/2023") == date(2023, 1, 1)

    def test_mes_desconocido(self):
        with pytest.raises(ValueError):
            _parse_us_date("XYZ/01/2024")

    def test_formato_incorrecto(self):
        with pytest.raises(ValueError):
            _parse_us_date("08-03-2024")


# ── parse_confirmation_text ───────────────────────────────────────────────────

class TestParseConfirmationText:
    def test_venta_simple(self):
        row = parse_confirmation_text(_VENTA_SIMPLE, "venta.pdf")
        assert row is not None
        assert row.tipo == "venta"
        assert row.ticker == "ORCL"
        assert row.fecha == date(2024, 3, 12)
        assert row.cantidad == Decimal("58")
        assert row.precio_usd == Decimal("126.2500")
        assert row.fmv_derivado is False
        assert row.source == "venta.pdf"

    def test_venta_asteriscos_limpia_precio(self):
        row = parse_confirmation_text(_VENTA_ASTERISCOS, "asteriscos.pdf")
        assert row is not None
        assert row.tipo == "venta"
        assert row.fecha == date(2024, 9, 26)
        assert row.cantidad == Decimal("8")
        # El sufijo **** debe eliminarse; el precio resultante debe ser exacto.
        assert row.precio_usd == Decimal("167.5992")

    def test_adquisicion_shares_deposited(self):
        """Distribución con Shares Deposited == Shares Distributed (sin neteo)."""
        row = parse_confirmation_text(_ADQ_SHARES_DEP, "adq_sep17.pdf")
        assert row is not None
        assert row.tipo == "adquisicion"
        assert row.fecha == date(2024, 9, 15)
        assert row.cantidad == Decimal("9")
        assert row.precio_usd == Decimal("162.03000")
        assert row.fmv_derivado is False

    def test_adquisicion_net_shares_deposited_usa_neto(self):
        """Distribución con neteo: cantidad = Net Shares Deposited (43), no bruto (75)."""
        row = parse_confirmation_text(_ADQ_NET_SHARES, "adq_aug.pdf")
        assert row is not None
        assert row.tipo == "adquisicion"
        assert row.fecha == date(2024, 8, 3)
        assert row.cantidad == Decimal("43")         # neto, no 75
        assert row.precio_usd == Decimal("133.28000")
        assert row.fmv_derivado is False

    def test_adquisicion_2020_fmv_derivado(self):
        """PDF antiguo (2020) sin línea FMV: deriva FMV = Market Value / Shares Distributed."""
        row = parse_confirmation_text(_ADQ_2020_DERIVADO, "adq_2020.pdf")
        assert row is not None
        assert row.tipo == "adquisicion"
        assert row.fecha == date(2020, 5, 5)
        assert row.cantidad == Decimal("58")         # neto, no 100
        # 5175.00 / 100 = 51.75
        assert row.precio_usd == Decimal("51.75")
        assert row.fmv_derivado is True

    def test_documento_desconocido_devuelve_none(self):
        row = parse_confirmation_text(_DESCONOCIDO, "desconocido.pdf")
        assert row is None

    def test_ticker_normalizado_mayusculas(self):
        # El símbolo del PDF ya está en mayúsculas; verificamos que no se altera.
        row = parse_confirmation_text(_VENTA_SIMPLE, "x.pdf")
        assert row.ticker == "ORCL"


# ── build_rows ────────────────────────────────────────────────────────────────

class TestBuildRows:
    def test_lista_vacia(self, tmp_path):
        rows, warnings = build_rows([])
        assert rows == []
        assert warnings == []

    def test_pdf_no_existe_produce_aviso(self, tmp_path):
        fake = tmp_path / "inexistente.pdf"
        rows, warnings = build_rows([fake])
        assert rows == []
        assert len(warnings) == 1

    def test_pdf_real_produce_fila(self):
        import pathlib
        pdf = pathlib.Path(
            "input/fidelity_ledger/2024/Trade_Confirmation_(pdf)_Mar_12,_2024.pdf"
        )
        if not pdf.exists():
            pytest.skip("PDF real no disponible en CI")
        rows, warnings = build_rows([pdf])
        assert len(rows) == 1
        assert rows[0].tipo == "venta"
        assert warnings == []


# ── rows_to_csv ───────────────────────────────────────────────────────────────

def _make_row(fecha_iso, tipo, cantidad, precio, fmv_derivado=False):
    return LedgerRow(
        fecha=date.fromisoformat(fecha_iso),
        ticker="ORCL",
        tipo=tipo,
        cantidad=Decimal(cantidad),
        precio_usd=Decimal(precio),
        fmv_derivado=fmv_derivado,
        source="test.pdf",
    )


class TestRowsToCsv:
    def test_cabecera_correcta(self):
        csv_str = rows_to_csv([], generated_on="2024-01-01")
        assert "fecha,ticker,tipo,cantidad,precio_usd" in csv_str

    def test_orden_por_fecha(self):
        rows = [
            _make_row("2024-03-12", "venta", "10", "120"),
            _make_row("2020-05-05", "adquisicion", "58", "51.75"),
        ]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        lines = [l for l in csv_str.splitlines() if not l.startswith("#")]
        data_lines = [l for l in lines if l.strip()]
        # Cabecera + 2 datos
        assert data_lines[0].startswith("fecha")
        assert data_lines[1].startswith("2020")
        assert data_lines[2].startswith("2024")

    def test_adquisicion_antes_que_venta_mismo_dia(self):
        rows = [
            _make_row("2024-03-12", "venta", "10", "120"),
            _make_row("2024-03-12", "adquisicion", "5", "100"),
        ]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        data_lines = [l for l in csv_str.splitlines() if l.strip() and not l.startswith("#")]
        data_lines = data_lines[1:]  # sin cabecera
        assert "adquisicion" in data_lines[0]
        assert "venta" in data_lines[1]

    def test_nota_fmv_derivado_en_comentarios(self):
        rows = [_make_row("2020-05-05", "adquisicion", "58", "51.75", fmv_derivado=True)]
        csv_str = rows_to_csv(rows, generated_on="2020-01-01")
        assert "FMV derivado" in csv_str
        assert "test.pdf" in csv_str

    def test_sin_fmv_derivado_no_menciona_derivado(self):
        rows = [_make_row("2024-03-12", "venta", "10", "120")]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        assert "FMV derivado" not in csv_str

    def test_salida_aceptada_por_parse_ledger(self, tmp_path):
        """Integración: el CSV generado pasa parse_ledger sin errores."""
        rows = [
            _make_row("2020-05-05", "adquisicion", "58", "51.75", fmv_derivado=True),
            _make_row("2024-03-12", "venta", "10", "120"),
        ]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        p = tmp_path / "ledger.csv"
        p.write_text(csv_str, encoding="utf-8")
        entries = fidelity_fifo.parse_ledger(p)
        assert len(entries) == 2
        tipos = [e.tipo for e in entries]
        assert "adquisicion" in tipos
        assert "venta" in tipos

    def test_cantidad_como_entero(self):
        """La cantidad en el CSV no lleva decimales innecesarios."""
        rows = [_make_row("2024-03-12", "venta", "58", "126.2500")]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        assert "58," in csv_str
        assert "58.0" not in csv_str

    def test_recuento_operaciones_en_comentarios(self):
        """El bloque de cabecera incluye la línea con el total de operaciones."""
        rows = [
            _make_row("2020-05-05", "adquisicion", "58", "51.75"),
            _make_row("2024-03-12", "venta", "10", "120"),
        ]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        assert "# Operaciones: 2 (1 adquisiciones + 1 ventas)" in csv_str

    def test_recuento_solo_adquisiciones(self):
        rows = [_make_row("2020-05-05", "adquisicion", "58", "51.75")]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        assert "# Operaciones: 1 (1 adquisiciones + 0 ventas)" in csv_str

    def test_recuento_ledger_vacio(self):
        csv_str = rows_to_csv([], generated_on="2024-01-01")
        assert "# Operaciones: 0 (0 adquisiciones + 0 ventas)" in csv_str

    def test_salida_con_bom_aceptada_por_parse_ledger(self, tmp_path):
        """El CSV escrito con utf-8-sig (BOM) es leído correctamente por parse_ledger."""
        rows = [
            _make_row("2020-05-05", "adquisicion", "58", "51.75"),
            _make_row("2024-03-12", "venta", "10", "120"),
        ]
        csv_str = rows_to_csv(rows, generated_on="2024-01-01")
        p = tmp_path / "ledger_bom.csv"
        p.write_text(csv_str, encoding="utf-8-sig")  # como hace build_fidelity_ledger.py
        entries = fidelity_fifo.parse_ledger(p)
        assert len(entries) == 2
        tipos = [e.tipo for e in entries]
        assert "adquisicion" in tipos
        assert "venta" in tipos
