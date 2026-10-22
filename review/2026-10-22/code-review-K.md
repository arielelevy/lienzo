# Code review K — 2026-10-22

Alcance: el delta del encargo K (decisiones 24, 23 y 13). Revisó el skill `code-review` (bifurcado,
esfuerzo alto) sobre: `lienzo/emergencia.py`, `health.py`, `mirror.py`, `red.py`, `pairing.py`,
`skills/lienzo/coordinar.py` (reparto), `web/src/components/PcStrip.tsx`, `web/src/types.ts`,
`web/src/styles.css` (.pcemerg), sus tests, y `.temp/resultados/2026-10-22-K/server.diff`,
`tests-con-server.diff` y `test_beacon_nat.py`.

Diez hallazgos, ninguno verificado por el revisor. Cada uno se revisó contra el código; los
corregidos llevan un test que falló antes del arreglo (`.temp/resultados/2026-10-22-K/rojo-review-*.txt`).

| # | Hallazgo | Veredicto | Qué se hizo |
|---|----------|-----------|-------------|
| 1 | `sincronizar_ronda`: `git log` cita y escapa las rutas con acentos, que parecen ajenas | Confirmado (rojo) | `-c core.quotePath=false` y `-z` |
| 2 | Con detección de renombres, `git mv` desde lo ajeno sólo lista el destino | Confirmado (rojo) | `--no-renames` |
| 3 | En server.diff, si la mejor IP no abre se saltea el par en vez de probar la siguiente | Confirmado (rojo) | Bucle sobre candidatas vivas |
| 4 | En server.diff, sin conexión en uso no se sondea y la puerta del NAT queda en peers.json | Confirmado (rojo) | Se sondea siempre; verificado en uso al reiniciar las dos instancias |
| 5 | Causa raíz: se toma la IP de origen del beacon en vez de las que anuncia firmadas | Válido, de diseño | **Pendiente**: cambia el formato del beacon firmado y la federación; fuera de este encargo |
| 6 | Sondeo bloqueante de 2 s en cada pasada mientras el NAT siga anunciando | Confirmado (rojo) | `red.sondear` recuerda los fallidos 60 s |
| 7 | `emergencia.propia()` dentro del lock del espejo y sin captura | Confirmado (rojo) | Se calcula fuera del lock con `try`; si falla, `emergencia: null` y una línea de log |
| 8 | ⛑ aparecía en un par recién conectado que todavía no contestó | Confirmado (rojo) | Sólo si ya se lo vio alguna vez (`last_seen`) |
| 9 | Enlace `/tailchrome` inútil desde otra máquina y puerto 7321 fijo en el texto | Confirmado | El texto ya no fija el puerto; el enlace sólo se muestra con el tablero en localhost; si no, texto con «(desde el tablero de esta PC)». Sin test de UI para el caso remoto |
| 10 | `/proc/stat` con 4 contadores daba IndexError | Confirmado (rojo) | Guarda `< 6` campos |

Verificación después de los arreglos: pytest de K en verde, `pcs.spec.ts` 22/22 (Vite en 7355),
`tsc` y `eslint` limpios, `ruff` limpio en las rutas de K, runner del plugin 2/2 OK (sin baseline), y
el par Linux de WSL ↔ Windows aislada vivo en los dos sentidos con el `server.diff` final.

Pendiente real: el hallazgo 5.
