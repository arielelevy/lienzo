# Aprobación del baseline de 0.4.0

Ariel aprobó explícitamente el baseline el 2026-10-18, después de revisar el cierre de `79702b1`, y pidió pushearlo.

Se versiona `resultados/release-final/baseline.json`: los cinco casos esperan código 0.

- Frontend: corrida `2026-10-18T15-20-13.234Z-34608`, cuatro casos con código 0; 201 pruebas Chromium aprobadas y seis generadores de capturas omitidos.
- Backend: corrida `2026-10-18T15-24-06.158Z-38092`, caso `backend-pytest` de la configuración principal, código 0; 2416 pruebas aprobadas y tres omitidas. Su comando es el mismo que `backend-global` del perfil de release. Se usa para aprobar el resultado esperado; no se copia ni se renombra como una ejecución de ese perfil.
- El baseline local del frente hijo, `runtime-contratos`, también queda fijado en su carpeta de coordinación. Sus resultados y configuración temporales no se publican.

Los resultados anteriores conservan su estado y sus logs originales. La aprobación del baseline no acepta las propuestas de requisitos, casos o mutaciones y no acredita por sí sola un PASS de certificación.
