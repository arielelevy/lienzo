# Antigravity: ejecutable renombrado por actualización

Alcance: revisión focal de `lienzo/antigravity_identity.py` y
`tests/test_antigravity_reader.py`, dentro de la revisión autorizada de Lienzo.
Realizada secuencialmente por la coordinadora; no es una revisión independiente.

La API desplegada 0.6.4 devolvió `process_identity_mismatch` y cero turnos.
La consulta nativa del PID 20088 devolvió el mismo instante de inicio, pero una
imagen terminada en `agy.exe.1792586409122112700.old`. El nombre cambió al actualizar
el ejecutable; el lector rechazaba la ruta antes de verificar el hash conocido.

El cambio admite `agy.exe` o `agy.exe.<1–20 dígitos ASCII>.old` exclusivamente
en el directorio oficial del usuario. No busca ejecutables alternativos ni cambia
el hash admitido. Conserva fecha de creación, proceso fijado por handle,
propietario exclusivo del archivo de presencia, identidad antes/después de la
lectura, límites de SQLite y rechazo de rutas redirigidas. No habilita fin/on_stop.

Revisión estática: sin nuevos bloqueantes detectados en el delta. La expresión
regular está anclada mediante fullmatch y no admite subdirectorios ni sufijos extra.
La llamada de fingerprint sigue siendo obligatoria para ambas formas válidas.
No hay nuevas dependencias, escritura de conversaciones, RPC ni inferencia.
El fingerprint mantiene su carrera preexistente entre comprobaciones de archivo;
este cambio no pretende convertir esas comprobaciones en una apertura atómica.

Evidencia: regresión previa `1 failed, 5 passed` en
`.temp/coordinacion/2026-10-21/agy-rename-red-external.log`.
El primer intento sandbox quedó impedido por WinError 5 y se conserva separado.
Primera focal corregida: 143 aprobadas; luego se ampliaron dos clases negativas
y la comprobación de que se llama al fingerprint. La batería backend previa al
reinicio terminó: 2977 aprobadas, 10 omitidas, rc0 (821,50 s), conservada en
`agy-rename-backend-actual.parcial.json`. No se modificó el baseline.

Lectura directa del código corregido contra el único proceso existente: cinco
turnos, cinco bloques de texto, catorce de herramientas, cero `ended=true`, sin
truncamiento. No se guardaron cuerpos de conversaciones en la evidencia.
Esto todavía no prueba el código desplegado: la API 0.6.4 continúa usando el lector
anterior hasta publicar/aplicar una actualización.

Pruebas agénticas, roles secuenciales:

- Explorer: respuesta real de `/sessions/pid-20088/turns`, contraste con NativeProbe.
  La UI no pudo observarse porque el controlador del navegador agotó su tiempo.
- Analyser: conservar identidad y hash conocidos, recuperar historial tras rename;
  fin de turno continúa sin contrato acreditado.
- Designer: ampliar el caso vigente con rename válido, nombres inválidos, otra
  carpeta, longitud excesiva y comprobación de fingerprint; hash desconocido
  rechazado también bajo nombre renombrado.
- Executor: roja y focal aisladas; caso aprobado `backend-pytest` mediante el runner,
  sin `--fijar`, `--aceptar` ni cambio de configuración aprobada.
- Detective: roja atribuida a comparación exacta de ruta; lectura directa recuperada.
  La batería previa terminó sin fallas. La nueva retoma incorporó una regresión
  de conexión: 2977 aprobadas, una fallida y diez omitidas; la falla está en
  pausa/reanudación de xfer y se conserva por separado. No hay aceptación global
  ni tareas cerradas.
