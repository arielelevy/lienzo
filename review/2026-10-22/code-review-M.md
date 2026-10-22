# Code review M — 2026-10-22 (vista por pestañas sin franjas)

Skill `code-review` (medium) sobre el delta de M: `lienzo/browser_host.mjs`, `lienzo/browser_stream.py`,
`web/src/components/RemoteBrowser.tsx`, `tests/browser_host.test.mjs`, `tests/fixtures/browser_host_socket.mjs`,
`tests/test_browser_tabs_stream.py`, `web/tests-ui/chrome.spec.ts`, `pruebas-agenticas/chrome_fit_real.mjs`.

| # | Hallazgo | Resolución |
|---|---|---|
| 1 | `unfit` borraba `cdp.fit` antes del clear: si el clear fallaba, la pestaña quedaba emulada sin registro | Corregido: `fit` se borra recién con el clear confirmado. Prueba «un unfit que vence…» (rojo con el orden viejo) |
| 2 | Un override vencido (504) que Chrome aplica tarde quedaba sin registro | Corregido: `fit = 'incierto'` antes de mandarlo. Prueba «un fit que vence…» (rojo antes) |
| 3 | Cambio de pestaña: `unfit` de la anterior antes del chequeo de propiedad de la nueva | Corregido: la anterior se devuelve sólo al confirmar el cambio (antes de soltar su propiedad) o, si la nueva es ajena, se devuelve sin soltarla. El chequeo temprano ya rechaza el caso común sin tocar nada (prueba «conserva la vista ajustada») |
| 4 | `close()` hace un `unfit` más dentro de `selection_lock` | Aceptado: tiene que ir antes de liberar la propiedad o pisaría el ajuste del visor siguiente. Sin fit el host contesta sin CDP |
| 5 | El ajuste cambia la página en la ventana real de la otra PC aunque el visor sea más grande | Es el pedido de Ariel. Medido con Chrome real: 700×1000 en una ventana de 723 px de alto, 0 px de franja, 1 resize por tamaño, vuelve al soltar |
| 6 | Comentarios «existing nunca emula» desactualizados | Corregidos |
| 7 | Margen de 50 ms en la prueba de gesto (pasos de 200 ms, debounce 250) | Debounce a 300 ms (margen 100 ms); con 150 ms la prueba da 5 size |
| 8 | Visor fuera de 320–1920 × 240–1080 vuelve a tener franjas | Límite preexistente de host, stream y UI; queda informado, sin cambiar |
