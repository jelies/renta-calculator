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

Los PDFs se detectan automáticamente por contenido (busca "Fidelity" o "Koinly" en la primera página). No es necesario nombrarlos de ninguna forma concreta.

### Formato de entrada

- Solo PDFs. No se soportan CSVs ni otros formatos.
- Los ficheros se pasan indicando un directorio; el programa detecta cuál es de cada fuente.

---

## Salida

- Un único fichero **HTML autocontenido**: sin dependencias externas, sin JavaScript, sin imágenes externas. Se puede abrir en cualquier navegador y guardar/imprimir sin conexión.
- El HTML incluye:
  - Resumen de casillas con el importe final en EUR
  - Tablas de detalle por sección (dividendos, ventas de acciones, retenciones, ganancias crypto, rewards)
  - Columna de **trazabilidad** en cada fila: nombre del PDF, número de página y fila de origen
  - Tabla de tipos de cambio BCE utilizados
  - Notas y advertencias fiscales

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
| **0029** | Dividendos (rendimientos del capital mobiliario) | Fidelity — sección "Dividend income" |
| **0328–0337** | Ganancias/pérdidas patrimoniales — acciones RSU | Fidelity — sección "Stock sales" |
| **0328–0337** | Ganancias/pérdidas patrimoniales — criptomonedas | Koinly — "Operaciones de Ganancias Patrimoniales" |
| **0588–0589** | Deducción por doble imposición internacional | Fidelity — sección "Nonresident alien withholding" |
| Rend. cap. mob. | Rendimientos de staking/rewards crypto | Koinly — "Operaciones de rendimientos" |

---

## Tipos de cambio (USD → EUR)

- Se obtienen automáticamente de la **API del Banco Central Europeo**.
- Endpoint: `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A`
- El tipo BCE es "USD por 1 EUR" (ej: 1.085 = 1 EUR vale 1.085 USD). Conversión: `EUR = USD / tipo`.
- El rango descargado cubre **todas las fechas necesarias**: si hay vesting dates de años anteriores al ejercicio fiscal, se descarga el rango desde el año más antiguo hasta el más reciente, en una sola petición.
- Para días no hábiles (fines de semana, festivos), se usa el tipo del **último día hábil anterior** (retrocede hasta 14 días).
- Los tipos de cambio se cachean en memoria durante la sesión para evitar peticiones repetidas.
- **Si no se puede obtener el tipo de cambio** para una fecha (sin conexión, fecha fuera de rango, etc.): la fila se marca con error y se excluye del total. La casilla muestra "NO CALCULABLE" si alguna fila falla. **Nunca se usa un tipo ficticio** (ej. 1:1) que produciría valores incorrectos sin avisar.

---

## Reglas de cálculo

### Dividendos (casilla 0029)
- Cada dividendo en USD se convierte a EUR usando el tipo BCE de la **fecha del dividendo**.
- Se suman todos para obtener el total de la casilla 0029.

### Ventas de acciones RSU (casillas 0328–0337)

**Decisión clave**: se usan **dos tipos de cambio distintos** por operación:
- El **valor de adquisición** (cost basis) se convierte al tipo BCE de la **fecha de vesting** (columna "Date acquired" en Fidelity). Razón: el coste real en EUR se produce en el momento en que las acciones se adquieren/liberan.
- El **valor de transmisión** (proceeds) se convierte al tipo BCE de la **fecha de venta** (columna "Date sold or transferred").
- La ganancia/pérdida en EUR = valor transmisión EUR − valor adquisición EUR.

> **Nota fiscal incluida en el informe**: el cost basis de Fidelity es el FMV (Fair Market Value) al vesting en USD. Fiscalmente, el valor de adquisición correcto para RSUs es el FMV en EUR a fecha de vesting (momento en que tributaron como rendimiento del trabajo). La conversión al tipo BCE de esa fecha es la aproximación más correcta disponible con los datos del PDF.

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

## Parsers — decisiones de implementación

### Fidelity
- El PDF es un "Save as PDF" de una página HTML, lo que resulta en celdas de tabla que contienen múltiples filas como texto multilinea.
- El parser extrae el texto de la celda de datos de cada página y aplica regex línea a línea.
- La detección de secciones se hace por texto marcador ("Dividend income", "Stock sales", "Nonresident alien withholding") en la celda de cabecera.
- El parser es genérico: no hardcodea páginas ni número de filas. Funciona con cualquier año y cualquier número de transacciones.
- Validación automática: se compara el total parseado con el resumen de la página 1 del PDF. El "Total" del resumen de ventas corresponde a la ganancia/pérdida neta, no a los ingresos totales.

### Koinly
- El PDF no tiene tablas detectables por pdfplumber; todos los datos están en texto plano.
- El parser extrae el texto de cada página y aplica regex línea a línea.
- La detección de secciones requiere que el marcador sea una **línea propia** en el texto (para evitar falsos positivos con el índice/tabla de contenidos de la primera página).
- El parser es genérico: funciona con cualquier año y cualquier número de transacciones y activos.

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

- Solo soporta los PDFs de Fidelity y Koinly mencionados. Añadir nuevos brokers requiere escribir un nuevo parser.
- La deducción por doble imposición muestra solo el impuesto pagado en EEUU; el límite legal (tipo medio efectivo español) no se calcula automáticamente.
- La calificación fiscal de los rewards de staking es incierta en España y puede cambiar con nuevas resoluciones de la DGT.
- No se genera la declaración directamente: el output es un informe de ayuda que el usuario debe trasladar manualmente al modelo 100.
