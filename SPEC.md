# Especificación funcional — renta

Documento de referencia con los requisitos y decisiones funcionales tomadas durante el diseño del programa.

---

## Objetivo

Calcular automáticamente las casillas de la declaración de la renta española (modelo 100) relacionadas con inversiones en bolsa y criptomonedas, a partir de los informes que generan los brokers, y producir un informe con trazabilidad completa que permita verificar cada cifra.

---

## Entradas

### Fuentes soportadas

| Broker/Plataforma | Tipo de informe |
|-------------------|-----------------|
| **Fidelity NetBenefits** | "Custom transaction summary" descargado como PDF desde la web |
| **Koinly** | "Complete tax report" en español (PDF) |
| **DEGIRO** | "Informe Fiscal Anual" (PDF) — flatexDEGIRO Bank AG |

Los PDFs se detectan automáticamente por contenido: cada parser registrado expone una función `detect()` que examina el texto de la primera página. No es necesario nombrar los ficheros de ninguna forma concreta.

### Formato de entrada

- Solo PDFs. No se soportan CSVs ni otros formatos.
- Los ficheros se pasan indicando un directorio; el programa detecta cuál es de cada fuente.

---

## Salida

- Un único fichero **HTML autocontenido**: sin dependencias externas, sin imágenes externas. Se puede abrir en cualquier navegador y guardar/imprimir sin conexión.
- El HTML incluye:
  - Resumen de casillas con el importe final en EUR
  - Tablas de detalle por sección (dividendos, ventas de acciones, retenciones, ganancias crypto, rewards)
  - Columna de **trazabilidad** en cada fila: nombre del PDF, número de página y fila de origen
  - Tabla de tipos de cambio BCE utilizados
  - Notas y advertencias fiscales
  - **Botones de acción** junto a los importes en EUR: copian el valor al portapapeles en formato ES (coma decimal, sin separador de miles, sin símbolo de moneda ni signo). Hay dos tipos distintos, identificados visualmente por su icono SVG:
    - 📋 **Copiar** (`copy-btn`): valores que el usuario debe introducir manualmente en el modelo 100. En ventas de acciones: columnas "Valor transmisión €" y "Valor adquisición €" de cada operación (casillas 0328 y 0331). En dividendos: total por activo de la tabla resumen (casilla 0029 por activo).
    - 👁 **Verificar** (`copy-btn verify-btn`): valores que la Renta calcula automáticamente a partir de los datos introducidos, y que se muestran para que el usuario pueda cuadrarlos. En ventas: casillas 0336, 0337/0338, 0339, 0340 (tabla resumen), y totales por activo de 0328/0331 (cabecera de cada grupo colapsable). En dividendos: total global de la fila "Total" de la tabla resumen.
    - La columna "Ganancia €" no lleva botón: es un cálculo interno del programa, no un valor a trasladar directamente.
    - **Shift+click** sobre cualquier botón restaura su estado original (icono SVG, sin marca de copiado) sin copiar nada.
  - Se ocultan al imprimir.

---

## Interfaz

CLI (línea de comandos):

```bash
renta calcular --input carpeta/ [--output fichero.html] [--year 2024]
```

- `--year` es opcional; si no se especifica, se autodetecta del contenido de los PDFs.
- El año autodetectado es el año de la primera transacción encontrada.

---

## Casillas del modelo 100 calculadas

| Casilla | Concepto | Fuente |
|---------|----------|--------|
| **0029** | Dividendos (rendimientos del capital mobiliario) | Fidelity — "Dividend income" + DEGIRO — "Dividendos recibidos" |
| **0328–0337** | Ganancias/pérdidas patrimoniales — acciones | Fidelity — "Stock sales" + DEGIRO — ventas detalladas |
| **0328–0337** | Ganancias/pérdidas patrimoniales — criptomonedas | Koinly — "Operaciones de Ganancias Patrimoniales" |
| **0588–0589** | Deducción por doble imposición internacional | Fidelity — "Nonresident alien withholding" + DEGIRO — retenciones en origen |
| Rend. cap. mob. | Rendimientos de staking/rewards crypto | Koinly — "Operaciones de rendimientos" |

---

## Tipos de cambio (USD → EUR)

