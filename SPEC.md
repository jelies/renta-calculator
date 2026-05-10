# Especificación funcional — renta

Documento de referencia con los requisitos y decisiones funcionales tomadas durante el diseño del programa.

---

## Objetivo

Calcular automáticamente las casillas de la declaración de la renta española (modelo 100) relacionadas con inversiones en bolsa y criptomonedas, a partir de los informes que generan los brokers, y producir un informe con trazabilidad completa que permita verificar cada cifra.

---

## Entradas

### Fuentes soportadas

| Broker/Plataforma | Tipo de informe | Si falta |
|-------------------|-----------------|----------|
| **Fidelity NetBenefits** | "Custom transaction summary" descargado como PDF desde la web | Aviso, continúa |
| **Koinly** | "Complete tax report" en español (PDF) | Aviso, continúa |
| **Koinly** | "Informe de plusvalías para España" (PDF) | Silencioso (opcional) |
| **DEGIRO** | "Informe Fiscal Anual" (PDF) — flatexDEGIRO Bank AG | Aviso, continúa |

Los PDFs se detectan automáticamente por contenido: cada parser registrado expone una función `detect()` que examina el texto de la primera página. No es necesario nombrar los ficheros de ninguna forma concreta.

### Formato de entrada

- Solo PDFs. No se soportan CSVs ni otros formatos.
- Los ficheros se pasan indicando un directorio; el programa detecta cuál es de cada fuente.

---

## Salida

- Un único fichero **HTML autocontenido**: sin dependencias externas, sin imágenes externas. Se puede abrir en cualquier navegador y guardar/imprimir sin conexión.
- El HTML incluye:
  - Resumen de casillas con el importe final en EUR; cada concepto es un enlace que salta a su sección de detalle
  - Tablas de detalle por sección (dividendos, ventas de acciones, retenciones, ganancias crypto, rewards)
  - Columna de **trazabilidad** en cada fila: nombre del PDF, número de página y fila de origen
  - Tabla de tipos de cambio BCE utilizados
  - Notas y advertencias fiscales
  - **Botones de acción** junto a los importes en EUR: copian el valor al portapapeles en formato ES (punto separador de miles, coma decimal, sin símbolo de moneda ni signo; ej. `6.523,22`). Hay dos tipos distintos, identificados visualmente por su icono SVG:
    - 📋 **Copiar** (`copy-btn`): valores que el usuario debe introducir manualmente en el modelo 100. En ventas de acciones: columnas "Valor transmisión €" y "Valor adquisición €" de cada operación (casillas 0328 y 0331). En dividendos: total por activo de la tabla resumen (casilla 0029 por activo).
    - 👁 **Verificar** (`copy-btn verify-btn`): valores que la Renta calcula automáticamente a partir de los datos introducidos, y que se muestran para que el usuario pueda cuadrarlos. En ventas: casillas 0336, 0337/0338, 0339, 0340 (tabla resumen), y totales por activo de 0328/0331 (cabecera de cada grupo colapsable). En dividendos: total global de la fila "Total" de la tabla resumen.
    - La columna "Ganancia €" no lleva botón: es un cálculo interno del programa, no un valor a trasladar directamente.
    - **Shift+click** sobre cualquier botón restaura su estado original (icono SVG, sin marca de copiado) sin copiar nada.
  - Se ocultan al imprimir.
  - **Modo privado (blur)**: botón en la cabecera del informe que difumina todos los importes (clases `.money`, `.cell-value`, `.kpi-val`, `.amount-strong`, etc.). El estado se persiste en `localStorage('renta-private')` y se restaura al reabrir el fichero. Es un control visual para compartir pantalla sin exponer cifras; no afecta al contenido del HTML.
  - **Tema claro/oscuro**: botón en la cabecera que alterna entre tema claro y oscuro, persistido en `localStorage('renta-theme')`.

---

## Interfaz

CLI (línea de comandos):

```bash
renta-calculator --input carpeta/ [--output fichero.html] [--year 2024]
```

Todos los flags admiten forma corta: `-i`, `-o`, `-y`.

- `--year` es opcional; si no se especifica, se autodetecta del año de la primera transacción encontrada en los PDFs. Si ningún parser puede determinarlo (situación excepcional), el programa termina con error y pide que se use `--year`.
- `--output` es opcional; si se omite, el informe se escribe en `output/renta_{año}_{ddmmYYYY_HHMM}.html` (se crea el directorio si no existe).
- Si se detectan múltiples PDFs del mismo tipo en el directorio, se usa el primero encontrado y se emite una advertencia por stderr.
- Al finalizar, el CLI imprime un aviso recordando que los resultados son una ayuda para el cálculo y deben ser verificados antes de presentarlos a Hacienda.

