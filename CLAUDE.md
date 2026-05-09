# Reglas para Claude Code

## Nunca uses valores inventados en cálculos

Si no puedes obtener un dato real necesario para un cálculo (por ejemplo, el tipo de cambio USD/EUR desde una API, el precio de adquisición de un activo, o cualquier otro valor externo), **NO uses un valor por defecto inventado o aproximado**.

En su lugar:
- Marca el valor como no disponible de forma visible (error, warning, texto en rojo si aplica).
- Deja el cálculo sin realizar.
- Indica claramente qué dato falta y por qué no se pudo obtener.

**Correcto:** `"No calculado: no se pudo obtener el tipo de cambio USD/EUR (API no disponible)"`

**Incorrecto:** asumir silenciosamente `1 USD = 1 EUR` y continuar con el cálculo.

Es preferible un resultado incompleto y explicado que un resultado incorrecto y silencioso.

## Mantén los tests al día con el código

Cada vez que modifiques código en `src/renta/`, actualiza o añade los tests correspondientes en `tests/` para que sigan cubriendo el comportamiento cambiado.

- Si cambias lógica existente → actualiza los tests afectados.
- Si añades funcionalidad nueva → añade tests que la cubran.
- Si eliminas código → elimina los tests que ya no apliquen.

Tras cualquier cambio, ejecuta `pytest` para verificar que todo sigue en verde.

## Decisiones de diseño del informe HTML

### Botones copy vs verify

- `copy` (portapapeles): el valor que **introduces tú** en AEAT.
- `verify` (ojo): el valor que **AEAT calcula** a partir de los que has introducido; lo usas para comprobar que coincide.

### Asimetría copy/verify entre stocks y crypto en el resumen por activo

En `_ventas_acciones.html`, las columnas Ganancias y Pérdidas **por activo** llevan `verify` con casilla AEAT (336/337/338) porque en stocks el formulario pide introducir los valores brutos por activo.

En `_ganancias_crypto.html`, esas mismas columnas **no llevan botón** (`button=none`). El `verify` aparece solo en la columna Balance (casillas 1809/1807/1808) porque en crypto el formulario pide el balance neto por activo, no los valores brutos.

Esta asimetría es intencional — refleja la estructura del formulario AEAT, no una inconsistencia de diseño. No "corregir".

### Criterio — vs NO CALCULADO

- `—`: el valor no aplica o no está disponible en el origen (campo que no viene en el PDF, caso ya avisado por otra columna, etc.).
- `NO CALCULADO` (rojo, `error-text`): el dato existe pero el cálculo ha fallado por error (falta tipo de cambio, dependencia rota, etc.).

## graphify

Este proyecto tiene un grafo de conocimiento de graphify en graphify-out/.

Reglas:
- Antes de responder preguntas de arquitectura o código, lee graphify-out/GRAPH_REPORT.md para la estructura de nodos y comunidades
- Si existe graphify-out/wiki/index.md, navégalo en lugar de leer ficheros raw
- Para preguntas de "cómo se relaciona X con Y", usa `graphify query "<pregunta>"`, `graphify path "<A>" "<B>"`, o `graphify explain "<concepto>"` en lugar de grep — estos recorren los enlaces EXTRACTED + INFERRED del grafo
- Tras modificar ficheros de código en esta sesión, ejecuta `graphify update .` para mantener el grafo actualizado (solo AST, sin coste de API)