- Se obtienen automáticamente de la **API del Banco Central Europeo**.
- Endpoint: `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A`
- El tipo obtenido es el **tipo de referencia oficial diario del BCE**, publicado una vez al día alrededor de las **16:00 CET**. No es un precio de cierre de mercado, sino un valor único de referencia calculado por el BCE a partir de un procedimiento concertado entre bancos centrales. Es el tipo aceptado por la AEAT para valorar operaciones en divisas.
- El tipo BCE es "USD por 1 EUR" (ej: 1.085 = 1 EUR vale 1.085 USD). Conversión: `EUR = USD / tipo`.
- El rango descargado cubre **todas las fechas necesarias**: si hay vesting dates de años anteriores al ejercicio fiscal, se descarga el rango desde el año más antiguo hasta el más reciente, en una sola petición.
- Para días no hábiles (fines de semana, festivos), se usa el tipo del **último día hábil anterior** (retrocede hasta 14 días).
- Los tipos de cambio se cachean en memoria durante la sesión para evitar peticiones repetidas.
- **Si no se puede obtener el tipo de cambio** para una fecha (sin conexión, fecha fuera de rango, etc.): la fila se marca con error y se excluye del total. La casilla muestra "NO CALCULABLE" si alguna fila falla. **Nunca se usa un tipo ficticio** (ej. 1:1) que produciría valores incorrectos sin avisar.

---

## Reglas de cálculo

### Dividendos (casilla 0029)
- Cada dividendo en USD se convierte a EUR usando el tipo BCE de la **fecha del dividendo**.
- Se agrupan por activo y se suma el total por activo.
- La casilla 0029 se introduce **una vez por activo** con su total (no el global).

En el informe HTML:

- **Tabla resumen** (siempre visible): una fila por activo con su total EUR y botón 📋 copiar. Fila de totales con el global y botón 👁 verificar.
- **Secciones colapsables por activo**: detalle de cada dividendo con fecha, importe $, tipo de cambio e importe €.

### Ventas de acciones RSU (casillas 0328–0337)

**Decisión clave**: se usan **dos tipos de cambio distintos** por operación:
- El **valor de adquisición** (cost basis) se convierte al tipo BCE de la **fecha de vesting** (columna "Date acquired" en Fidelity). Razón: el coste real en EUR se produce en el momento en que las acciones se adquieren/liberan.
- El **valor de transmisión** (proceeds) se convierte al tipo BCE de la **fecha de venta** (columna "Date sold or transferred").
- La ganancia/pérdida en EUR = valor transmisión EUR − valor adquisición EUR.

> **Nota fiscal incluida en el informe**: el cost basis de Fidelity es el FMV (Fair Market Value) al vesting en USD. Fiscalmente, el valor de adquisición correcto para RSUs es el FMV en EUR a fecha de vesting (momento en que tributaron como rendimiento del trabajo). La conversión al tipo BCE de esa fecha es la aproximación más correcta disponible con los datos del PDF.

En el informe HTML:

- **Casillas a rellenar manualmente**: **0328** (valor de transmisión) y **0331** (valor de adquisición), una entrada por cada operación de cada activo. Las columnas "Valor transmisión €" y "Valor adquisición €" llevan botón 📋 copiar.
- **Tabla resumen** (siempre visible): muestra un desglose por activo con las casillas de verificación, todas con botón 👁 verificar:
  - Fila por activo: **0336** (ganancias del activo = suma de operaciones con ganancia > 0) y **0337/0338** (pérdidas del activo = suma de operaciones con pérdida < 0).
  - Fila de totales: **0339** (suma de todas las ganancias) y **0340** (suma de todas las pérdidas). Estos valores los calcula automáticamente la Renta; se muestran para verificar los datos una vez introducidos.
- **Secciones colapsables por activo**: cada grupo muestra en la cabecera los totales de casilla 0328 y 0331 con botón 👁 verificar, y se puede desplegar para ver las operaciones individuales con sus fechas, importes en USD, tipos de cambio y ganancia/pérdida en EUR (sin botón).
- La columna **Ganancia €** no lleva botón: es un resultado intermedio del programa, no una casilla a introducir directamente.

### Retenciones EEUU — doble imposición (casillas 0588–0589)
- La sección "Nonresident alien withholding" de Fidelity contiene retenciones sobre dividendos y ajustes/devoluciones.
- Los importes negativos son retenciones efectivas; los positivos son ajustes o devoluciones.
- Se suman todos (neto) y se convierte a EUR al tipo BCE de cada fecha.
- El valor absoluto del neto es la deducción por doble imposición.

