# Flujo de entrada en ventana completa

Alcance: ChromeWindow/RemoteScreen en RemoteBrowser.tsx y chrome-window-flow.spec.ts.
No cambia worker, Win32, permisos, pairing ni flujo de pestañas.

El sender nativo resolvía la promesa al enviar por WebSocket. El control de flujo
del visor no esperaba al receptor:12movimientos sin ACK enviaban12pedidos.
Se espera ahora t=input con n pendiente; el hover nativo queda limitado a un
lote en vuelo y conserva la última posición acumulada. Botones y teclas conservan
su orden y sus confirmaciones; los IDs crecen también al reconectar el canal.

Timeout10s, error reconocido o saturación128 bloquean sin repetir acciones.
Se limpian promesas/timers y se envía release de entradas propias. El usuario
puede reconectar sin reenviar. Un ACK tardío no habilita la entrada bloqueada.
Release se envía antes de cambiar destino y al ocultar/perder foco; el epoch
limpia estado local nativo al reconectar. El protocolo no confirma release:
no se afirma que la UI haya acreditado su aplicación Win32.

La revisión independiente de E identificó que el primer delta permitía4hover,
cuando el caso exigía1, y que faltaban blur/cambio de destino. Se corrigieron
ambos y se amplió cobertura. E releyó el delta final y no encontró bloqueante
nuevo en este alcance; informe íntegro conservado en
.temp/resultados/E-native-flow-review.md con hashes antes/después.

Explorer: observación real de demoras y código que resolvía send antes del ACK.
Analyser: separar canal nativo y pestañas, envío y ejecución, certeza y replay.
Designer: última posición exacta, IDs estrictos, clic down/up, timeout/rechazo
con ACK tardío, Shift retenido/blur/cambio y reconexión sin replay.
Executor: rojo inicial12envíos; primer delta4todavía rojo; focal final5/5verde.
ESLint y TypeScript/buildrc0. La corrida amplia de desarrollo38pass2fail queda
preservada: límite corregido y perfil dependiente de StrictMode. No se modificó
el oráculo del perfil. Producción final:44/44UI aprobadas en1.2min, incluidos
los cinco casos nuevos y las regresiones existentes de pestañas/ventana/launch.
Log íntegro:.temp/coordinacion/2026-10-21/native-flow-production.log. Vite y
preview de pruebas cerrados; diff-checkrc0.
Detective: cobertura con fixtures explícitos; no demuestra todavía la mejora del
incidente real de Ariel ni constituye PASS global. No se aprobaron baselines.

Riesgos/límites: el servidor nativo no reemplaza el movimiento ya transmitido;
el cliente evita su acumulación. No hay WebRTC ni eliminación de bytes TCP en vuelo.
La precisión/foco de Win32 y el clic físico del checkbox remoto siguen requiriendo
verificación real. Saturación128/hidden/fallo de envío de release revisados por
lectura; no se presentan como casos dinámicos ejecutados.

SHA256 producto final:D44C62DC0539B40395005964AAD806448E12CB0A8D3C03A4C89A32689D25BCC5.
SHA256 pruebas:D4F89DD7BEEBDB710CB70CF280887FDB37AAAD3FD669C2DF43CFCD8D691326D4.
