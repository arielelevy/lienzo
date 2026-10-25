# Reclasificación de creencias revertidas · `lienzo`

- Copias de una misma medición: 10 en 2 métricas → una propuesta por métrica, pendiente de medir la eficacia.
- Para reabrir como pendiente: 3.
- Se mantienen refutadas: 0.
- Ya se leen reemplazadas (tienen sucesora), sin cambios: 7.

## Métrica `difusiones` (3 copias → 1)

Acción: Usar c.aviso(texto, frentes): un solo aviso cuando confirmen todos, sin idas y vueltas.

- `ad788660` El mismo texto a varios frentes casi a la vez: 6 veces
- `4dfd34d5` El mismo texto a varios frentes casi a la vez: 6 veces
- `3a009ea3` El mismo texto a varios frentes casi a la vez: 6 veces

## Métrica `esperas_h` (7 copias → 1)

Acción: Revisar por lotes y dejar a cada frente la tarea siguiente del encargo en vez de «quedo quieto»; un frente por funcionalidad de punta a punta reduce lo que hay que integrar.

- `ad724bfd` Frentes esperando a la coordinadora: 37.0 h en 11 esperas (mediana 56 min)
- `1a9ec353` Frentes esperando a la coordinadora: 37.5 h en 13 esperas (mediana 39 min)
- `b9a883a3` Frentes esperando a la coordinadora: 38.9 h en 15 esperas (mediana 39 min)
- `d1ee99ee` Frentes esperando a la coordinadora: 39.3 h en 17 esperas (mediana 36 min)
- `92dfdee6` Frentes esperando a la coordinadora: 39.5 h en 18 esperas (mediana 32 min)
- `b875ccea` Frentes esperando a la coordinadora: 39.5 h en 18 esperas (mediana 32 min)
- `2b11df1d` Frentes esperando a la coordinadora: 4.1 h en 9 esperas (mediana 16 min)

## Reabrir como pendiente

- `087572ab` falta **eficacia**: Las 25 decisiones pendientes de Ariel salieron en una hora con preguntas de a 5, cada una con opciones y una recomendada.  
  Motivo del rechazo: No hay evidencia de que preguntar en tandas de 5 haya destrabado pendientes; es un consejo sin respaldo.
- `01b7072d` falta **evidencia**: Un mensaje de commit con backticks entre comillas dobles ejecutó kiro-cli en la shell y dejó un hueco en el mensaje (9a651a4).  
  Motivo del rechazo: Sin evidencia en lo provisto: el registro sólo menciona el commit 9a651a4, no un mensaje con backticks que ejecutó comandos ni un hueco en el texto.
- `95889947` falta **evidencia**: En la sesión de Claude Code, un subproceso de prueba que redirige la salida pero hereda el stdin falla con WinError 6; uno sin ninguna redir  
  Motivo del rechazo: Sin evidencia: el registro de las rondas citadas no menciona la falla WinError 6 ni el comportamiento de stdin en subprocesos de prueba.

## Ya reemplazadas (sin cambios)

- `1ae4a9a6` En X, Playwright falló al cerrar una traza con ENOENT en una carpeta compartida. La repetición con --output y TEMP/TMP exclusivos pasó los 5
- `d2965d8b` La batería completa de backend tardó entre 12 min y 2 h según la carga; las fallas por tiempo bajo carga pasaron solas.
- `0f5668cb` WSL retuvo 3,5 GB de caché (vmmemWSL) y dejó la PC con 0,4 GB libres.
- `ee492c65` La vista por pestañas de Chrome siguió con la PC bloqueada a 14–24 c/s sólo con Chrome arrancado con --disable-features=CalculateNativeWinOc
- `93cebc09` Reiniciar el server con trabajo sin commitear de un frente carga ese código a medias.
- `5d316bda` Desde 19747a2 las reglas de un frente cerrado sólo las hereda una sucesora real; antes, cualquier sesión nueva en la carpeta heredaba y mand
- `74387935` Con Chrome en uso en la PC ariel, cuatro frentes Claude dejaron 1,1 GB libres y el clic remoto de Chrome dio 504.

