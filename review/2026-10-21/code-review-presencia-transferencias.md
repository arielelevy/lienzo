# Revisión de presencia segura en transferencias

Alcance: delta de `lienzo/xfer.py` y `tests/test_xfer.py` posterior a 0.6.0.
Entrega de E contrastada por raíz contra los archivos y sus SHA256 congelados.

La contradicción se reprodujo con un parcial de dos bloques y respuestas falsas de exists:
estado, bloque y cierre descartaban contenido válido. Un error de acceso al diario también
podía interpretarse como ausencia y autorizar borrado. Cuatro regresiones fallaron antes del
cambio. Los controles posteriores distinguen presencia, ausencia y errores de validación.

`_presente_seguro` usa la apertura existente, con confinamiento, tipo y nlink. Sólo una
ausencia producida por la llamada de apertura devuelve None; las consultas posteriores de
metadatos y fstat propagan errores, incluido WinError 2. El descriptor se cierra al validar
presencia y se vuelve a verificar al escribir. No convierte una observación en garantía
contra carreras ni amplía FILE_SHARE_DELETE. Un fallo del diario conserva el parcial;
su ausencia, cabecera incompatible o ASCII inválido conservan la semántica de reinicio.

La revisión no encontró una relajación concreta de pinning, apertura relativa,
OBJ_DONT_REPARSE, rechazo de enlaces, truncado después de validación ni publicación por
handle. No cambia CRT, la lista de hashes ni los reintentos. Agrega una apertura por
comprobación de presencia; no acredita una mejora de rendimiento.

Focal completa de presencia: 60 aprobadas, 1 fallida, 6 omitidas, rc1. La suspensión medida
se conserva en sus tiempos y no invalida el fallo: `NtSetInformationFile` rechazó la
publicación con WinError 2 después de verificar hashes. Los diez cierres del otro caso WSL
pasaron; no se mezclan para declarar resuelta la intermitencia. No hay ejecución de la rama
del receptor en Linux ni prueba de todos los redirectores.

El ajuste diagnóstico posterior conserva el NTSTATUS de esa misma excepción. Su regresión
roja/verde verifica una sola llamada, mismo handle, RootDirectory, nombre relativo, replace,
clase 10 y bytes intactos ante error. No cambia los argumentos ni convierte un fallo en éxito.

Evidencia privada: `.temp/resultados/E-wsl-frio/presencia-*`, `rename-status-*` y
`rename-freeze-review.md`. Los cinco roles secuenciales constan allí. Sin aprobación de
baseline, cambio de permisos, nuevos AGY ni tareas marcadas completadas. El fallo natural
de WSL y su causa siguen abiertos; este informe no es un PASS global.
