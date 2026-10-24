# Revisión de código — encargo F

Fecha: 2026-10-24. Alcance: cambios F, sin revisar ni modificar el trabajo E.
Modo: revisión estática en la misma sesión, con el skill code-review.

## Archivos revisados

- `lienzo/preguntas.py`: detección, lector de CODA, enrutamiento, deduplicación y respuestas.
- `lienzo/sessions.py`: barrido de consultas y revalidación de diálogos.
- `lienzo/server.py`: registro de `/responder` y conexión del enrutador federado.
- `skills/lienzo/coordinar.py`: cliente `responder`.
- `web/src/components/CardNeeds.tsx` y `web/src/types.ts`: consulta y elección visibles.
- `tests/test_preguntas_F.py` y `web/tests-ui/preguntas-coordinadora-F.spec.ts`.

## Hallazgos corregidos

1. **Guarda incorrecta para hooks.** `send_blocked` rechaza precisamente un hook pendiente.
   La respuesta de hook valida sesión detenida y origen externo, y usa `answer_pending`.
   La guarda de teclado sólo corre para terminales. Prueba: opción y doble respuesta de hook.
2. **Lectura incorrecta de CODA.** El parser genérico mezclaba el panel lateral con las opciones
   y perdía AZUL y Type something. Medido en pantalla real. El lector propio separa el panel,
   conserva opciones y pregunta partidas, y elimina el bloque █ del borde.
3. **Número sin confirmación.** En CODA 1.5.0, `2` mueve el cursor y deja abierta la pregunta.
   La respuesta usa flechas y Enter, con relectura antes de confirmar.
4. **Compatibilidad con permisos.** El lector nuevo se usa sólo si el diálogo lleva
   `lector: pregunta_coda`. Los diálogos previos conservan su lector.
5. **Pregunta cambiada con las mismas opciones.** Se compara también la pregunta antes de teclear.
6. **Doble respuesta.** Se serializan respuestas y se conserva la identidad ya contestada.
7. **Envío incierto.** El intento se persiste antes del envío. No se reintenta un fallo incierto.
   Un `409` con `code: dialog_open` es un rechazo previo a teclear: espera 15 segundos.
   Se limpió ese plazo antes del intento siguiente, para que un 500 posterior no herede el reintento.
   Prueba roja observada: se enviaban 3 mensajes en vez de 2. Corregido.
8. **Texto de Ariel en el editor.** Se exige Type something seleccionado y editor vacío.
   Si ya hay texto, devuelve 409 sin modificarlo. Se rechazan controles y texto de más de 2000 caracteres.
9. **Identidad del repositorio.** La selección exige `repo_key`, coordinadora viva, distinta y no detenida.
10. **Cliente ambiguo.** `c.responder` conserva ambos argumentos si se pasan ambos, para que el servidor
    responda 400 en vez de descartar texto silenciosamente.

## Validación

- Ruff sobre los cinco archivos Python F, incluidos los enganches y el cliente: sin hallazgos.
- Regresión final F, CODA, auto-aprobar, hooks, Kiro y diálogos: **106 passed**.
- Tarjeta F en Chromium con fixtures y escrituras bloqueadas: **1 passed**.
- Medición real: recepción de la consulta por la coordinadora descartable, opción VERDE,
  texto TEXTO-F-LIBRE y respuesta tardía 409. Ambas codas cerradas con 200.
- Suite aprobada de siete casos: **6/7**, compuerta **FAIL** por timeout de backend-pytest.
  Lint, build, unitarias, Playwright aprobado y los dos casos de memoria pasaron.
- Segunda corrida backend completa: **3693 passed, 11 skipped**, salida 0, en 881,57 segundos.
  Se inició antes del último ajuste de hook vencido; ese ajuste y su prueba están cubiertos
  por la regresión focal final de 106 pruebas. No se reemplazó el resultado histórico del runner.
- No se corrió mutación sobre el árbol compartido ni se aprobaron baselines.

## Límites de la revisión

No se cambiaron dependencias. No se hizo auditoría de dependencias ajena al alcance F.
La federación de `/responder` se probó con un doble del peer; no con otra PC real.
Los hooks Claude y preguntas múltiples se probaron con fixtures, sin lanzar un Claude real.
Multiselección conserva el contrato `answers` del tablero, sin medición específica.
El teclado de texto libre se habilita para el editor CODA medido.
La compuerta global no está aprobada. La segunda corrida backend completa tiene su log en
`.temp/coordinacion/2026-10-24/F-pruebas/backend-final-F.log`.

No quedan hallazgos funcionales conocidos de F sin corregir en esta revisión.
El timeout de la corrida inicial sigue sin causa determinada. La segunda corrida terminó;
las esperas registradas en infografías y xfer no terminaron en fallas. No se atribuye a F
un defecto global sin evidencia.
