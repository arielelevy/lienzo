# Revisión: Chrome remoto en Lienzo (verificación de navegador pendiente)

Alcance: los cambios de esta sesión en `lienzo/browser_api.py`, `browser_remote.py`,
`browser_host.mjs`, `server.py`, `mirror.py`, `protocol.py`, `secretos.py`, la vista
`RemoteBrowser.tsx`, su CSS, integración en App/Header/Vite, mensaje de Git en PcStrip y sus pruebas.
No es una auditoría completa del repositorio. Revisión estática secuencial en la misma sesión.

## Hallazgos corregidos

- Las entradas de teclado y capturas no podían viajar en claro por el transporte HMAC de peers.
  Se reutiliza el cifrado autenticado existente con clave derivada exclusiva y un identificador
  de pedido que impide aceptar una respuesta de otra operación. Se comprueba con pruebas aisladas.
- El generador de bloques de `secretos.py` sumaba todos los bloques en cada vuelta. Se reemplazó
  por un rango de igual cantidad de bloques para mantener formato y costo lineal con capturas.
- La PC elegida queda fijada; una desaparición del peer no cambia automáticamente al Chrome local.
- Los resultados de una vista o pestaña anterior se descartan; los eventos pendientes se vacían
  al desmontar la página. Las acciones incluyen destino y pestaña explícitos.
- No se reintentan automáticamente navegaciones, creación de pestañas ni entradas después de
  un timeout. La reconexión consulta estado. Hay límites de entradas, texto, tamaño y pestañas.
- Se agregó captura del puntero para soltar el mouse aunque el arrastre salga del área visible.
- La UI interpretaba todo `git: error` como red o Git colgado. Ahora conserva la incertidumbre;
  el caso observado era un `Repository not found` usando la cuenta equivocada.

## Controles revisados

La ruta de acciones requiere autenticación/CSRF y acceso local sin túnel. El listener de peers
valida firma antes del descifrado. CDP no se publica ni acepta métodos del cliente. No hay shell
al iniciar Node o Chrome, ni argumentos ejecutables controlados por la URL. Chrome usa perfil
propio, sandbox normal y loopback. El cierre afecta exclusivamente al proceso que creó el worker.
Las capturas y teclas no se escriben al log de peer. No se copiaron credenciales del Chrome personal.

## Evidencia y pendientes reales

- Primera corrida del runner: 1005 pruebas backend pasaron; una falló porque el contrato exacto
  de capacidades no incluía `browser.remote`. Se actualizó ese contrato al agregar la capacidad.
- Verificación posterior de salud, ruteo y cifrado: **61 passed**. Primer conjunto de ruteo/cifrado:
  **28 passed**. Build y unitarias del frontend pasaron.
- Se corrigió el hallazgo de lint sobre selección inicial de PC. La ejecución final queda registrada
  en `pruebas-agenticas/resultados/chrome` (ignorado en Git).
- `npm audit --omit=dev`: cero vulnerabilidades. `npm ci` informó dos de severidad alta en
  dependencias de desarrollo ya existentes; no se hizo un cambio de versiones fuera de alcance.
- No hay validación visual ni prueba real de Chrome en esta PC todavía: menos de 2 GB libres y
  CUA devolvió timeout. No se afirma funcionamiento de punta a punta basándose en el build.
- Los requisitos, casos de navegador y mutación son propuestas; no se aprobaron ni fijaron baselines.
- Audio, descargas, selector de archivos, extensiones e IME no están certificados para esta vista.
  La transmisión usa capturas periódicas; no tiene la fluidez de video de un escritorio remoto.

No se identificaron otros bloqueos de seguridad en la revisión estática dentro de este alcance.
Queda pendiente ejecutar la prueba con Chrome real y el recorrido visual en una PC con memoria.
