# Estabilidad: conexión firmada y pausa de transferencias

Revisión focal de `lienzo/xfer.py` y `tests/test_xfer.py`, secuencial por la
coordinadora. No constituye auditoría completa ni revisión independiente.

## Firma después de conectar

HTTPConnection abre TCP de forma diferida en request. Antes, signed_headers
se evaluaba primero: resolver/conectar consumía la ventana de autenticación.
Ahora se conecta explícitamente cuando no hay socket, se configura su timeout
y después se firma. La conexión existente se reutiliza; tras _soltar se conecta
de nuevo. Los errores de conexión siguen el mismo manejo con pausa y backoff.

Regresión con PeerHandler real aislado: roja por firmar antes de conectar.
El primer intento corregido detectó un error del test (payload sin bs, 400);
corregido el payload, pasó y comprobó tres firmas sobre dos conexiones TCP.
Se verificó el orden; no se midió un handshake remoto lento.

No se modificaron claves, ventana de 30 s, nonce, firma del cuerpo completo,
límites de cuerpos ni confinamiento. La verificación continúa después de leer
el cuerpo: una carga demasiado lenta puede seguir venciendo. Este delta no
acredita la causa ni la resolución de los 401 remotos del 21/10.

## Pausa durante el límite de velocidad

Balde.tomar usaba sleep, que no escucha la orden de pausa. Dos regresiones
aisladas fallaron para red y disco. Ahora recibe la espera interrumpible del
trabajo. Si esa espera lanza Pausa, devuelve los bytes reservados bajo el lock
y propaga la excepción; no deja una deuda de velocidad por bytes no enviados.
Los dos puntos de llamada se actualizaron, sin otros consumidores en el repo.

La espera sigue fuera del lock y el reembolso queda dentro. Una operación de
red o disco ya en curso mantiene el contrato previo; no se fuerza su cierre.
Los tests comprueban que el hilo termina al pausar, que no continúa el envío
o la lectura y que se devuelve el presupuesto. El reloj de prueba se reemplaza
sólo en xfer, sin sustituir el sleep global de Python. Los hilos se cierran
también cuando falla una aserción.

Las tres regresiones finales (firma, pausa de red y pausa de disco) aprobaron.
Ruff focal aprobó. Black --check mostró únicamente un formato preexistente en
el campo pct de xfer.py, contrastado con HEAD; los otros tres archivos pasaron.
No se reformateó código ajeno al delta para silenciar ese resultado.

## Evidencia y límites

La corrida del plugin `2026-10-21T16-45-00.216Z-24548` terminó con rc1:
2977 backend aprobadas, una fallida y diez omitidas. Falló
test_el_que_manda_se_reinicia_y_retoma_sin_releer_lo_hecho: seguía copiando
después de esperar su pausa. No se capturó el stack del hilo durante ese fallo:
la espera no interrumpible es un defecto reproducido aparte, no una causa
acreditada de esa falla concreta. La batería focal posterior queda registrada
en .temp/coordinacion/2026-10-21; no se reemplaza ni se oculta la falla original.

Esa focal terminó rc1: 176 aprobadas, dos fallidas y seis omitidas (373,87 s).
Fallaron otra vez pausa/reanudación y el cierre inmediato WSL (bloque aceptado,
cierre 409 y parcial lleno de ceros). No se presentó como verde.

La sonda de pausa posterior capturó 0/302 archivos confirmados y un worker en
HTTPConnection.getresponse esperando el paquete. El caso había vencido su espera
de 20 s sin alcanzar la precondición de 50 archivos y continuaba igualmente.
La sonda completa terminó rc0; eso no elimina las dos fallas conservadas.
El test ahora usa tres archivos y una barrera tras confirmar el primero; pide
pausa antes de liberar el worker y comprueba la restauración sin volver a
comparar lo ya registrado. Mantiene las aserciones de contenido, mtime, total
y ausencia de salteos. No aumenta timeouts para ocultar un fallo. El caso
corregido y las tres regresiones de producto aprobaron: 4/4, Ruff aprobado.

WSL sigue abierto. Un experimento prefijado de diez cierres nativos y diez sin
truncate produjo 10/10 y 9/10 correctos, respectivamente. El fallo de la segunda
variante fue WinError 2 durante el bloque, antes del cierre. No respalda cambiar
truncate: no se modificó ese código. La sonda nativa existente ejecutó después
tres casos aprobados, sin capturar errores de metadatos; tampoco cancela los
fallos anteriores. Todo quedó bajo .temp/coordinacion/2026-10-21.

La compuerta sigue en FAIL: lee el actual.json completo anterior, cuya huella
no corresponde al código actual, y mutaciones antiguas. La corrida seleccionada
de esta retoma se conserva como actual.parcial.json, sin convertirla en global.

En esa misma corrida aprobaron frontend lint, build, unitarias y 139 recorridos
Playwright con fixtures. Las tres pruebas adicionales de launch-chrome también
aprobaron: el logo Chrome como subíndice existe para sesiones marcadas chrome;
el lanzamiento con Chrome se ofrece para Claude. No se cambiaron los iconos
por inferencia de un pedido ambiguo ni se escribieron sesiones reales.

Sonda aislada: 8.040.000 bytes con igual SHA256, 0,035 s directo y 0,202 s por
el puente local. No mide Tailchrome remoto. Registró un WinError 10058 al cerrar;
no se usa ese resultado como aceptación del puente en uso remoto.

Sin nuevos bloqueantes detectados en el delta, con el fallo de batería anterior
y los límites reales aquí conservados. No hay PASS global ni nueva medición de
mutación: el árbol conserva cambios previos. Sin baselines nuevos, despliegue,
reinicio, reanudación de copias o cierre de tareas. Sigue vigente la pausa de
despliegue documentada en RETOMAR-TRAS-REINICIO.md.
