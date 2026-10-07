# Revisión: Chrome remoto en Lienzo (perfil habitual pendiente de autorización)

Alcance: los cambios de esta sesión en `lienzo/browser_api.py`, `browser_remote.py`,
`browser_host.mjs`, `browser_profiles.mjs`, `server.py`, `mirror.py`, `protocol.py`, `secretos.py`, la vista
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
propio, sandbox normal y loopback; alternativamente conecta al Chrome habitual autorizado por
su propio aviso. Se lee sólo nombre e ID de los perfiles. El endpoint se toma de una ruta fija
del usuario y se valida puerto/ruta; nunca admite un host enviado por el cliente. El cierre mata
exclusivamente al Chrome creado por el worker; en el habitual sólo desconecta el socket. Las páginas
usan sesiones multiplexadas sobre una conexión autorizada. Cancelar cierra también la solicitud
pendiente y una respuesta tardía no puede reconectar después de cancelar.
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
- En 570f4ac: runner backend **1006 passed**, lint/build/unitarios sin fallas, dos pruebas de UI
  con fixtures pasaron. El frente S ejecutó Chrome real aislado en ar-it33940: nueve controles
  pasaron y revisó la captura (teclado, mouse, navegación, historia, pestañas y cierre).
- Cambio de perfiles: dos pruebas Node de catálogo/endpoint y doce de backend pasaron; lint y
  build pasaron por el runner. Primer intento dentro del sandbox falló por permisos de entorno.
- Falta probar el permiso de conexión en el Chrome habitual de Globant. No se afirma que se
  haya conectado a ese perfil. Abrir un perfil y compartirlo son acciones distintas: Chrome
  elige el perfil predeterminado cuando hay varios activos. La UI informa esa limitación.
- Los requisitos, casos de navegador y mutación son propuestas; no se aprobaron ni fijaron baselines.
- Audio, descargas, selector de archivos, extensiones e IME no están certificados para esta vista.
  La transmisión usa capturas periódicas; no tiene la fluidez de video de un escritorio remoto.

No se identificaron otros bloqueos de seguridad en la revisión estática dentro de este alcance.
Queda pendiente verificar en vivo el Chrome habitual con permiso del usuario. El informe se
conserva en docs por ese pendiente, según el pedido de Ariel.

## Ventana real de Chrome — e137db1

Revisión estática de los diez archivos del cambio: destino explícito, transporte cifrado,
validación del ejecutable chrome.exe y de la ventana activa antes de enviar entrada,
límites de coordenadas, teclas y texto. La vista completa es ahora la opción predeterminada;
no requiere activar remote debugging. El modo por pestañas conserva sus requisitos anteriores.

Evidencia previa al pedido de detener pruebas: 61 casos Python pasaron y se observó una
captura local de la ventana completa de Chrome (1295 × 767). No se verificó la interacción
nativa en ar-it33940 ni el funcionamiento sin monitor. Windows debe mantener la sesión
abierta y desbloqueada. La liberación al salir cubre teclas; queda pendiente cubrir también
un botón del mouse mantenido al desconectarse. No se sincroniza el portapapeles remoto.

Recorrido agéntico secuencial: Explorer identificó las ventanas existentes; Analyser separó
el permiso CDP de la captura nativa; Designer agregó el caso de ventana completa; Executor
registró la evidencia anterior y dejó las restantes pruebas sin ejecutar por el pedido
explícito «sin probar»; Detective conserva esos pendientes. No se aceptaron baselines
ni se declara PASS de aceptación. Build e instalación se ejecutan como parte del despliegue.
