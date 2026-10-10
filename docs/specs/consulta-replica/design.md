# Diseño: réplica y tamaño de respuestas en la consulta

## Resumen

Dos piezas: (1) el modo réplica — un endpoint `POST /consultas/<id>/replica` que le reenvía a un
investigador una respuesta puntual de otro, por el envío de siempre, sin tocar pendientes ni avance;
(2) el tamaño de cada respuesta en la vista, calculado en el frontend del texto que ya tiene.

## Componentes

### lienzo/consulta.py

Una función nueva, al lado de `cancelar`:

```python
def replica(cid: str, d: dict) -> tuple[int, dict]:
    """POST /consultas/<id>/replica. d = {"para": sid, "de": sid, "vuelta": n}."""
```

- Valida con el lock tomado: la consulta existe (404), está en `ABIERTAS` (409), `para` es
  participante (`_participantes`), `de` tiene respuesta en `c["respuestas"][str(vuelta)]`, `vuelta`
  es entero positivo. Rechaza con `_rechazo` y el motivo, sin mandar nada.
- Arma el pedido con una marca propia: `[consulta <cid> · réplica]` (misma forma que `_marca`, etapa
  `réplica`), el texto de la respuesta con su autor y vuelta, y `REGLAS` al pie.
- Manda con un helper nuevo `_enviar_uno(cid, sid, texto, de)`, extraído de `_mandar_vuelta`: hace el
  `enviar` con try/except y devuelve `(code, out)`, sin anotar pendiente ni llamar a `_sacar`.
  `_mandar_vuelta` lo usa para cada tarjeta (conserva su paralelismo, sus pendientes y su `_sacar`),
  y `replica` lo llama directo: sin pendiente (1.3) y, si el envío falla, sin sacar a nadie (1.5) —
  devuelve el error como respuesta HTTP.
- Anota en `c["replicas"]` (lista nueva en el dict de la consulta, vacía al abrir): `{"para", "de",
  "vuelta", "ts"}`, guarda y responde 200 con la anotación.

### lienzo/server.py

Una ruta, junto a la de cancelar:

```python
if len(parts) == 3 and parts[0] == "consultas" and parts[2] == "replica":
    code, res = consulta.replica(parts[1], d)
```

### skills/lienzo/coordinar.py

Al lado de `consulta_estado`:

```python
def consulta_replica(cid, para, de, vuelta):
    """Le reenvía a `para` la respuesta de `de` en esa vuelta. Levanta RuntimeError si falla."""
```

`pedir("POST", f"/consultas/{cid}/replica", {...})`; 200 → None, si no `RuntimeError`.

### skills/lienzo/SKILL.md

Una línea en «Consulta entre investigadores», después del ejemplo: `c.consulta_replica(cid, para,
de, vuelta)` reenvía una respuesta que el otro no recibió.

### web/src (vista)

- `types.ts`: `ConsultaEntera` gana `replicas: {para: string; de: string; vuelta: number; ts: string}[]`.
- `components/Consulta.tsx`: junto al `<h3>vuelta {n}</h3>` de cada respuesta, un `<span>` con el
  tamaño formateado (`formatTamano(texto.length)`: `3,2 k` para miles, el número pelado si es corto);
  lo mismo para la síntesis. Función local, sin dependencias nuevas.

## Modelo de datos

`c["replicas"]`: lista de `{"para": sid, "de": sid, "vuelta": int, "ts": iso}`. Se inicializa vacía
en `abrir()` y `cargar()` la tolera (las consultas viejas de disco no la tienen: `replica` usa
`c.setdefault("replicas", [])`).

## Manejo de errores

| Caso | Respuesta |
|---|---|
| consulta inexistente | 404 |
| consulta no abierta | 409 |
| `para` no participante / `de` sin respuesta en la vuelta / `vuelta` inválido | 400 |
| envío fallido | 200 con `{"ok": False, "error": ...}` — no saca a nadie (1.5) |

Una contestación a una réplica no matchea ningún pendiente (la marca `· réplica` no es la del
pendiente), así que `_tomar` la ignora (1.4): no hace falta código nuevo.

## Estrategia de prueba

| Prueba | Cubre |
|---|---|
| `tests/test_consulta_replica.py`: valida 404/409/400, la marca del pedido, que no queda pendiente ni se saca a nadie al fallar el envío, y la anotación en `replicas` | Requisito 1 |
| `tests/test_consulta_vista.py` (o el test de UI que ya existe): el tamaño se muestra por respuesta y para la síntesis | Requisito 2 |
| batería existente sin cambios | Requisito 3 |
