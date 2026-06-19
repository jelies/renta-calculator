"""
Genera el CSV ledger de operaciones de Fidelity parseando las Trade Confirmations (PDFs).

El CSV resultante es la entrada para el modo --fidelity-fifo de renta-calculator.

Uso:
    uv run python scripts/build_fidelity_ledger.py
    uv run python scripts/build_fidelity_ledger.py --input input/fidelity_ledger --out mi_ledger.csv
    uv run python scripts/build_fidelity_ledger.py --stdout

Opciones:
  --input DIR   Carpeta base con los PDFs (busca recursivamente *.pdf). [input/fidelity_ledger]
  --out FILE    Ruta de salida del CSV. [<input>/fidelity_ledger.csv]
  --stdout      Imprime el CSV por stdout en lugar de escribir a disco.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_pdfs(base: Path) -> list[Path]:
    """Devuelve todos los *.pdf dentro de base, ordenados por ruta (año y nombre)."""
    return sorted(base.rglob("*.pdf"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera el CSV ledger FIFO de Fidelity a partir de los PDFs de Trade Confirmation."
    )
    parser.add_argument(
        "--input",
        default="input/fidelity_ledger",
        metavar="DIR",
        help="Carpeta base con las Trade Confirmations (busca *.pdf recursivamente). "
             "[input/fidelity_ledger]",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="Ruta de salida del CSV. Por defecto: <input>/fidelity_ledger.csv",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Imprime el CSV por stdout en lugar de escribir un fichero.",
    )
    args = parser.parse_args()

    base = Path(args.input)
    if not base.is_dir():
        print(f"ERROR: la carpeta de entrada no existe: {base}", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else base / "fidelity_ledger.csv"

    # Importaciones aquí para que los mensajes de error del CLI sean claros.
    from renta.parsers.fidelity_confirmations import build_rows, rows_to_csv
    from renta.parsers.fidelity_fifo import parse_ledger, compute_fifo

    # ── 1. Leer PDFs ──────────────────────────────────────────────────────────
    pdf_paths = _find_pdfs(base)
    if not pdf_paths:
        print(f"ERROR: no se encontraron PDFs en {base}", file=sys.stderr)
        return 1

    print(f"📂  {len(pdf_paths)} PDFs encontrados en {base}")

    rows, warnings = build_rows(pdf_paths)

    if warnings:
        print()
        for w in warnings:
            print(w, file=sys.stderr)

    if not rows:
        print("ERROR: no se pudo extraer ninguna operación de los PDFs.", file=sys.stderr)
        return 1

    n_adq = sum(1 for r in rows if r.tipo == "adquisicion")
    n_ven = sum(1 for r in rows if r.tipo == "venta")
    n_der = sum(1 for r in rows if r.fmv_derivado)
    print(
        f"✅  Extraídas {len(rows)} filas: "
        f"{n_adq} adquisiciones + {n_ven} ventas"
        + (f" ({n_der} FMV derivados)" if n_der else "")
    )

    # ── 2. Generar CSV ────────────────────────────────────────────────────────
    csv_content = rows_to_csv(rows)

    if args.stdout:
        print()
        print(csv_content, end="")
        return 0

    out_path.write_text(csv_content, encoding="utf-8-sig")
    print(f"📄  CSV escrito en: {out_path}")

    # ── 3. Auto-verificación: parse_ledger ────────────────────────────────────
    print()
    print("🔍  Verificando formato del CSV con parse_ledger…")
    try:
        entries = parse_ledger(out_path)
    except ValueError as exc:
        print(f"❌  parse_ledger falló: {exc}", file=sys.stderr)
        return 1

    n_e_adq = sum(1 for e in entries if e.tipo == "adquisicion")
    n_e_ven = sum(1 for e in entries if e.tipo == "venta")
    print(f"    OK — {len(entries)} entradas: {n_e_adq} adquisiciones + {n_e_ven} ventas")

    # ── 4. Chequeo FIFO por año ───────────────────────────────────────────────
    anios_venta = sorted({e.fecha.year for e in entries if e.tipo == "venta"})
    if anios_venta:
        print()
        print("📊  Chequeo FIFO por año fiscal:")
        hay_errores = False
        for yr in anios_venta:
            frags, errores = compute_fifo(entries, yr)
            if errores:
                hay_errores = True
                print(f"    ⚠️  {yr}: {len(frags)} fragmentos — {len(errores)} error(es):")
                for e in errores:
                    print(f"       - {e}", file=sys.stderr)
            else:
                print(f"    ✅  {yr}: {len(frags)} fragmentos — inventario OK")
        if hay_errores:
            print()
            print(
                "⚠️  Hay ventas sin inventario FIFO suficiente. Revisa que todos los PDFs",
                file=sys.stderr,
            )
            print(
                "   de adquisición estén presentes en la carpeta de entrada.",
                file=sys.stderr,
            )

    # ── 5. Resumen final ──────────────────────────────────────────────────────
    print()
    print("─" * 60)
    print(f"  PDFs procesados:     {len(pdf_paths)}")
    if warnings:
        print(f"  No reconocidos:      {len(warnings)}")
    print(f"  Filas en el CSV:     {len(rows)} ({n_adq} adq. + {n_ven} ven.)")
    if n_der:
        print(f"  FMV derivados:       {n_der} (de Market Value / Shares Distributed)")
    print(f"  Salida:              {out_path}")
    print("─" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
