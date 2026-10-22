# Revisión del encargo T

Fecha: 2026-10-22. Revisor: Codex, sesión pid-36704. Modo: misma sesión, revisión estática del delta propio.
Alcance autorizado: parser nuevo en `lienzo/screen.py`, perfil Kiro en `lienzo/agentes.py` y `tests/test_kiro_confianza.py`.
Se aplicó el skill `code-review` con su checklist. No incluye los cambios de otros frentes presentes en esos archivos.

## Resultado

Sin hallazgos bloqueantes en el delta T. Sin nuevas dependencias.

- El parser exige pregunta exacta, carpeta absoluta visible, dos opciones exactas y un único cursor ❯.
- Se conserva `detail` como carpeta, sin mezclar las advertencias del diálogo.
- El perfil elige únicamente la primera opción «Trust, continue». El cursor puede estar en «Don't trust, exit» sin que esa opción se autorice.
- Se reutilizan `launch._allowed_roots` y `launch._cwd_allowed`: configuración local, existencia, comparación por componentes y destino físico. No se duplica una validación parcial basada en prefijos.
- La política se evalúa al enumerar y antes de contestar por el proveedor existente. `answer_dialog` mantiene su comprobación de pantalla antes de teclear.
- Fuera de raíz queda `auto_aprobar_omitido` con el motivo. Un diálogo incompleto no queda autorizado.
- Sin cambios a los parsers anteriores, salvo insertar la llamada al nuevo parser. Sin cambios en sesiones ni en autoaprobar.

## Verificación

Runner del plugin: 50 pruebas, código 0 (11 focales de T y 39 regresiones de autoaprobar/pantalla).
`ruff check lienzo/screen.py lienzo/agentes.py tests/test_kiro_confianza.py`: código 0.
`ruff format --check lienzo/screen.py lienzo/agentes.py tests/test_kiro_confianza.py`: código 0; 3 archivos formateados.
Evidencia: `.temp/resultados/2026-10-22-T/actual.json`, `salidas/kiro-confianza.log`.

## Límites y pendientes reales

No se abrió Kiro real ni se verificó el tablero en navegador. La pantalla fue la provista por Ariel, aplicada a funciones reales mediante fixtures; la transición de tarjeta y la persistencia se ejercitaron localmente.
No se reinició ni desplegó el server. No se ejecutó la suite global.
Artefactos agénticos propuestos sin aprobar; sin baseline. Compuerta: código 2, «No hay baseline.json». No se informa PASS certificado.
Mutación propuesta para omitir `_cwd_allowed`, sin ejecutar: aprobación reservada a la coordinadora (decisión 3).

## Archivos de código entregados

- `lienzo/screen.py`
- `lienzo/agentes.py`
- `tests/test_kiro_confianza.py`
