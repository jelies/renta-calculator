# Auditoría fiscal — Sección "Venta de acciones" (casillas 0326–0340)

> Auditoría del código desde el punto de vista de un asesor fiscal, centrada
> exclusivamente en la sección **venta de acciones**: cálculos, uso de los tipos
> de cambio EUR/USD y resultados mostrados. Cubre la ruta Fidelity (RSU) y DEGIRO.
>
> Ficheros revisados: `calculator.py` (`_calc_ganancias_acciones`,
> `_calc_ganancias_degiro`), `parsers/fidelity.py`, `parsers/degiro.py`,
> `exchange.py`, `formatting.py`, `templates/_ventas_acciones.html`, `models.py`,
> `cli.py`.

---

## ✅ Lo que está correcto

1. **Doble tipo de cambio por operación** (`calculator.py:482-483`). El **valor de
   adquisición** se convierte al tipo BCE de la **fecha de vesting** y el **valor de
   transmisión** al tipo BCE de la **fecha de venta**. Es lo correcto según el
   criterio de la DGT: cada componente se valora al tipo de cambio de su propia
   fecha de devengo.

2. **Dirección de la conversión** (`exchange.py:127`): el BCE publica USD por 1 EUR
   y se aplica `EUR = USD / tipo`. Correcto y es el tipo oficial admitido por la AEAT.

3. **Redondeo por operación a céntimos** (`exchange.py:127`, cada valor
   `quantize(0.01)`). Adecuado: en el modelo 100 se introduce un importe por
   operación redondeado a céntimos, así que redondear cada valor de
   transmisión/adquisición y luego sumar reproduce lo que el contribuyente teclea.
   No hay error de redondeo acumulado indebido.

4. **Fallback de fin de semana/festivo** al último día hábil anterior
   (`exchange.py:108-118`), con aviso. Razonable y trazable.

5. **Valor de adquisición de RSU = FMV al vesting** convertido al tipo de esa fecha.
   Es la aproximación más correcta posible: el FMV al vesting es lo que tributó como
   rendimiento del trabajo en especie y constituye el valor de adquisición. Bien
   documentado en la nota del informe.

6. **Nunca inventa un tipo**: si falta el tipo BCE, marca la fila en rojo,
   `importe_eur=None` y la casilla como NO CALCULABLE. Cumple la regla de CLAUDE.md.

7. **Comisión de Fidelity**: comprobado contra un PDF de muestra que en el "Custom
   transaction summary" se cumple `gain/loss = proceeds − cost basis` exactamente
   (validación en `fidelity.py:276`). No hay columna de comisión separable; el fee,
   si existe, ya está embebido en "proceeds". Usar `proceeds_usd`/`cost_basis_usd`
   como valores de transmisión/adquisición reproduce la ganancia del propio bróker.
   **No hay ajuste de comisión pendiente en Fidelity.**

---

## ⚠️ Hallazgos a mejorar

Decisión tomada: **solo advertir** (añadir avisos en el informe, sin cambiar la
lógica de cálculo), salvo el punto 4 que es una corrección trivial y segura.

### 1. ✅ No se aplica la regla FIFO (art. 37.2 LIRPF) — PRIORIDAD ALTA — COMPLETADO

Para valores homogéneos (mismo ISIN, mismos derechos — las RSU lo son), la ley
obliga a considerar transmitidas **las acciones adquiridas en primer lugar (FIFO)**.
El código usa el emparejamiento lote-a-lote del bróker:

- Fidelity (`fidelity.py:118-119`): toma `date_acquired` y `cost_basis` de la fila
  tal cual los reporta Fidelity (que normalmente usa identificación específica del
  lote).
- DEGIRO: confía en la ganancia que calcula DEGIRO.

En **ventas totales** de la posición coincide. En **ventas parciales** de una
posición homogénea, el lote (y por tanto el valor de adquisición y el tipo de cambio
de vesting) puede no ser el que exige el FIFO español, alterando la ganancia/pérdida
declarada.

