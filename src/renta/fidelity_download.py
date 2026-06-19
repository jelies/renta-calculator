"""
Descarga automatizada de Trade Confirmations de Fidelity NetBenefits.

Uso a través del comando integrado:
    renta-calculator download-trades --years 2024 2025

Flujo:
  1. Se abre Chromium con un perfil persistente (.fidelity_profile/).
  2. Tú haces login + 2FA a mano y pulsas Enter.
  3. El script navega a "Statements & records" → "Trade confirmations",
     selecciona el año, carga todos los resultados y descarga cada PDF.
  4. Al final genera el CSV ledger automáticamente.

Opciones:
  --years AÑO [AÑO ...]  Años a descargar (default: año actual)
  --out DIR              Carpeta base de destino (default: input/fidelity_ledger/)
  --delay SECS           Segundos de espera entre documentos (default: 2)
  --timeout SECS         Timeout por operación en segundos (default: 30)
  --profile DIR          Directorio del perfil de navegador (default: .fidelity_profile)
  --url URL              URL de inicio (default: https://nb.fidelity.com)
  --inspect              Abre Playwright Inspector para explorar selectores
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime
import re
import sys
from pathlib import Path


# ── Utilidades ────────────────────────────────────────────────────────────────

def sanitize_filename(text: str) -> str:
    """Convierte texto libre en nombre de fichero seguro."""
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:120] or "documento"


def unique_path(directory: Path, stem: str, suffix: str = ".pdf") -> Path:
    """Devuelve una ruta que no colisiona con ficheros existentes."""
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter:03d}{suffix}"
        counter += 1
    return candidate


def parse_confirmation_date(link_text: str) -> datetime.date | None:
    """Extrae la fecha de un texto de enlace de Trade Confirmation de Fidelity.

    El texto suele ser 'Trade Confirmation (pdf) May 5, 2022' o similar.
    Devuelve None si no se reconoce la fecha — nunca inventa un valor.
    """
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", link_text)
    if not match:
        return None
    month_str, day_str, year_str = match.groups()
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.datetime.strptime(
                f"{month_str} {day_str} {year_str}", fmt
            ).date()
        except ValueError:
            continue
    return None


def _require_playwright():
    """Importa playwright o lanza SystemExit con instrucciones claras."""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        print(
            "ERROR: playwright no está instalado.\n"
            "Para usar 'download-trades' instala el extra:\n"
            "  pip install 'renta-calculator[download]'\n"
            "  playwright install chromium\n"
            "\nO si usas uv:\n"
            "  uv sync --extra download\n"
            "  uv run playwright install chromium",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Navegación ────────────────────────────────────────────────────────────────

async def activate_trade_confirmations_tab(page, timeout_ms: int) -> None:
    """
    Activa la pestaña 'Trade confirmations' y verifica que quedó seleccionada.
    Lanza RuntimeError si no se puede confirmar tras reintentos — nunca falla
    en silencio (descargar de la sección equivocada sería peor que abortar).
    """
    tab = page.get_by_role("tab", name="Trade confirmations")
    await tab.wait_for(state="visible", timeout=timeout_ms)

    for attempt in range(3):
        if attempt == 0:
            await tab.click()
        else:
            # Reintento: foco + Enter por si el clic se pierde en el re-render de la SPA
            await tab.focus()
            await page.keyboard.press("Enter")

        await asyncio.sleep(1.5)

        selected = await tab.get_attribute("aria-selected")
        if selected == "true":
            print("  → Pestaña 'Trade confirmations' activada ✓")
            return

        print(f"  ⚠️  Pestaña no activa aún (intento {attempt + 1}/3, aria-selected={selected!r})")

    raise RuntimeError(
        "No se pudo activar la pestaña 'Trade confirmations' tras 3 intentos "
        "(sigue seleccionada otra sección). Abortado para no bajar PDFs incorrectos."
    )


async def navigate_to_trade_confirmations(page, timeout_ms: int) -> None:
    """Navega a la sección de Trade Confirmations (tolerante si ya está en la página)."""
    try:
        link = page.get_by_role("link", name="Statements & records")
        await link.wait_for(state="visible", timeout=timeout_ms)
        await link.click()
        print("  → Clic en 'Statements & records'")
        # Esperar a que la zona de pestañas cargue antes de intentar clicar
        await asyncio.sleep(2.0)
    except Exception:
        print("  ℹ️  'Statements & records' no encontrado (posiblemente ya estás ahí)")

    await activate_trade_confirmations_tab(page, timeout_ms)


async def select_year(page, year: int, timeout_ms: int) -> None:
    """Abre el combobox 'Time period' y selecciona el año indicado."""
    combobox = page.get_by_role("combobox", name=re.compile("Time period"))
    await combobox.wait_for(state="visible", timeout=timeout_ms)
    await combobox.click()
    print(f"  → Combobox 'Time period' abierto")

    option = page.get_by_role("option", name=str(year))
    await option.wait_for(state="visible", timeout=timeout_ms)
    await option.click()
    print(f"  → Año {year} seleccionado")

    await asyncio.sleep(2.0)


async def load_all_results(page, timeout_ms: int) -> None:
    """Clica 'Load N more result' repetidamente hasta que no haya más."""
    load_more_re = re.compile(r"Load \d+ more result")
    rounds = 0
    while True:
        try:
            btn = page.get_by_role("link", name=load_more_re)
            # Espera corta: si no aparece, no hay más resultados
            await btn.wait_for(state="visible", timeout=5_000)
            text = await btn.inner_text()
            await btn.click()
            print(f"  → Clic en '{text.strip()}' (ronda {rounds + 1})")
            await asyncio.sleep(2.0)
            rounds += 1
        except Exception:
            # No hay más botón de cargar
            break
    if rounds == 0:
        print("  → Sin 'Load more': todos los resultados ya visibles")
    else:
        print(f"  → Carga completada ({rounds} ronda(s))")


# ── Descarga ──────────────────────────────────────────────────────────────────

async def download_confirmation(
    page,
    idx: int,
    total: int,
    link_text: str,
    out_dir: Path,
    timeout_ms: int,
) -> Path:
    """
    Clica el link idx-ésimo 'Trade Confirmation (pdf)', espera el popup con la
    URL blob: y extrae el PDF directamente desde la memoria del navegador vía JS.
    Devuelve la ruta guardada. Lanza excepción si algo falla.
    """
    locator = page.get_by_role("link", name=re.compile(r"Trade Confirmation \(pdf\)"))

    async with page.expect_popup(timeout=timeout_ms) as popup_info:
        await locator.nth(idx).click()

    popup = await popup_info.value

    # Esperar a que el popup navegue a su URL final (blob: o https:)
    await popup.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

    # Pequeña pausa para que el blob esté completamente disponible en memoria
    await asyncio.sleep(1.0)

    blob_url = popup.url

    if blob_url.startswith("blob:"):
        # Leer el blob desde JS y devolver como base64
        pdf_b64: str = await popup.evaluate(
            """async (url) => {
                const resp = await fetch(url);
                const buf = await resp.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let bin = '';
                for (let i = 0; i < bytes.byteLength; i++) {
                    bin += String.fromCharCode(bytes[i]);
                }
                return btoa(bin);
            }""",
            blob_url,
        )
        pdf_bytes = base64.b64decode(pdf_b64)
    else:
        # URL normal: descargar vía la API de requests del contexto
        response = await popup.context.request.get(blob_url)
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} al descargar {blob_url}")
        pdf_bytes = await response.body()

    if not pdf_bytes or pdf_bytes[:4] != b"%PDF":
        raise RuntimeError(
            f"El contenido recibido no parece un PDF válido "
            f"(primeros bytes: {pdf_bytes[:8]!r})"
        )

    fecha = parse_confirmation_date(link_text)
    if fecha is not None:
        stem = f"trade-confirmation-{fecha:%Y.%m.%d}"
    else:
        # Fecha no reconocida: conservar el texto original saneado y avisar.
        stem = sanitize_filename(link_text)
        print(
            f"⚠️  fecha no reconocida en {link_text.strip()!r}, usando nombre original … ",
            end="",
            flush=True,
        )
    save_path = unique_path(out_dir, stem)
    save_path.write_bytes(pdf_bytes)
    await popup.close()

    return save_path


# ── Lógica principal ──────────────────────────────────────────────────────────

async def process_year(
    page,
    year: int,
    out_base: Path,
    delay: float,
    timeout_ms: int,
) -> tuple[list[tuple[str, Path]], list[tuple[int, str, str]]]:
    """Descarga todas las trade confirmations del año dado. Devuelve (ok, failed)."""
    out_dir = out_base / f"fidelity_trade_confirmations_{year}"
    out_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[tuple[str, Path]] = []
    failed: list[tuple[int, str, str]] = []

    print(f"\n{'─' * 60}")
    print(f"  AÑO {year}")
    print(f"{'─' * 60}")

    await select_year(page, year, timeout_ms)

    # Guard: verificar que seguimos en 'Trade confirmations' tras cambiar el año
    # (el cambio de año a veces resetea la selección de pestaña en la SPA)
    try:
        await activate_trade_confirmations_tab(page, timeout_ms)
    except RuntimeError as e:
        print(f"\n  ❌ {e}")
        failed.append((0, f"AÑO {year}", str(e)))
        return downloaded, failed

    await load_all_results(page, timeout_ms)

    # Contar documentos disponibles
    locator = page.get_by_role("link", name=re.compile(r"Trade Confirmation \(pdf\)"))
    count = await locator.count()
    print(f"\n  📄 {count} Trade Confirmation(s) encontrada(s) para {year}")

    # Diagnóstico: mostrar el texto del primer documento para confirmar sección
    if count > 0:
        first_text = await locator.first.inner_text()
        print(f"  🔍 Primer documento: {first_text.strip()!r}")
    print()

    if count == 0:
        print("  ⚠️  No se encontraron documentos para este año.")
        return downloaded, failed

    for i in range(count):
        try:
            link_text = await locator.nth(i).inner_text()
        except Exception:
            link_text = f"Trade_Confirmation_{year}_{i + 1:03d}"

        print(f"  [{i + 1}/{count}] {link_text.strip()!r} … ", end="", flush=True)

        try:
            path = await download_confirmation(
                page=page,
                idx=i,
                total=count,
                link_text=link_text.strip(),
                out_dir=out_dir,
                timeout_ms=timeout_ms,
            )
            print(f"✅ {path.name}")
            downloaded.append((link_text.strip(), path))
        except Exception as exc:
            reason = str(exc)[:120]
            print(f"❌ {reason}")
            failed.append((i + 1, link_text.strip()[:60], reason))

        if i < count - 1:
            await asyncio.sleep(delay)

    return downloaded, failed


async def _run_async(args: argparse.Namespace) -> int:
    # Import perezoso: solo falla aquí (al ejecutar), no al importar el módulo
    _require_playwright()
    from playwright.async_api import async_playwright

    out_base = Path(args.out)
    out_base.mkdir(parents=True, exist_ok=True)
    timeout_ms = int(args.timeout * 1000)

    all_downloaded: dict[int, list[tuple[str, Path]]] = {}
    all_failed: dict[int, list[tuple[int, str, str]]] = {}

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            headless=False,
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        print(f"\n→ Abriendo {args.url} …")
        await page.goto(args.url, wait_until="domcontentloaded")

        if args.inspect:
            print("\n🔍 Modo inspección: usa el Inspector para explorar el DOM.")
            print("   Cierra el Inspector o la ventana del navegador cuando termines.\n")
            await page.pause()
            await context.close()
            return 0

        # Pausa para login manual
        print(
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            "\n  Inicia sesión en Fidelity (usuario + contraseña + 2FA si aplica)."
            "\n  No hace falta que navegues a ningún sitio — el script lo hará."
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        input("  ▶ Pulsa Enter cuando hayas completado el login…\n")

        # Navegar a Trade Confirmations (una sola vez)
        await navigate_to_trade_confirmations(page, timeout_ms)

        # Procesar cada año
        for year in args.years:
            ok, failed = await process_year(
                page=page,
                year=year,
                out_base=out_base,
                delay=args.delay,
                timeout_ms=timeout_ms,
            )
            all_downloaded[year] = ok
            all_failed[year] = failed

        await context.close()

    # ── Informe final ─────────────────────────────────────────────────────────
    total_ok = sum(len(v) for v in all_downloaded.values())
    total_fail = sum(len(v) for v in all_failed.values())

    print(f"\n{'━' * 68}")
    print("  RESUMEN FINAL")
    print(f"{'━' * 68}")

    for year in args.years:
        ok = all_downloaded.get(year, [])
        fail = all_failed.get(year, [])
        print(f"\n  {year}: ✅ {len(ok)} descargado(s), ⚠️  {len(fail)} fallido(s)")
        for label, path in ok:
            print(f"     • {path.name}")
        for idx, label, reason in fail:
            print(f"     ✗ [{idx}] {label!r}")
            print(f"          Motivo: {reason}")

    print(f"\n  TOTAL: {total_ok} descargado(s), {total_fail} fallido(s)")
    print(f"  Carpeta base: {out_base.resolve()}")

    if total_fail:
        print(
            "\n  Consejo: para reintentar los fallidos, re-ejecuta el comando."
            "\n  Los ya descargados no se sobrescribirán (unique_path)."
        )
    else:
        print("\n  Sin fallos. 🎉")

    print(f"{'━' * 68}\n")
    return 1 if total_fail else 0


def run_download(args: argparse.Namespace) -> int:
    """Punto de entrada sincrónico para el subcomando download-trades."""
    return asyncio.run(_run_async(args))


def add_download_args(parser: argparse.ArgumentParser) -> None:
    """Registra los argumentos del subcomando download-trades en el parser dado."""
    current_year = datetime.date.today().year
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[current_year],
        metavar="AÑO",
        help=f"Años a descargar (default: {current_year})",
    )
    parser.add_argument(
        "--out",
        default="input/fidelity_ledger",
        help="Carpeta base de destino (default: input/fidelity_ledger/)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Segundos entre documentos (default: 2)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout por operación en segundos (default: 30)",
    )
    parser.add_argument(
        "--profile",
        default=".fidelity_profile",
        help="Directorio del perfil persistente",
    )
    parser.add_argument(
        "--url",
        default="https://nb.fidelity.com",
        help="URL de inicio",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Abre Playwright Inspector para explorar selectores",
    )
