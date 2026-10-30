# Copiar archivos entre PCs

[Volver al README](../README.md)

`POST /xfer {pc, origen, destino}` (o `coordinar.copiar`) copia un archivo o una carpeta de esta PC a
la carpeta `destino` de otra, por el mismo listener de peers: sin SMB, sin puerto nuevo, sin otra
credencial. Un `robocopy /Z /MT` hecho en casa:

- Por bloques y retomable. Bloques de 8 MiB, cada uno su propio pedido firmado. El que recibe
  escribe a `<archivo>.parte` y anota cada bloque verificado en `<archivo>.parte.diario`; el que manda
  guarda su avance en `~/.lienzo/xfer/trabajos/`. Un corte o un reinicio de cualquiera de las dos
  puntas retoma desde ahí.
- Paralelo. 6 bloques en vuelo (`hilos`); los archivos de menos de 1 MiB viajan en paquetes de
  hasta 256.
- Verificado. sha256 por bloque al llegar (1,5 GB/s con SHA-NI, contra 0,56 de blake2b). Al
  cerrar se relee el `.parte` entero contra la lista del que manda y recién ahí se renombra. Un bloque
  distinto se rechaza y se vuelve a mandar; un archivo que cambia en el origen mientras viaja se
  vuelve a pasar.
- Sólo lo que cambió, comparando hashes por bloque (tamaño y fecha no alcanzan).
- Nunca borra en el destino, salvo `espejo: true`, que primero lista lo que borraría y espera
  `POST /xfer/<id>/confirmar`. El espejo borra por el handle fijado de la carpeta padre y rechaza
  enlaces: una junction puesta entre validar y borrar no lo hace borrar fuera del destino.
- No mata la máquina. Topes `mbps` y `disco_mbps`, prioridad baja de CPU y disco, y se frena si
  cualquiera de las dos PCs baja de 1,5 GB libres (sigue sola cuando se libera).
- Rutas permitidas. Origen y destino tienen que caer en `copy_roots` o en `launch_roots` del
  `config.json` de su PC (vacías es ninguna). Las de `launch_roots` cuentan porque una PC emparejada
  ya puede lanzar un agente ahí, así que un repo se copia de raíz a raíz sin tocar la config;
  `"copy_incluye_launch_roots": false` lo apaga. Las de WSL, como `\\wsl.localhost\<distro>\...`.

Lo medido entre dos PCs el 2026-10-04:

- Corte provocado: con el lienzo del que recibe reiniciado al 40 % de un archivo de 2 GB, la
  copia retomó sola a los 12 s, desde el diario.
- WSL por 9p: lee un archivo grande a 149 MB/s (más que una LAN gigabit) pero sólo ~600
  archivos/s chicos con 16 hilos. Sirve para un volcado de pocos archivos grandes.
- La caché de WSL se come la memoria. Lo que pasa por 9p queda en la caché de la VM de WSL, que
  Windows cuenta como memoria de `vmmemWSL`: copiando 2 GB, la PC que recibía bajó de 2,6 a 0,5 GB
  libres y la copia se frenó sola. El canal ahora le pide a WSL que suelte la caché de cada archivo
  cada 256 MB y al cerrarlo (`dd iflag=nocache count=0`, 2 GB en 2 s). Lo que cachean otros
  procesos de WSL (una base de datos, por ejemplo) sigue ocupando: para eso, `autoMemoryReclaim` en
  `.wslconfig`.
- Velocidad sostenida: sin medir todavía. Con las dos PCs cargadas de agentes la memoria libre
  no pasó de la reserva el tiempo suficiente.
