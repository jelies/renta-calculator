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
renta calcular --input samples/
renta calcular --input samples/ --output renta_2024.html --year 2024
```

## Output

El programa genera un **HTML autocontenido** (sin dependencias externas) con:

- Resumen de casillas con importes en EUR
- Detalle de cada transacción con trazabilidad al PDF original (página y fila)
- Tipos de cambio BCE utilizados para cada conversión USD → EUR
- Notas y advertencias fiscales

## Tipos de cambio

Los tipos de cambio se obtienen automáticamente de la API del **Banco Central Europeo** para la fecha exacta de cada transacción. Para días no hábiles (fines de semana, festivos), se usa el tipo del último día hábil anterior.

El programa descarga automáticamente los tipos de **todos los años necesarios**: si hay acciones con fecha de vesting en años anteriores al ejercicio fiscal (habitual en RSUs), se obtienen también los tipos de esos años en una sola petición.

Si no se puede obtener el tipo de cambio para una fecha (sin conexión, fecha fuera de rango, etc.), la fila se marca en rojo en el informe como **NO CALCULABLE** y se excluye del total de la casilla. **Nunca se usa un tipo ficticio** (como 1 USD = 1 EUR) que produciría valores incorrectos silenciosamente.

Endpoint: `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A`

## Notas fiscales importantes

- **Cost basis de RSUs**: el valor de adquisición se convierte al tipo BCE de la **fecha de vesting** (date acquired); los ingresos al tipo de la **fecha de venta**.
- **Doble imposición**: se calcula la retención neta en EEUU. La deducción está limitada al tipo medio efectivo español — consulta con tu asesor fiscal.
- **Staking/rewards**: la calificación fiscal en España no es definitiva. Consulta con tu asesor fiscal.

> Este programa es una herramienta de ayuda. Verifica siempre los resultados antes de presentar la declaración.
