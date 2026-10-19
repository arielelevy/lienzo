# Proceso automático de Tailchrome

Revisión del delta de proceso, protocolo nativo, WebSocket y página de red. Misma
sesión, sin agentes adicionales. No se modifica el helper instalado ni el perfil de Chrome.

## Recorrido de pruebas agénticas

- Explorer: página real con dos servidores aislados y Chromium. Se observaron
  arranque manual, activación del proceso, inventario y apagado.
- Analyser: se contrastó el protocolo con el código oficial del helper de Tailchrome.
  Requisitos: perfil separado, sufijo `-lienzo`, inventario entero, reconexión y
  autenticación de todos los pares conocidos. Falta ejecutar el helper instalado real.
- Designer: se amplió el E2E vigente para cerrar Chrome por completo, reiniciar el
  servidor con su configuración persistida y detener el servicio. Se agregaron casos
  de framing, privacidad de credenciales, duplicados y nodos offline/no emparejados.
- Executor: **202 pruebas aprobadas** de proceso, transporte y federación; Ruff sin
  hallazgos. E2E con código 0: tráfico firmado en ambos sentidos sin navegador y
  autostart después de reiniciar Lienzo. Helper y tailnet sustituidos por fixtures.
- Detective: el E2E detectó una ruta POST agregada por error en GET y una carrera con
  el primer refresco del formulario. Se corrigieron y se volvió a ejecutar el recorrido.

## Revisión de código y limpieza

Se comparte el multiplexor cifrado y el endpoint de puente entre navegador y proceso.
No hay una implementación nueva de firmas ni de cifrado. El proceso sólo usa el helper
registrado de Chrome o Edge y recibe su proxy autenticado por pipes. Las credenciales
del proxy no salen en la API, no se copian del navegador y se descartan al cerrar.

Se revisaron Origin/CSRF de la activación, validación del manifiesto nativo, tamaños
máximos del protocolo, cierre por EOF y terminación del proceso propio. Los puentes
se reservan por pc_id para no duplicarlos. La respuesta anónima de descubrimiento
no permite ejecutar acciones: el canal exige la prueba cifrada del par.

La lista incluye todos los nodos publicados, aunque estén offline o no tengan Lienzo.
Una respuesta truncada del helper se informa como incompleta. Sólo se prueban las
IPv4 100.x y los puertos de Lienzo, con hasta ocho sondas concurrentes. No hay
cambios de firewall, DNS, exit nodes ni rutas de subred.

No se detectaron hallazgos críticos o altos abiertos en el delta. No se ejecutó
mutación ni se aceptaron casos, requisitos o baselines nuevos. La verificación
agéntica no tiene un PASS de aceptación: conserva el estado ESCALAR del perfil
de propuestas. La conexión real requiere una autorización inicial del nodo propio
en Tailscale y sigue pendiente en la PC de destino.

Evidencia local ignorada: `pruebas-agenticas/resultados/tailchrome/proceso.xml`,
`proceso.log`, `automatico.png` y los logs de los servidores fixture. El comando
reproducible es `node web/tests-ui/tailchrome-e2e.mjs`.
