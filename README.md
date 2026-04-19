# renta

CLI para calcular las casillas de la declaración de la renta española (modelo 100) a partir de los informes de Fidelity NetBenefits y Koinly.

> **Aviso importante**: los resultados generados por este programa son una ayuda para el cálculo y **nunca deben presentarse directamente a Hacienda sin revisión previa**. Los valores deben ser verificados por el usuario y, si procede, por un asesor fiscal, antes de incluirlos en la declaración. El programa puede contener errores, los PDFs de entrada pueden variar entre años, y la normativa fiscal puede cambiar. El autor no se hace responsable de declaraciones incorrectas.

## Casillas calculadas

| Casilla | Concepto |
|---------|----------|
| 0029 | Dividendos — rendimientos del capital mobiliario |
| 0328–0337 | Ganancias/pérdidas patrimoniales — ventas de acciones (RSUs) |
| 0328–0337 | Ganancias/pérdidas patrimoniales — criptomonedas |
| 0588–0589 | Deducción por doble imposición internacional (retenciones EEUU) |
| Rend. cap. mob. | Rendimientos de staking/rewards de criptomonedas |

## Entradas soportadas

- **Fidelity NetBenefits** — "Custom transaction summary" (PDF descargado desde la web)
- **Koinly** — "Complete tax report" en español (PDF)

Los parsers están registrados en `src/renta/parsers/__init__.py`. Para añadir soporte para otro broker, consulta la sección "Cómo añadir un nuevo parser" en `SPEC.md`.

## Instalación

Requiere Python 3.11 o superior.

```bash
git clone <repo>
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

El repositorio incluye PDFs de ejemplo con datos ficticios en `samples/`:

```bash
renta calcular --input samples/
```

## Output

El programa genera un **HTML autocontenido** (sin dependencias externas) con:

- Resumen de casillas con importes en EUR
- Detalle de cada transacción con trazabilidad al PDF original (página y fila)
- Tipos de cambio BCE utilizados para cada conversión USD → EUR
- Notas y advertencias fiscales
- **Botones de acción** junto a los importes relevantes: copian el valor al portapapeles en formato ES (coma decimal, sin separador de miles). Dos tipos:
  - 📋 **Copiar**: valores a introducir directamente en el modelo 100 (valor transmisión € y valor adquisición € por operación).
  - 👁 **Verificar**: valores que la Renta calcula automáticamente (casillas 0336, 0337/0338, 0339, 0340, y totales por activo de 0328/0331) — para cuadrar contra el resultado una vez introducidos los datos.
  - **Shift+click** en cualquier botón restaura su estado original sin copiar nada.

## Tipos de cambio

Los tipos de cambio USD/EUR se obtienen automáticamente del **Banco Central Europeo**:

`https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A`

## Notas fiscales importantes

- **Cost basis de RSUs**: el valor de adquisición se convierte al tipo BCE de la **fecha de vesting** (date acquired); el valor de transmisión al tipo de la **fecha de venta**.
- **Doble imposición**: se calcula la retención neta en EEUU. Introduce ese importe en las casillas 0588–0589 de Renta Web: el propio programa de la AGEAT aplica automáticamente el límite legal (tipo medio efectivo español) y ajusta la deducción si corresponde.
- **Staking/rewards**: la calificación fiscal en España no es definitiva. Consulta con tu asesor fiscal.

> Este programa es una herramienta de ayuda. Verifica siempre los resultados antes de presentar la declaración.