---

## Casillas del modelo 100 calculadas

| Casilla | Concepto | Fuente |
|---------|----------|--------|
| **0029** | Rendimientos del capital mobiliario - Dividendos | Fidelity — "Dividend income" + DEGIRO — "Dividendos recibidos" |
| **0326–0340** | Ganancias/pérdidas patrimoniales - Ventas de acciones | Fidelity — "Stock sales" + DEGIRO — ventas detalladas |
| **1800–1814** | Ganancias/pérdidas patrimoniales - Venta de cryptos | Koinly — "Operaciones de Ganancias Patrimoniales" |
| **0588** | Deducción por doble imposición internacional | Fidelity — "Nonresident alien withholding" + DEGIRO — retenciones en origen |
| **0033** | Rendimientos de capital mobiliario - Staking/Rewards crypto | Koinly — "Operaciones de rendimientos" (tipo `Reward`) |
| **0034** | Rendimientos de capital mobiliario - Airdrops crypto | Koinly — "Operaciones de rendimientos" (tipo `Airdrop`) |

---

## Tipos de cambio (USD → EUR)

- Se obtienen automáticamente de la **API del Banco Central Europeo**.
- Endpoint: `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A`
- El tipo obtenido es el **tipo de referencia oficial diario del BCE**, publicado una vez al día alrededor de las **16:00 CET**. No es un precio de cierre de mercado, sino un valor único de referencia calculado por el BCE a partir de un procedimiento concertado entre bancos centrales. Es el tipo aceptado por la AEAT para valorar operaciones en divisas.
- El tipo BCE es "USD por 1 EUR" (ej: 1,085 = 1 EUR vale 1,085 USD). Conversión: `EUR = USD / tipo`.
- El rango descargado cubre **todas las fechas necesarias**: si hay vesting dates de años anteriores al ejercicio fiscal, se realiza una sola petición al BCE desde `min_fecha − 7 días` hasta `max_fecha` (el margen de 7 días absorbe fines de semana previos a la fecha más antigua).
- Para días no hábiles (fines de semana, festivos), se usa el tipo del **último día hábil anterior** (retrocede hasta 14 días).
- Los tipos de cambio se cachean en memoria durante la sesión para evitar peticiones repetidas.
- **Si no se puede obtener el tipo de cambio** para una fecha (sin conexión, fecha fuera de rango, etc.): la fila se marca con error y se excluye del total. La casilla muestra "NO CALCULABLE" si alguna fila falla. **Nunca se usa un tipo ficticio** (ej. 1:1) que produciría valores incorrectos sin avisar.

---

## Reglas de cálculo

### Ventas de acciones RSU (casillas 0326–0340)

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

### Dividendos (casilla 0029)
- Cada dividendo en USD se convierte a EUR usando el tipo BCE de la **fecha del dividendo**.
- Se agrupan por activo y se suma el total por activo.
- La casilla 0029 se introduce **una vez por activo** con su total (no el global).

En el informe HTML:

- **Tabla resumen** (siempre visible): una fila por activo con su total EUR y botón 📋 copiar. Fila de totales con el global y botón 👁 verificar.
- **Secciones colapsables por activo**: detalle de cada dividendo con fecha, importe $, tipo de cambio e importe €.

### Retenciones EEUU — doble imposición (casilla 0588)
- La sección "Nonresident alien withholding" de Fidelity contiene retenciones sobre dividendos y ajustes/devoluciones.
- Los importes negativos son retenciones efectivas; los positivos son ajustes o devoluciones.
- Se suman todos (neto) y se convierte a EUR al tipo BCE de cada fecha.
- El valor absoluto del neto es el "Impuesto satisfecho en el extranjero" (casilla 0588).
- En la práctica, el PDF de Fidelity de un año dado puede incluir retenciones cuya fecha pertenece al año anterior (ya declaradas). Estas filas se detectan, se excluyen del total y se marcan en el informe (ver "Operaciones fuera del año fiscal").

En el informe HTML, la **tabla resumen de retenciones** muestra por activo los dos valores que solicita Renta Web al introducir retenciones en el extranjero:

