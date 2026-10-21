# Selección de descargas

Alcance: Downloads.tsx, downloads.css y downloads.spec.ts. No backend ni permisos.

La UI real ofrecía sólo una casilla de aproximadamente13×13px; el nombre del
archivo no activaba la selección. Se añade asociación label/htmlFor con useId
por instancia y el id opaco del archivo. La casilla mide24×24px y el nombre
ofrece un blanco adicional. La selección conserva el mismo Set y onChange.

No se añadió transferencia automática. Nombre/casilla respetan disabled durante
carga o confirmación; la confirmación de sobrescritura no cambia. No se expone
una ruta como id ni se introduce HTML sin escapar. El teclado nativo se conserva.

Explorer: UI real de ambas direcciones, entrada remota con rechazo de foco observado.
Analyser: distinguir blanco pequeño de fallo remoto todavía no atribuido.
Designer: seleccionar por nombre, desmarcar con espacio y cero POST; reutilizar
los casos existentes de sobrescritura y cierre con respuesta tardía.
Executor: rojo sobre0.6.1 servido:1failed por casilla sin marcar después de clic
en nombre. Verde con fuentes actuales en Vite7393:4passed8.1s. ESLint focalrc0.
TypeScript y buildrc0,391 módulos; aviso existente por chunk superior a500kB.
Vite de pruebas cerrado y diff-checkrc0. Sin pruebas reales de transferencia.
Detective: rojo/verde acredita selección por nombre; no atribuye el fallo remoto
de Ariel ni acredita que desaparezca el bloqueo de foco. No es PASS global.

No hay hallazgo bloqueante en este delta. Pendiente: medir clic/teclado en la
otra PC con esta versión desplegada y distinguir interacción física/visor.
No se aceptaron baselines ni se cerraron casillas.

Logs ignorados en .temp/coordinacion/2026-10-21/downloads-label-{red,green}.log.