> **Nota fiscal incluida en el informe**: la deducción por doble imposición está limitada al menor de: (a) impuesto efectivamente pagado en el extranjero, o (b) tipo medio efectivo español aplicado a esas rentas. El programa solo calcula (a). El usuario debe verificar el límite con su asesor fiscal.

### Ganancias patrimoniales crypto (casillas 0328–0337)
- Se toman directamente del informe de Koinly, que ya los proporciona en EUR calculados con método FIFO.
- No se aplica conversión de divisa (los valores ya están en EUR).

### Rendimientos de staking/rewards crypto
- Se toman directamente de Koinly (ya en EUR).
- Se presenta un resumen agrupado por activo y un detalle expandible con todas las operaciones individuales.

> **Nota fiscal incluida en el informe**: la calificación fiscal de los rendimientos de staking en España no está definitivamente establecida. El usuario debe consultar con su asesor fiscal si corresponde declararlos como rendimientos del capital mobiliario u otro tipo de renta.

---

## Arquitectura de parsers

### Registry

Los parsers están registrados en `src/renta/parsers/__init__.py` en la lista `REGISTRY`. Cada módulo parser expone un contrato de 6 funciones:

| Función | Firma | Propósito |
|---------|-------|-----------|
| `detect(first_page_text: str) -> bool` | Texto de la primera página del PDF | Determinar si el PDF pertenece a este parser |
| `parse(pdf_path: Path) -> XxxData` | Ruta al PDF | Parsear el PDF y devolver un dataclass con los datos |
| `validate(data: XxxData) -> list[str]` | Datos parseados | Comparar totales parseados con los del resumen del PDF |
| `stats_summary(data: XxxData) -> str` | Datos parseados | Resumen de una línea para la salida CLI |
| `year_hint(data: XxxData) -> int \| None` | Datos parseados | Año fiscal autodetectado, o None |
| `usd_dates(data: XxxData) -> set[date]` | Datos parseados | Fechas que necesitan conversión USD→EUR |

El CLI (`cli.py`) itera el registry para la detección, parsing, validación y recolección de fechas USD, sin necesidad de modificarlo al añadir nuevos parsers.

Cada `Casilla` generada por el Calculator lleva un campo `template` con el nombre de su template parcial HTML (ej. `_dividendos.html`), y un campo `extras` con datos adicionales para el template. El informe HTML itera `result.casillas` dinámicamente para renderizar las secciones.

### Cómo añadir un nuevo parser

Para añadir soporte para un nuevo tipo de documento:

1. **Crear el módulo parser** en `src/renta/parsers/<broker>.py` implementando las 6 funciones del contrato.
2. **Añadir dataclasses** en `src/renta/models.py` para los datos parseados (ej. `BrokerData`).
3. **Registrarlo** añadiendo una línea en `parsers/__init__.py`:
   ```python
   REGISTRY.append(("broker", broker))
   ```
4. **Conectar con el Calculator** en `calculator.py`:
   - Si el nuevo broker produce datos que mapean a casillas existentes (ej. más dividendos o más ventas de acciones), basta con concatenar sus listas con las existentes antes de llamar a los `_calc_*` correspondientes.
   - Si introduce un concepto fiscal nuevo, hay que escribir un nuevo método `_calc_*`, crear un template parcial en `templates/`, y añadir el campo correspondiente a `ResultadoRenta`.
5. **Añadir tests** en `tests/test_<broker>.py` y factories en `tests/factories.py`.

**No es necesario tocar** `cli.py`, `report.html` ni `report.py`.

### Decisiones de implementación

### Fidelity
- El PDF es un "Save as PDF" de una página HTML, lo que resulta en celdas de tabla que contienen múltiples filas como texto multilinea.
- El parser extrae el texto de la celda de datos de cada página y aplica regex línea a línea.
- La detección de secciones se hace por texto marcador ("Dividend income", "Stock sales", "Nonresident alien withholding") en la celda de cabecera.
- El parser es genérico: no hardcodea páginas ni número de filas. Funciona con cualquier año y cualquier número de transacciones.
- Validación automática: se compara el total parseado con el resumen de la página 1 del PDF. El "Total" del resumen de ventas corresponde a la ganancia/pérdida neta, no a los ingresos totales.
- Los dividendos y retenciones de Fidelity se etiquetan con el nombre fijo `ORCL / FYIXX (US)` en el informe HTML (Oracle Corp y el fondo del plan de empresa, ambos de EEUU).