- **Rentas incluidas en la base del ahorro** (tomado de `grupos_dividendos` de la casilla 0029, por ticker): el total de dividendos del activo. Lleva botón 📋 copiar.
- **Impuesto satisfecho en el extranjero** (casilla 0588): la retención neta del activo. Lleva botón 📋 copiar.

La fila de totales muestra el global de cada columna con botón 👁 verificar.

> **Nota incluida en el informe**: Renta Web aplica automáticamente el límite legal (menor de: impuesto efectivamente pagado en el extranjero vs. tipo medio efectivo español). Por eso el informe se limita a indicar que se introduzcan los importes calculados en la casilla 0588.

### Ganancias patrimoniales crypto (casillas 1800–1814)
- Se toman directamente del informe de Koinly, que ya los proporciona en EUR calculados con método FIFO.
- No se aplica conversión de divisa (los valores ya están en EUR).
- Los **detalles operación a operación** siempre vienen del *Complete tax report*.
- Los **totales de adquisición (`Total adquisiciones`, casilla 1806) y transmisión (`Total transmisiones`, casilla 1804) por activo** se obtienen con la siguiente prioridad:
  1. **"Informe de plusvalías para España"** (Spain report, opcional): columna "Valor (EUR)" = total adquisición; columna "Ingresos (EUR)" = total transmisión. Solo se procesan las filas de totales por activo (e.g. `ABC 100,00 150,00 50,00`); las sub-filas por categoría (`ABC fue vendido por fiat...`) se ignoran automáticamente.
  2. **Fallback**: suma de `cost_eur` / `proceeds_eur` de las operaciones individuales del activo. Puede arrastrar pequeños errores de redondeo.
  - El override es silencioso (sin warning) y por activo: si el Spain report sólo cubre algunos activos, el resto mantiene el cálculo por suma.
- Las **Ganancias y Pérdidas por activo** (tabla resumen del informe HTML) se obtienen de la tabla "Resumen de activos" del *Complete tax report* cuando está disponible, o de la suma de operaciones como fallback. Estas columnas son independientes de los totales de adquisición/transmisión.

En el informe HTML:

- **Tabla resumen** (siempre visible): una fila por activo con sus Ganancias y Pérdidas (del *Complete tax report* cuando disponibles, suma de operaciones como fallback). Fila de totales con el global.
- **Secciones colapsables por activo**: la cabecera muestra `Transmisiones` y `Adquisiciones` (del Spain report si disponible, suma de operaciones si no). El detalle incluye cada operación con fechas, cantidad, transmisión EUR, adquisición EUR y ganancia/pérdida EUR (siempre del *Complete tax report*, sin modificar).

### Rendimientos de staking/rewards crypto (casilla 0033)
- Se toman directamente de Koinly (ya en EUR). Solo se incluyen operaciones con `reward_type == "Reward"`.
- El **total** se obtiene de la línea `Reward` del "Resumen de rendimientos" del PDF (no de la suma de las operaciones individuales ni del campo `Total` del bloque). Esto evita el error de redondeo acumulado al sumar filas ya redondeadas a 2 decimales.
- La línea `Other income` del mismo bloque se ignora deliberadamente: su origen es desconocido y aún no tiene casilla asignada en el modelo 100.
- Si el resumen del PDF no está disponible, se usa la suma de las operaciones individuales como fallback.
- Se presenta un resumen agrupado por activo y un detalle expandible con todas las operaciones individuales.

> **Nota fiscal incluida en el informe**: la calificación fiscal de los rendimientos de staking en España no está definitivamente establecida. El usuario debe consultar con su asesor fiscal si corresponde declararlos como rendimientos del capital mobiliario u otro tipo de renta.

### Airdrops crypto (casilla 0034)
- Se toman directamente de Koinly (ya en EUR). Solo se incluyen operaciones con `reward_type == "Airdrop"`.
- El parser comparte el regex `_REWARD_RE` con los rewards (acepta `Reward|Airdrop`) y luego separa las listas por tipo.
- El **total** se obtiene de la línea `Airdrop` del "Resumen de rendimientos" del PDF. Si no está disponible, se usa la suma de las operaciones individuales como fallback.
- Se presenta un resumen agrupado por activo y un detalle expandible, igual que la sección 0033.

> **Nota fiscal incluida en el informe**: la calificación fiscal de los airdrops en España puede variar según el origen y las condiciones. El usuario debe consultar con su asesor fiscal.

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

