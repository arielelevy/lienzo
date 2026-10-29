# Revisión de cambios pendientes

Alcance: los 10 archivos modificados y 3 archivos nuevos que quedaron fuera de `bc60cf2`. Revisión estática y pruebas por la sesión principal, sin agentes adicionales.

## Qué cambia

- Cuotas federadas: `/cuotas` consulta PCs emparejadas cuando puede completar una lectura local ausente; `/peer/cuotas` devuelve sólo datos locales bajo la firma existente, evitando recursión. La UI muestra la PC de origen. La sugerencia para lanzar conserva la decisión local.
- Arranque: busca Python por su ruta instalada y usa `git pull --ff-only --no-rebase`, para admitir `pull.rebase=true` con cambios locales que no entran en conflicto.

## Hallazgos

1. **Media — ruta de Python sin comillas.** `lienzo-server.cmd:7` y `:14` expanden `%PY%` sin proteger espacios. En un perfil cuya ruta incluya espacios, el arranque falla. Reproducción del mismo patrón con un ejecutable instalado: `cmd /d /c '%LIENZO_REVIEW_EXE% --version'`, con la variable apuntando a `C:\Program Files\PowerShell\7\pwsh.exe`, devuelve código 1 y `'C:\Program' is not recognized as an internal or external command`. Separar ejecutable y argumentos y entrecomillar el ejecutable.
2. **Media — se consulta a todas las PCs aun con todas las lecturas locales válidas.** `lienzo/cuotas_federadas.py:7`–`:10` lanza todas las consultas antes de comprobar si faltan datos. Medido con las cuatro cuentas locales `ok: true`: una PC viva produce una llamada remota. Se espera hasta 20 s por una consulta que no puede aportar datos. Evitar la consulta cuando todas las lecturas ya están disponibles.
3. **Baja — formato Python.** Ruff detecta `I001` en `lienzo/cuotas_federadas.py:3`; falta separación entre el import y la función.

## Evidencia focal

- `.temp/review-startup-dirty.py`: repositorios Git temporales reales; `pull.rebase=true` y archivo modificado. El comando anterior falla; el nuevo termina con 0 y conserva el contenido local.
- `.temp/review-peer-cuotas.py`: listener HTTP real aislado. Sin firma responde 401 y no lee cuotas; con firma válida responde 200; `refrescar=1` llega como `True` al lector local. Lectores simulados, sin credenciales reales ni inferencia.
- `node web/scripts/unit.mjs` desde `web`: 8 de 8 archivos pasan.
- La PC emparejada `ar-it33940` estaba desconectada al consultar `/peers`. No se certifica un recorrido entre máquinas reales.

## Alcance de la suite global

Se ejecuta el runner completo de `pruebas-agenticas/pruebas-agenticas.json`, más todos los 59 archivos Playwright (364 casos descubiertos), porque la configuración global sólo enumera parte de las pruebas de interfaz y cuatro archivos unitarios.

La validación global detectó dos mutaciones cuyo texto ya no existe en `lienzo/conocimiento.py`: `memoria-roto-no-rechaza` y `memoria-respaldo-sin-exigir`. No se cambian propuestas aprobadas ni baselines para ocultarlo. El árbol de trabajo contiene cambios locales, por lo que no se ejecuta mutación en el lugar.

Los resultados completos y el recorrido de cinco roles se conservan bajo `pruebas-agenticas/resultados/`. Este informe se amplía al terminar la corrida.

## Resultados de la corrida global

Corrida `2026-10-29T01-50-33.480Z-3916`: 6 de 7 casos del runner terminaron con código 0. `backend-pytest` terminó con código -1, `timeout`, a los 900572 ms. El log completo alcanza el 98 %; no contiene un resumen final de pytest, por lo que no se convierte ese avance en cantidad de pruebas aprobadas.

- Lint frontend: código 0.
- Build frontend: código 0; conserva el aviso de bundle mayor de 500 kB.
- Unitarios configurados: código 0; además se ejecutaron los 8 archivos disponibles por el script del proyecto, todos en ok.
- Playwright configurado: 143 casos pasan. Corrida ampliada a los 59 archivos: 353 pasan y 11 se saltean por sus condiciones de instancia especial, capturas o IA real. No se suman ambas corridas como casos distintos.
- Memoria focal: 191 pasan en 35.50 s.
- Memoria E2E: código 0 y `veredicto True`, sobre servidor aislado.
- Ruff global: código 1, sólo `I001` en el módulo nuevo de cuotas federadas.
- Compuerta: código 1, `No hay baseline.json`. No se fija un baseline con el caso global de backend fallido.
- Mutación: no ejecutada; configuración inválida y árbol con cambios locales.

La investigación adicional de los 40 archivos finales, desde `test_revision_F.py`, terminó con **745 passed, 9 skipped in 357.04s**. Fue una ejecución separada, no una aprobación de la corrida global. Los nueve saltos corresponden a transcripciones de Codex no disponibles y pruebas de symlink de Windows; las pruebas WSL de este tramo sí corrieron.

Los cinco casos más lentos de transferencia tardaron 59.99, 45.78, 43.70, 35.50 y 27.54 s. La traza a los 60 s ubicó el hilo principal en `tests/test_xfer.py:172`, leyendo archivos dentro de `_igual`; ese caso luego pasó. Esto acredita demora en la validación de archivos durante la observación, sin probar una causa externa específica ni convertir el timeout global en éxito.

El árbol conserva los cambios iniciales; esta revisión sólo agregó su informe y artefactos ignorados. No se modificaron fuentes ni baselines. Los servidores de prueba y navegadores iniciados finalizaron.
