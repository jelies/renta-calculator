"""
CLI principal del programa renta.

Uso:
    renta calcular --input carpeta/ --output resultado.html [--year 2024]
    python -m renta calcular --input carpeta/ --output resultado.html
"""

import argparse
import sys
from pathlib import Path

import pdfplumber

from renta import parsers
from renta.calculator import Calculator
from renta.exchange import ExchangeRateProvider
from renta.parsers import fidelity, koinly
from renta.report import generate


def _detect_pdf_type(pdf_path: Path) -> str | None:
    """
    Devuelve 'fidelity', 'koinly' o None según el contenido de la primera página.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return None
            text = (pdf.pages[0].extract_text() or "").lower()
            if "fidelity" in text:
                return "fidelity"
            if "koinly" in text:
                return "koinly"
    except Exception:
        pass
    return None


def _find_pdfs(input_path: Path) -> dict[str, Path]:
    """
    Busca PDFs en input_path (directorio o fichero único) y los clasifica.
    Devuelve {'fidelity': path, 'koinly': path}.
    """
    if input_path.is_file():
        candidates = [input_path]
    elif input_path.is_dir():
        candidates = list(input_path.glob("*.pdf")) + list(input_path.glob("*.PDF"))
    else:
        print(f"Error: {input_path} no existe.", file=sys.stderr)
        sys.exit(1)

    found: dict[str, Path] = {}
    for pdf_path in candidates:
        pdf_type = _detect_pdf_type(pdf_path)
        if pdf_type:
            if pdf_type in found:
                print(
                    f"Advertencia: se encontraron múltiples PDFs de tipo '{pdf_type}'. "
                    f"Se usará: {found[pdf_type].name}. Se ignora: {pdf_path.name}",
                    file=sys.stderr,
                )
            else:
                found[pdf_type] = pdf_path

    return found


def _detect_year(fidelity_data, koinly_data) -> int:
    """Intenta detectar el año fiscal de los datos."""
    if fidelity_data and fidelity_data.dividends:
        return fidelity_data.dividends[0].date.year
    if fidelity_data and fidelity_data.stock_sales:
        return fidelity_data.stock_sales[0].date_sold.year
    if koinly_data and koinly_data.capital_gains:
        return koinly_data.capital_gains[0].date_sold.year
    if koinly_data and koinly_data.rewards:
        return koinly_data.rewards[0].date.year
    return 2024


def cmd_calcular(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    print(f"Buscando PDFs en: {input_path}")
    pdfs = _find_pdfs(input_path)

    if not pdfs:
        print("Error: no se encontró ningún PDF de Fidelity o Koinly.", file=sys.stderr)
        print("Asegúrate de que los PDFs son el 'Custom transaction summary' de Fidelity "
              "o el 'Tax Report' de Koinly.", file=sys.stderr)
        sys.exit(1)

    fidelity_data = None
    koinly_data = None
    all_warnings: list[str] = []

    if "fidelity" in pdfs:
        print(f"  Procesando Fidelity: {pdfs['fidelity'].name}")
        fidelity_data = fidelity.parse(pdfs["fidelity"])
        warnings = fidelity.validate(fidelity_data)
        if warnings:
            for w in warnings:
                print(f"  ⚠ {w}", file=sys.stderr)
        all_warnings.extend(warnings)
        print(
            f"    → {len(fidelity_data.dividends)} dividendos, "
            f"{len(fidelity_data.stock_sales)} ventas, "
            f"{len(fidelity_data.withholdings)} retenciones"
        )
    else:
        print("  Aviso: no se encontró PDF de Fidelity.", file=sys.stderr)

    if "koinly" in pdfs:
        print(f"  Procesando Koinly: {pdfs['koinly'].name}")
        koinly_data = koinly.parse(pdfs["koinly"])
        warnings = koinly.validate(koinly_data)
        if warnings:
            for w in warnings:
                print(f"  ⚠ {w}", file=sys.stderr)
        all_warnings.extend(warnings)
        print(
            f"    → {len(koinly_data.capital_gains)} ganancias crypto, "
            f"{len(koinly_data.rewards)} rewards"
        )
    else:
        print("  Aviso: no se encontró PDF de Koinly.", file=sys.stderr)

    # Determinar año fiscal
    year = args.year
    if year is None:
        year = _detect_year(fidelity_data, koinly_data)
        print(f"  Año fiscal detectado: {year}")

    # Recopilar todas las fechas USD necesarias para la conversión
    all_dates: set = set()
    if fidelity_data:
        for d in fidelity_data.dividends:
            all_dates.add(d.date)
        for s in fidelity_data.stock_sales:
            all_dates.add(s.date_sold)
            all_dates.add(s.date_acquired)  # fecha de vesting (puede ser de años anteriores)
        for w in fidelity_data.withholdings:
            all_dates.add(w.date)

    # Obtener tipos de cambio del BCE para todas las fechas necesarias
    if all_dates:
        min_year = min(d.year for d in all_dates)
        max_year = max(d.year for d in all_dates)
        rango_str = f"{min_year}" if min_year == max_year else f"{min_year}–{max_year}"
        print(f"Descargando tipos de cambio del BCE ({rango_str})...")
    else:
        print(f"Descargando tipos de cambio del BCE para {year}...")
    try:
        if all_dates:
            rates = ExchangeRateProvider.for_dates(all_dates)
        else:
            rates = ExchangeRateProvider.for_year(year)
        print("  ✓ Tipos de cambio obtenidos correctamente")
    except Exception as e:
        print(f"Error al obtener tipos de cambio: {e}", file=sys.stderr)
        sys.exit(1)

    # Calcular
    print("Calculando casillas del modelo 100...")
    from renta.models import FidelityData, KoinlyData
    calculator = Calculator(rates)
    result = calculator.calculate(
        fidelity=fidelity_data or FidelityData(),
        koinly=koinly_data or KoinlyData(),
        year=year,
    )
    result.warnings = all_warnings + result.warnings

    # Generar HTML
    html = generate(result, koinly=koinly_data)

    # Guardar
    if output_path is None:
        output_path = Path(f"resultado_{year}.html")
    output_path.write_text(html, encoding="utf-8")

    print(f"\n✓ Informe generado: {output_path.resolve()}")
    print("\nResumen:")
    def _fmt_valor(v):
        return "NO CALCULABLE" if v is None else f"€{v:,.2f}"

    if result.dividendos:
        print(f"  Casilla {result.dividendos.numero} (Dividendos): {_fmt_valor(result.dividendos.valor)}")
    if result.ganancias_acciones:
        print(f"  Casillas {result.ganancias_acciones.numero} (Acciones RSU): {_fmt_valor(result.ganancias_acciones.valor)}")
    if result.ganancias_crypto:
        print(f"  Casillas {result.ganancias_crypto.numero} (Crypto): {_fmt_valor(result.ganancias_crypto.valor)}")
    if result.doble_imposicion:
        print(f"  Casillas {result.doble_imposicion.numero} (Doble imposición): {_fmt_valor(result.doble_imposicion.valor)}")
    if result.rendimientos_crypto:
        print(f"  {result.rendimientos_crypto.numero} (Staking rewards): {_fmt_valor(result.rendimientos_crypto.valor)}")
    if result.warnings:
        print(f"\n  ⚠ {len(result.warnings)} advertencia(s). Consulta el informe HTML.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="renta",
        description="Calcula casillas del modelo 100 a partir de PDFs de Fidelity y Koinly",
    )
    subparsers = parser.add_subparsers(dest="command")

    calc = subparsers.add_parser("calcular", help="Procesar PDFs y generar informe")
    calc.add_argument(
        "--input", "-i", required=True,
        help="Directorio con los PDFs o ruta a un PDF específico",
    )
    calc.add_argument(
        "--output", "-o", default=None,
        help="Ruta del fichero HTML de salida (default: resultado_YYYY.html)",
    )
    calc.add_argument(
        "--year", "-y", type=int, default=None,
        help="Año fiscal (default: autodetectado del PDF)",
    )

    args = parser.parse_args()

    if args.command == "calcular":
        cmd_calcular(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
