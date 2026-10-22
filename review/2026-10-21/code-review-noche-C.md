# Code review — encargo C, ronda nocturna 2026-10-21

Skill `code-review` (medium) sobre: `lienzo/browser_window.py`, `tests/test_browser_window.py`,
`web/src/components/RemoteBrowser.tsx`, `web/src/components/Card.tsx`, `web/src/hooks/usePantallaQuieta.ts`,
`web/tests-ui/chrome.spec.ts`, `web/tests-ui/tarjeta-quieta.spec.ts` y el parche propuesto
`.temp/resultados/noche-C/mirror-latencia-en-vivo.patch`. 9 hallazgos sin verificar; resultado de cada uno:

| # | Hallazgo | Resultado |
|---|---|---|
| 1 | `clipboard_changed` atribuía a Chrome cualquier cambio si al mirar estaba al frente una ventana del mismo proceso, aunque la copia hubiera pasado con el visor en pausa (riesgo: traer una contraseña) | **Corregido.** Exige esa misma ventana al frente (`GetForegroundWindow() == hwnd`) y la mirada anterior a ≤ 1 s (`CLIPBOARD_FRESH_S`); un hueco sin mirar actualiza la marca sin anunciar. Prueba ampliada (otra ventana, 30 s sin mirar). |
| 2 | `paste` escribe el portapapeles remoto antes del Ctrl+V; si el frente cambia en el medio, lo pegado queda allá y no se pega | **Queda.** El bucle de `input` comprueba el frente justo antes del evento; la ventana es de milisegundos y el error se informa al visor. Restaurar el portapapeles anterior exigiría leerlo sin gesto. |
| 3 | «Copiar acá» escribe el portapapeles local al llegar la respuesta, no en el instante del clic | **Queda, documentado.** Mismo límite que el Ctrl+C que ya existía; Chrome lo acepta (prueba UI verde), un navegador más estricto da el aviso «No se pudo copiar en esta PC». Comentario corregido. |
| 4 | Cada pestaña lee `/screen` por tarjeta corriendo cada 60 s (subproceso screen.py) | **Queda, propuesto.** La raíz es server: `screen_once` (sessions.py, de F) ya lee la pantalla cada 5 s y podría guardar `pantalla_cambio_at`. Anotado para la coordinadora. Se acotó: sólo pestaña visible, sólo `corriendo` con consola, no con la PC caída. |
| 5 | Al volver a mirar (aviso reactivado, PC que vuelve) se reusaba la huella vieja y el tiempo sin mirar contaba como quieto | **Corregido.** La limpieza del efecto borra la huella; la primera lectura vuelve a contar desde cero. |
| 6 | Parche del espejo: con la PC caída, `latencia_ms` caía a la mediana vieja de reenvíos | **Corregido en el parche.** `latencia_ms` es `None` si la PC no está viva; la prueba ahora tiene reenvíos viejos. |
| 7 | El comentario decía «mismo criterio que coordinar.estancada()» y no es igual | **Corregido.** Dice en qué difiere (no cuenta el reloj del spinner). |
| 8 | Los minutos no se propagaban a otra pestaña | **Corregido.** Escucha el evento `storage`. |
| 9 | Secuencia Ctrl+C duplicada a mano junto a `CTRL_V` | **Corregido.** `ctrl(key)` arma `CTRL_C` y `CTRL_V`. |

Verificación después de corregir: `pytest tests/test_browser_window.py` 54 passed; parche del espejo en copia
de HEAD, `tests/test_mirror.py` 26 passed; ruff limpio en mis rutas; `tsc` y ESLint limpios; Playwright
focal 82 passed contra un server de prueba en 7343 (copia de HEAD + estos archivos).