Cada entrada del registry es una **3-tupla** `(nombre, módulo, optional)`. El flag `optional` controla si se emite aviso cuando el PDF no está presente — en ningún caso es un error fatal (la herramienta siempre continúa con los PDFs que encuentre, y solo falla si no reconoce ninguno). Actualmente solo `koinly_spain` es opcional (sin aviso).

El CLI (`cli.py`) itera el registry para la detección, parsing, validación y recolección de fechas USD, sin necesidad de modificarlo al añadir nuevos parsers.

Cada `Casilla` generada por el Calculator lleva un campo `template` con el nombre de su template parcial HTML (ej. `_dividendos.html`), y un campo `extras` con datos adicionales para el template. El informe HTML itera `result.casillas` dinámicamente para renderizar las secciones.

#### Convenciones de templates parciales

Todos los templates parciales siguen el mismo orden canónico al inicio de la sección:

```jinja
{{ section_h2(casilla, 'Título de la sección') }}
{{ note_block(casilla) }}
{{ casilla_warnings_block(casilla) }}
{# <div class="instrucciones">...</div>  — solo si la sección tiene instrucciones de relleno #}
```

Los macros de `_macros.html` relevantes para las secciones:

- `section_h2(casilla, title)` — renderiza el `<h2>` con `id` y badge de casilla usando `render_casilla`.
- `note_block(casilla)` — panel azul con `casilla.notas` / `casilla.notas_secciones`. No renderiza nada si está vacío.
- `casilla_warnings_block(casilla)` — panel amarillo con `bce_warnings` y `advertencias`. No renderiza nada si está vacío.
- `td_eur(amount, color, sign, button, extra_class)` — celda `<td>` con importe en EUR. `button='copy'` (defecto), `'verify'`, o cualquier otro valor para sin botón.
- `section_total(casilla, label, with_sign)` — bloque destacado de total de sección con botón copiar.
- `cell_amount(amount, casilla, casillas, button, abs_value)` — importe inline con badge de casilla opcional.
- `td_source(source, extra_class)` / `td_source_short(source, extra_class, multi)` — celda de trazabilidad (PDF + página).
- `empty_state(message)` — mensaje de sección vacía.
- `render_casilla(numero_str)` / `casilla_badge(numero)` — renderiza badges de casilla (soporta rangos `X-Y` y listas `X/Y`).
- `copy_btn(amount)` / `verify_btn(amount)` / `copy_btn_str(eur_str)` / `verify_btn_str(eur_str)` — botones de portapapeles sueltos.
- `pluralize(n, singular, plural)` — pluralización de textos.

La nota informativa de la casilla (`casilla.notas`) va siempre en el panel azul (`note_block`). Las instrucciones de relleno del formulario AEAT van en el panel verde (`<div class="instrucciones">`).

Criterio `—` vs `NO CALCULADO`: ver CLAUDE.md → "Decisiones de diseño del informe HTML".

### Cómo añadir un nuevo parser

Para añadir soporte para un nuevo tipo de documento:

