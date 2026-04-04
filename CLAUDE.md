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
