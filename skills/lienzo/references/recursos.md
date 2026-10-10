# CPU, memoria y temperatura

Parte de la skill `lienzo` (se lee desde `SKILL.md` cuando hace falta).

## CPU, memoria y temperatura: la coordinadora los vigila

Con seis sesiones en una máquina de 15 GB la memoria se termina antes que la CPU. Medido el
2026-09-26 en un proyecto con base de datos en WSL: Windows bajó dos veces a menos de 50 MB libres, WSL se reinició solo de
noche y se cortaron mediciones a mitad. Las sesiones de Claude solas ocupaban 4,3 GB.

Reglas que van en el encargo común de cada ronda:

- Una sola tarea pesada a la vez en toda la máquina: una batería de pruebas, una consulta o un
  índice grande, un navegador con Playwright, o la API con el dev server levantados. Antes de
  lanzar, el frente mira que no haya otra corriendo y la memoria del lado donde corre:
  - adentro de WSL (pruebas, índices, consultas, API): `available` de `free -m` en WSL con al
    menos 3 GB, y Windows con al menos 1 GB;
  - del lado de Windows (Edge, Playwright): Windows con al menos 2 GB.

  Un piso único de 2 GB en Windows traba la ronda entera, medido el 2026-09-26: WSL tenía 8 GB
  libres adentro y Windows veía 1,8, porque WSL no devuelve enseguida lo que libera, y cinco
  frentes quedaron esperando una memoria que no necesitaban.
- Con cinco o más frentes, el cupo lo cuenta la máquina, no cada frente. Si cada uno mira
  `pgrep` antes de lanzar, dos miran a la vez, ven lugar y lanzan los dos: el 2026-09-26 con el cupo
  de dos la carga llegó a 19 sobre 12 procesadores y 95 °C. La salida es un semáforo con `flock` en
  WSL (por ejemplo `~/.cache/<proyecto>/pesada.sh`): dos archivos de turno, cada tarea pesada se
  lanza envuelta (`bash pesada.sh <comando>`), espera turno, chequea `MemAvailable` y suelta el
  turno al terminar aunque falle. Deja un registro de quién corrió qué y cuándo.
- Las consultas de medición van sin paralelismo del lado de la base (en Postgres,
  `SET max_parallel_workers_per_gather = 0`) y con `nice 19`.
- Al terminar, cada frente cierra lo que levantó: servidores, navegadores, motores.

Lo que mide la coordinadora, antes de lanzar algo pesado y cada vez que llega un informe:

```powershell
# memoria libre de Windows, en GB
[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)
# quién la tiene: memoria privada por nombre (el WS de vmmemWSL engaña)
Get-Process | Group-Object ProcessName | % { [pscustomobject]@{n=$_.Name; GB=[math]::Round((($_.Group | Measure-Object PrivateMemorySize64 -Sum).Sum)/1GB,2)} } | Sort-Object GB -Desc | Select -First 8
# temperatura sin administrador: HighPrecisionTemperature en deciKelvin
Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | % { "$($_.Name) $([math]::Round($_.HighPrecisionTemperature/10-273.15,1)) °C" }
```

El sensor bueno es `\_TZ.THRM` (`\_TZ.TZ01` da 20 °C fijo). En el Ryzen 9 7940HS, 95 °C sostenidos
es su techo de diseño, no una alarma; 81 °C es la máquina descansando de un trabajo largo. La carga
de CPU sale de `\Processor(_Total)\% Processor Time` y, adentro de WSL, de `uptime`.
`Win32_Processor.CurrentClockSpeed` miente: da el máximo fijo.

**Con varias PCs, cada una vigila la suya y `GET /peers` trae el resumen** (memoria libre y
temperatura de cada chip de la tira). Para el detalle fino de una PC remota, `/peer/health` de esa
PC (mismos tres números que arriba, medidos del lado de allá); no hay forma de correr el
PowerShell de arriba contra una máquina que no es la propia. Mismo semáforo y mismos pisos que en
una sola PC: la memoria justa de una no se compensa con que sobre en la otra.

Un monitor permanente mientras dure la ronda: un `.ps1`
lanzado oculto (`Start-Process pwsh -WindowStyle Hidden -File monitor.ps1`) que cada minuto anota
temperatura, CPU, memoria libre de Windows y carga y memoria de WSL en un CSV, y que cuando algo
pasa su umbral le escribe a la coordinadora por `POST /sessions/<coordinadora>/send`, con 10
minutos de pausa entre avisos del mismo tipo. Umbrales: 96 °C (no menos: el 7940HS se queda en 95
por diseño y avisar antes es avisar siempre), Windows con menos de 0,5 GB, carga de WSL de 14 o más.
Conviene dejarlo en el scratchpad de la coordinadora como `monitor.ps1`.

Cuando la memoria se termina, en este orden y sin matar el trabajo de nadie:

1. Liberar la caché de disco de WSL, que se queda con lo que leyó y no lo devuelve sola:
   `sync; echo 1 | sudo -n tee /proc/sys/vm/drop_caches`. Windows lo recupera en unos 30 s.
   Con seis o más frentes conviene dejarlo automático: un lazo en WSL que cada 60 s mira
   `Buffers + Cached` de `/proc/meminfo` y, si pasa de 3 GB, hace ese mismo `drop_caches`. Se lanza
   una vez con `setsid nohup ... & disown` desde un `.sh`, y se busca con `pgrep -f "[v]igia"`: el
   nombre del guion no puede aparecer literal en la línea que lo busca, o `pgrep` se encuentra a sí
   mismo. Y compactar: `echo 1 | sudo -n tee /proc/sys/vm/compact_memory`, cada 5 minutos en
   el mismo lazo. WSL devuelve las páginas libres en bloques grandes, y con la memoria fragmentada
   no hay bloques que devolver: el 2026-09-26 Windows estaba en 0,06 GB con 7 GB disponibles
   adentro de WSL, y compactar lo llevó a 1,93 GB en segundos. `autoMemoryReclaim=gradual` en el `.wslconfig` ayuda, pero devuelve la caché más lento de
   lo que la llenan un índice o una subida grande (medido el 2026-09-26: Windows en 210 MB con
   `gradual` puesto).
   **Si `drop_caches` no mueve nada, lo de WSL no es caché**: el 2026-10-04 `free -m` dio 8,2 GB
   `used` y 3,8 de `buff/cache`, y Windows bajó igual de 1.268 a 815 MB disponibles. Lo que ocupa son
   los servicios levantados (API, dev server, motores, base): bajarlos o lanzar en la otra PC si
   `capacidad(pc, n)` da lugar.
2. Cerrar con `/exit` las sesiones que terminaron.
3. Postergar lo que no apura (mediciones de navegador) y decírselo al frente.