1. **Crear el módulo parser** en `src/renta/parsers/<broker>.py` implementando las 6 funciones del contrato.
2. **Añadir dataclasses** en `src/renta/models.py` para los datos parseados (ej. `BrokerData`).
3. **Registrarlo** añadiendo una línea en `parsers/__init__.py`:
   ```python
   REGISTRY.append(("broker", broker, False))  # False = avisa si falta; True = silencioso si falta
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
- **Columnas `Anotaciones` y `Wallet Name`**: se extraen por posición mediante `pdfplumber.extract_words()`. El parser localiza los `x0` de las cabeceras `Anotaciones` y `Wallet Name` en la página, y asigna a cada fila las palabras que caen en el rango de cada columna (con tolerancia de 5 pt para imprecisiones de alineación). Este enfoque evita heurísticas de texto y funciona con wallets de nombre compuesto.
- **Tabla "Resumen de activos"**: se extrae de las primeras páginas del PDF (≤8) para obtener los totales oficiales de ganancias/pérdidas por activo, que se usan en la tabla resumen del informe en lugar de la suma de operaciones individuales.
- **"Informe de plusvalías para España" (`koinly_spain`)**: parser separado que lee la tabla de una página con columnas `Activo / Valor (EUR) / Ingresos (EUR) / Ganancia`. Solo se extraen filas de totales por activo (patrón: ticker + exactamente 3 números); las sub-filas por categoría (`"ABC fue vendido por fiat..."`) no casan con el patrón y se descartan automáticamente. La función `detect()` del *Complete tax report* excluye explícitamente este PDF comprobando que el texto de la primera página no contenga `"informe de plusval"`.
- **Formato decimal**: tanto el *Complete tax report* como el Spain report usan coma como separador decimal (`1.234,56`). Ambos parsers reutilizan la función `_parse_decimal` con soporte de formato europeo.

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
| Rewards EUR (línea `Reward`) | "Resumen de rendimientos" de Koinly (excluye `Other income` y el `Total` del bloque) |
| Airdrops EUR (línea `Airdrop`) | "Resumen de rendimientos" de Koinly (excluye `Other income` y el `Total` del bloque) |
| Dividendos brutos EUR (DEGIRO) | Última running total de la tabla de dividendos |
| Retenciones en origen EUR (DEGIRO) | Última running total de la tabla de dividendos |
| Ganancia/pérdida neta ventas EUR (DEGIRO) | Fila "Total" de la sección de ventas |

Si hay discrepancias, se muestran como advertencias en la consola y en el informe HTML, dentro de la sección correspondiente.

---

## Operaciones fuera del año fiscal

El PDF de Fidelity puede incluir transacciones cuya fecha pertenece a un ejercicio fiscal distinto al que se está calculando (p.ej. retenciones de 2024 presentes en el informe de 2025). Incluirlas supondría una doble declaración.

Para las tres categorías de Fidelity (dividendos, retenciones y ventas de acciones), el Calculator compara `entry.date.year` con el año fiscal activo:

- Si no coinciden: la fila se añade al desglose con `aviso="Operación fuera del año fiscal {year} — excluida del total"` y `importe_eur=None`. No se suma al total de la casilla ni al total del grupo.
- El total de la casilla y del grupo **sigue calculándose** con las filas válidas restantes (a diferencia de los errores de tipo de cambio, que invalidan el grupo y la casilla completa).
- Se registra un warning en la salida CLI con la fecha completa de la operación excluida.
- En el informe HTML (sección retenciones), la fila aparece en **amarillo/naranja** (`warning-row`) con badge "AVISO" en la cabecera del grupo. En dividendos y ventas de acciones la fila aparece en rojo (comportamiento heredado; pendiente de homogeneizar).

---

## Manejo de errores en tipos de cambio

Cuando no se puede obtener el tipo BCE para una fecha:

- La fila afectada se renderiza en **rojo** en el informe HTML con el motivo del error.
- El campo `importe_eur` de la fila queda a `None` (no se usa ningún valor ficticio).
- La fila **no se suma** al total de la casilla.
- Si alguna fila de una casilla tiene error, el valor de la casilla es `None` y el informe muestra "NO CALCULABLE" con un badge de error.
- Se registra un warning en el resumen indicando cuántas operaciones no pudieron calcularse.

---

## Diseño del informe HTML

### Botones copy vs verify

- `copy` (portapapeles): el valor que **introduce el usuario** en AEAT.
- `verify` (ojo): el valor que **AEAT calcula** a partir de los que se han introducido; sirve para comprobar que coincide.

### Asimetría copy/verify entre stocks y crypto en el resumen por activo

En `_ventas_acciones.html`, las columnas Ganancias y Pérdidas **por activo** llevan `verify` con casilla AEAT (336/337/338) porque en stocks el formulario pide introducir los valores brutos por activo.

En `_ganancias_crypto.html`, esas mismas columnas **no llevan botón** (`button=none`). El `verify` aparece solo en la columna Balance (casillas 1809/1807/1808) porque en crypto el formulario pide el balance neto por activo, no los valores brutos.

Esta asimetría es intencional — refleja la estructura del formulario AEAT, no una inconsistencia de diseño.

### Criterio — vs NO CALCULADO

- `—`: el valor no aplica o no está disponible en el origen (campo que no viene en el PDF, caso ya avisado por otra columna, etc.).
- `NO CALCULADO` (rojo, `error-text`): el dato existe pero el cálculo ha fallado por error (falta tipo de cambio, dependencia rota, etc.).

---

## Limitaciones conocidas

- Solo soporta los PDFs de Fidelity, Koinly y DEGIRO mencionados. Añadir nuevos brokers requiere escribir un nuevo parser (ver sección "Cómo añadir un nuevo parser").
- La calificación fiscal de los rewards de staking es incierta en España y puede cambiar con nuevas resoluciones de la DGT.
- No se genera la declaración directamente: el output es un informe de ayuda que el usuario debe trasladar manualmente al modelo 100.