### Koinly
- El PDF no tiene tablas detectables por pdfplumber; todos los datos están en texto plano.
- El parser extrae el texto de cada página y aplica regex línea a línea.
- La detección de secciones requiere que el marcador sea una **línea propia** en el texto (para evitar falsos positivos con el índice/tabla de contenidos de la primera página).
- El parser es genérico: funciona con cualquier año y cualquier número de transacciones y activos.

### DEGIRO
- El "Informe Fiscal Anual" de flatexDEGIRO es un PDF con texto plano extraíble.
- **Todos los importes ya están en EUR**: no se requiere conversión de divisa.
- **Sección de dividendos** (busca marcador "Dividendos recibidos"):
  - Filas con código de país (2 letras mayúsculas al inicio) = pagos individuales.
  - Filas sin código de país = *running totals* acumulados → se ignoran como datos individuales, pero la **última running total** se usa como total de validación.
- **Sección de ventas** (dos variantes, según el año del informe):
  - *Sección detallada* (2025+): marcador "Beneficios y pérdidas derivadas de la transmisión de elementos patrimoniales". Contiene una fila por operación con fecha, ISIN, tipo de cambio y ganancia/pérdida.
  - *Sección resumida* (2024): marcador "Relación de ganancias y pérdidas por producto". Solo contiene la fila "Total" (suele ser 0,00 EUR si no hubo ventas). Se ignoran las filas individuales de esta sección (no tienen datos suficientes).
  - El parser usa la sección detallada si existe, y el fallback resumido en caso contrario.
- **Formato numérico**: coma decimal + punto para miles (estilo español). Ej: `1.234,56 EUR` → `Decimal("1234.56")`.
- **Retenciones en origen**: no hay una sección separada; la retención de cada dividendo está en la misma tabla como columna "Retenciones a cuenta" (valor negativo). El calculator las usa para la casilla de doble imposición.
- **Integración con el Calculator**: los datos DEGIRO se mezclan con los de Fidelity mediante `_merge_casillas()`, que concatena los desgloses y suma los valores. Las columnas que no aplican (fecha USD, tipo de cambio USD) se dejan con "—" en los extras de cada `LineaDetalle`.

---

## Validaciones

El programa compara automáticamente los totales parseados con los totales del resumen del propio PDF:

| Check | Fuente del total esperado |
|-------|--------------------------|
| Dividendos totales USD | Resumen pág. 1 de Fidelity |
| Ganancia/pérdida neta de ventas USD | Resumen pág. 1 de Fidelity |
| Retenciones netas USD | Resumen pág. 1 de Fidelity |
| Ganancias netas crypto EUR | Resumen pág. 2 de Koinly |
| Total rewards EUR | Resumen pág. 3 de Koinly |
| Dividendos brutos EUR (DEGIRO) | Última running total de la tabla de dividendos |
| Retenciones en origen EUR (DEGIRO) | Última running total de la tabla de dividendos |
| Ganancia/pérdida neta ventas EUR (DEGIRO) | Fila "Total" de la sección de ventas |

Si hay discrepancias, se muestran como advertencias en la consola y en el informe HTML.

---

## Manejo de errores en tipos de cambio

Cuando no se puede obtener el tipo BCE para una fecha:

- La fila afectada se renderiza en **rojo** en el informe HTML con el motivo del error.
- El campo `importe_eur` de la fila queda a `None` (no se usa ningún valor ficticio).
- La fila **no se suma** al total de la casilla.
- Si alguna fila de una casilla tiene error, el valor de la casilla es `None` y el informe muestra "NO CALCULABLE" con un badge de error.
- Se registra un warning en el resumen indicando cuántas operaciones no pudieron calcularse.

---

## Limitaciones conocidas

- Solo soporta los PDFs de Fidelity, Koinly y DEGIRO mencionados. Añadir nuevos brokers requiere escribir un nuevo parser (ver sección "Cómo añadir un nuevo parser").
- La deducción por doble imposición muestra solo el impuesto pagado en EEUU; el límite legal (tipo medio efectivo español) no se calcula automáticamente.
- La calificación fiscal de los rewards de staking es incierta en España y puede cambiar con nuevas resoluciones de la DGT.
- No se genera la declaración directamente: el output es un informe de ayuda que el usuario debe trasladar manualmente al modelo 100.
