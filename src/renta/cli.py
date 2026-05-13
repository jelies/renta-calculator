"""
CLI principal del programa renta.

Uso:
    renta-calculator --input carpeta/ --output resultado.html [--year 2024]
    python -m renta --input carpeta/ --output resultado.html
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

from renta.calculator import Calculator
from renta.exchange import ExchangeRateProvider
from renta.formatting import bold, cyan, dim, format_eur, green, primary, red, yellow
from renta.parsers import REGISTRY
from renta.report import generate


def _detect_pdf_type(pdf_path: Path) -> str | None:
    """
    Devuelve el nombre del parser que reconoce este PDF, o None.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text() or ""
            for name, module, _optional in REGISTRY:
                if module.detect(text):
                    return name
    except Exception:
        pass
    return None


def _find_pdfs(input_path: Path) -> dict[str, Path]:
    """
    Busca PDFs en input_path (directorio o fichero único) y los clasifica.
    Devuelve {'fidelity': path, 'koinly': path, ...}.
    """
    if input_path.is_file():
        candidates = [input_path]
    elif input_path.is_dir():
        candidates = list(input_path.glob("*.pdf")) + list(input_path.glob("*.PDF"))
    else:
        print(red(bold(f"Error: {input_path} no existe.", sys.stderr), sys.stderr), file=sys.stderr)
        sys.exit(1)

    found: dict[str, Path] = {}
    for pdf_path in candidates:
        pdf_type = _detect_pdf_type(pdf_path)
        if pdf_type:
            if pdf_type in found:
                print(
                    yellow(
                        f"Advertencia: se encontraron múltiples PDFs de tipo '{pdf_type}'. "
                        f"Se usará: {found[pdf_type].name}. Se ignora: {pdf_path.name}",
                        sys.stderr,
                    ),
                    file=sys.stderr,
                )
            else:
                found[pdf_type] = pdf_path

    return found


def _detect_year(parsed_data: dict[str, Any]) -> int | None:
    """Devuelve el año fiscal detectado de los datos, o None si no hay hint disponible."""
    for name, module, _optional in REGISTRY:
        if name in parsed_data:
            hint = module.year_hint(parsed_data[name])
            if hint is not None:
                return hint
    return None


def cmd_calcular(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    print(cyan(bold(f"Buscando PDFs en: {input_path}")))
    pdfs = _find_pdfs(input_path)

    if not pdfs:
        known = " o ".join(name for name, _, optional in REGISTRY if not optional)
        print(red(bold(f"Error: no se encontró ningún PDF reconocido ({known}).", sys.stderr), sys.stderr), file=sys.stderr)
        sys.exit(1)

    parsed_data: dict[str, Any] = {}
    all_warnings: list[str] = []

    for name, module, optional in REGISTRY:
        if name in pdfs:
            print(f"  Procesando {name}: {pdfs[name].name}")
            data = module.parse(pdfs[name])
            warnings = module.validate(data)
            if warnings:
                for w in warnings:
                    print(yellow(f"  ⚠ {w}", sys.stderr), file=sys.stderr)
            all_warnings.extend(warnings)
            print(dim(f"    → {module.stats_summary(data)}"))
            parsed_data[name] = data
        elif not optional:
            print(yellow(f"  Aviso: no se encontró PDF de {name}.", sys.stderr), file=sys.stderr)

    # Determinar año fiscal
    year = args.year
    if year is None:
        year = _detect_year(parsed_data)
        if year is None:
            print(
                red(bold("Error: no se pudo autodetectar el año fiscal. Usa --year para especificarlo.", sys.stderr), sys.stderr),
                file=sys.stderr,
            )
            sys.exit(1)
        print(dim(f"  Año fiscal detectado: {year}"))

    # Recopilar todas las fechas USD necesarias para la conversión
    all_dates: set = set()
    for name, module, _optional in REGISTRY:
        if name in parsed_data:
            all_dates |= module.usd_dates(parsed_data[name])

    # Obtener tipos de cambio del BCE para todas las fechas necesarias
    if all_dates:
        min_year = min(d.year for d in all_dates)
        max_year = max(d.year for d in all_dates)
        rango_str = f"{min_year}" if min_year == max_year else f"{min_year}–{max_year}"
        print(cyan(bold(f"Descargando tipos de cambio del BCE ({rango_str})...")))
    else:
        print(cyan(bold(f"Descargando tipos de cambio del BCE para {year}...")))
    try:
        if all_dates:
            rates = ExchangeRateProvider.for_dates(all_dates)
        else:
            rates = ExchangeRateProvider.for_year(year)
        print(green("  ✓ Tipos de cambio obtenidos correctamente"))
    except Exception as e:
        print(red(bold(f"Error al obtener tipos de cambio: {e}", sys.stderr), sys.stderr), file=sys.stderr)
        sys.exit(1)

    # Calcular
    print(cyan(bold("Calculando casillas del modelo 100...")))
    calculator = Calculator(rates)
    result = calculator.calculate(parsed_data, year=year)
    result.warnings = all_warnings + result.warnings

    # Generar HTML
    html = generate(result)

    # Guardar
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = Path("output") / f"renta_{year}_{timestamp}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    print(green(bold(f"\n✓ Informe generado: {output_path.resolve()}")))
    print(bold("\nResumen:"))

    def _fmt_valor(v):
        if v is None:
            return red("NO CALCULABLE")
        return bold(format_eur(v))

    def _linea(label: str, casillas: str, valor) -> None:
        badge = primary(f"[{casillas}]")
        print(f"  {label} {badge}: {_fmt_valor(valor)}")

    if result.dividendos:
        _linea("Dividendos", result.dividendos.numero, result.dividendos.valor)
    if result.ganancias_acciones:
        _linea("Venta acciones", result.ganancias_acciones.numero, result.ganancias_acciones.valor)
    if result.doble_imposicion:
        _linea("Impuestos extranjero", result.doble_imposicion.numero, result.doble_imposicion.valor)
    if result.ganancias_crypto:
        _linea("Venta cryptos", result.ganancias_crypto.numero, result.ganancias_crypto.valor)
    if result.rendimientos_crypto:
        _linea("Staking/rewards crypto", result.rendimientos_crypto.numero, result.rendimientos_crypto.valor)
    if result.airdrops_crypto:
        _linea("Airdrops crypto", result.airdrops_crypto.numero, result.airdrops_crypto.valor)
    if result.warnings:
        print(yellow(f"\n  ⚠ {len(result.warnings)} advertencia(s). Consulta el informe HTML."))

    print(
        yellow(
            "\n⚠ Aviso importante: los resultados son una ayuda para el cálculo y nunca deben "
            "presentarse directamente a Hacienda sin revisión previa. Verifica los valores y, "
            "si procede, consulta con un asesor fiscal antes de incluirlos en la declaración."
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="renta-calculator",
        description="Calcula casillas del modelo 100 a partir de PDFs de Fidelity, Koinly y DEGIRO",
        add_help=False,
    )
    parser.add_argument(
        "-h", "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Muestra este mensaje de ayuda y sale",
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Directorio con los PDFs o ruta a un PDF específico",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Ruta del fichero HTML de salida (default: output/renta_{año}_{YYYYmmdd_HHMM}.html)",
    )
    parser.add_argument(
        "--year", "-y", type=int, default=None,
        help="Año fiscal (default: autodetectado del PDF)",
    )

    args = parser.parse_args()
    cmd_calcular(args)


if __name__ == "__main__":
    main()