**Implementado en `feature/fidelity_fifo_calc` (commit 11e42a9):**
- Modo FIFO alternativo activable con `--fidelity-fifo [ruta_csv]`.
- El usuario mantiene un CSV ledger (`fecha,ticker,tipo,cantidad,precio_usd`) con el
  historial completo de adquisiciones y ventas. El programa reconstruye el FIFO desde
  el origen y emite un fragmento por cada lote consumido en cada venta del año fiscal.
- El modo por defecto (cálculo por lotes del bróker) se mantiene y ahora incluye un
  aviso explícito en el informe indicando que no se aplica FIFO y cómo activarlo.
- CSV de ejemplo en `samples/1-samples/fidelity_ledger_sample.csv` alineado con el
  PDF de muestra para comparar ambos métodos (lote vs FIFO producen resultados distintos
  cuando hay inventario sin vender que el bróker sí emparejaría).

### 2. Regla de los dos meses / recompra (art. 33.5.f LIRPF) — PRIORIDAD MEDIA

Las pérdidas en valores recomprados dentro de los 2 meses (cotizados) no son
computables en el momento. Con RSU que vestean periódicamente, una pérdida en una
venta puede coincidir con vestings cercanos. El tool computa todas las pérdidas como
deducibles sin comprobar esta regla.

**Acción (solo advertir):** nota/aviso cuando haya operaciones con pérdida.

### 3. Comisión de venta de DEGIRO no se deduce — PRIORIDAD MEDIA

`commission_eur` se parsea (`models.py:156`) pero **nunca se usa**. En
`calculator.py:842` se toma `gain_loss_eur` directamente y el comentario del modelo
indica que la B/P de DEGIRO *no* incluye comisión. Fiscalmente, la comisión de venta
es un gasto inherente a la transmisión deducible; si no se resta, la ganancia queda
sobreestimada. Además el coste se estima como `cost_eur = value_eur − gain_loss_eur`
(ya avisado en el informe), lo que combinado con la comisión ignorada distorsiona el
coste implícito. También se confía en el método de cálculo de DEGIRO, que puede no
coincidir con el FIFO español.

**Acción (solo advertir):** nota indicando que la B/P de DEGIRO puede no incluir
comisión y que el coste mostrado es una estimación; verificar.

### 4. Margen de fechas BCE inconsistente (7 vs 14 días) — PRIORIDAD BAJA (corregir)

`for_dates` descarga desde `min_fecha − 7 días` (`exchange.py:95`) pero `get_rate`
retrocede hasta 14 días (`exchange.py:110`). Si la fecha más antigua necesaria cae en
festivo/fin de semana cuyo último día hábil está a >7 días naturales (p. ej. inicio
de año), la conversión fallaría → NO CALCULABLE. Es seguro (no produce valor
incorrecto), pero podría fallar espuriamente.

**Acción:** igualar el margen de descarga a 14 días (corrección de 1 línea, segura).

### 5. Fluctuación de divisa — INFORMATIVO (no es error)

Usar dos tipos de cambio distintos hace que parte de la "ganancia en EUR" sea pura
variación EUR/USD. Esto es **correcto** bajo la norma española (cada valor a su
fecha). No requiere acción; se anota para evitar confusión.

---

## Resumen de acciones propuestas

| # | Hallazgo | Acción | Estado |
|---|----------|--------|--------|
| 1 | FIFO (art. 37.2) no garantizado en ventas parciales | ✅ Modo FIFO alternativo (`--fidelity-fifo`) + aviso en modo lote | Completado |
| 2 | Regla de los 2 meses (art. 33.5.f) no comprobada | Nota/aviso ante pérdidas | Pendiente |
| 3 | Comisión de venta de DEGIRO parseada pero no usada | Nota/aviso en informe | Pendiente |
| 4 | Margen BCE 7 vs 14 días | Igualar a 14 días | Pendiente |
| 5 | Fluctuación de divisa | Sin acción (informativo) | — |

> Pendiente: implementar los avisos (puntos 2–3) y la corrección del margen (punto 4),
> con sus tests, acotado a la sección de ventas de acciones.
