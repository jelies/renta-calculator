# renta-calculator

[![tests](https://github.com/jelies/renta-calculator/actions/workflows/test.yml/badge.svg)](https://github.com/jelies/renta-calculator/actions/workflows/test.yml)

CLI para calcular las casillas de la declaración de la renta española (modelo 100) a partir de los informes de Fidelity NetBenefits y Koinly.

> **Aviso importante**: los resultados generados por este programa son una ayuda para el cálculo y **nunca deben presentarse directamente a Hacienda sin revisión previa**. Los valores deben ser verificados por el usuario y, si procede, por un asesor fiscal, antes de incluirlos en la declaración. El programa puede contener errores, los PDFs de entrada pueden variar entre años, y la normativa fiscal puede cambiar. El autor no se hace responsable de declaraciones incorrectas.

## Casillas calculadas

| Casilla | Concepto |
|---------|----------|
| 0029 | Dividendos — rendimientos del capital mobiliario |
| 0326–0340 | Ganancias/pérdidas patrimoniales — ventas de acciones (RSUs) |
| 1800–1814 | Ganancias/pérdidas patrimoniales — venta de criptomonedas |
| 0588 | Deducción por doble imposición internacional — "Impuesto satisfecho en el extranjero" (retenciones EEUU) |
| 0033 | Rendimientos de staking/rewards de criptomonedas |
| 0034 | Rendimientos de airdrops de criptomonedas |

## Entradas soportadas

- **Fidelity NetBenefits** — "Custom transaction summary" (PDF descargado desde la web)
- **Koinly** — "Complete tax report" en español (PDF)
- **Koinly** — "Informe de plusvalías para España" (PDF, opcional) — cuando está presente, sustituye los totales de adquisición/transmisión por activo por los valores oficiales del informe, evitando errores de redondeo acumulado
- **DEGIRO** — "Informe Fiscal Anual" de flatexDEGIRO Bank AG (PDF)

Los parsers están registrados en `src/renta/parsers/__init__.py`. Para añadir soporte para otro broker, consulta la sección "Cómo añadir un nuevo parser" en `SPEC.md`.

## Instalación

Requiere Python 3.11 o superior.

```bash
git clone https://github.com/jelies/renta-calculator.git
cd renta
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Uso

```bash
renta calcular --input carpeta/ [--output fichero.html] [--year 2024]
```

Donde `carpeta/` contiene los PDFs de Fidelity y Koinly. El programa los detecta automáticamente.

### Opciones

| Opción | Descripción | Default |
|--------|-------------|---------|
| `--input` / `-i` | Directorio con los PDFs (o ruta a un PDF) | requerido |
| `--output` / `-o` | Fichero HTML de salida | `output/renta_YYYY_ddMMYYYY_HHmm.html` |
| `--year` / `-y` | Año fiscal | autodetectado del PDF |

### Ejemplo

```bash
renta calcular --input /ruta/a/mis/pdfs/
renta calcular --input /ruta/a/mis/pdfs/ --output renta_2024.html --year 2024
```

### Prueba rápida con datos de ejemplo

El repositorio incluye tres datasets de PDFs ficticios en `samples/`:

```bash
renta calcular --input samples/1-samples/  # datos pequeños (original)
renta calcular --input samples/2-big/      # ~100 operaciones por sección
renta calcular --input samples/3-empty/    # sin operaciones (estados vacíos)
```

Los PDFs se regeneran con `python scripts/generate_sample_pdfs.py`.

## Output

El programa genera un **HTML autocontenido** (sin dependencias externas) con:

- Resumen de casillas con importes en EUR (cada concepto es un enlace que salta a su sección de detalle)
- Detalle de cada transacción con trazabilidad al PDF original (página y fila)
- Tipos de cambio BCE utilizados para cada conversión USD → EUR
- Notas y advertencias fiscales
- **Operaciones fuera del año fiscal** marcadas en amarillo/naranja como aviso y excluidas del total (p.ej. retenciones de 2024 que aparecen en el PDF de 2025); el total del activo sigue siendo visible con las operaciones válidas
- **Botones de acción** junto a los importes relevantes: copian el valor al portapapeles en formato ES (punto separador de miles, coma decimal; ej. `6.523,22`). Dos tipos:
  - 📋 **Copiar**: valores a introducir directamente en el modelo 100 (valor transmisión € y valor adquisición € por operación en ventas; total por activo en dividendos).
  - 👁 **Verificar**: valores que la Renta calcula automáticamente — para cuadrar contra el resultado una vez introducidos los datos (casillas 0336, 0337/0338, 0339, 0340 en ventas; total global de dividendos).
  - **Shift+click** en cualquier botón restaura su estado original sin copiar nada.

## Tipos de cambio

Los tipos de cambio USD/EUR se obtienen automáticamente del **Banco Central Europeo**:

`https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A`

## Notas fiscales importantes

- **Cost basis de RSUs**: el valor de adquisición se convierte al tipo BCE de la **fecha de vesting** (date acquired); el valor de transmisión al tipo de la **fecha de venta**.
- **Doble imposición**: el informe muestra, por activo, los dos valores que pide Renta Web al introducir retenciones en el extranjero: "Rentas incluidas en la base del ahorro" (= total dividendos del activo, casilla 0029) e "Impuesto satisfecho en el extranjero" (= retención neta, casilla 0588). El propio programa de la AEAT aplica automáticamente el límite legal (tipo medio efectivo español) y ajusta la deducción si corresponde.
- **Staking/rewards**: la calificación fiscal en España no es definitiva. Consulta con tu asesor fiscal.

> Este programa es una herramienta de ayuda. Verifica siempre los resultados antes de presentar la declaración.

## Limitaciones

- Los parsers están ajustados a formatos concretos de PDF de cada broker. Pueden romperse si el broker cambia el formato en un año futuro.
- Solo cubre las fuentes documentadas en "Entradas soportadas". Otros brokers o exchanges requieren añadir un parser nuevo (ver `SPEC.md`).
- Los tipos de cambio se obtienen del BCE en tiempo real; si la API no está disponible, los cálculos en USD quedan sin convertir y se marcan como no calculados.

## Contribuir

Las contribuciones son bienvenidas. Abre un issue para reportar un bug o proponer una mejora, o un PR si ya tienes un fix. Para añadir soporte para un nuevo broker, consulta la sección "Cómo añadir un nuevo parser" en [`SPEC.md`](SPEC.md).

## Licencia

[MIT](LICENSE)
