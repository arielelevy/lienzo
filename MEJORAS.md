# Mejoras del lienzo, anotadas a medida que se usa

Registro vivo: cada vez que repartir trabajo con el lienzo (sobre todo entre PCs) muestra un
tropiezo o una idea, se anota acá con la evidencia, y cuando se arregla pasa a «Hecho». La fuente
de cada punto es una sesión real, no una suposición. Última actualización: 2026-10-02.

## Hecho

| Fecha | Mejora | Evidencia / motivo |
|---|---|---|
| 2026-10-01 | **Recarga automática del server**: `lienzo-server.cmd` lo relanza (salida 75) cuando cambia un `.py`; no relanza sobre código que no compila | había que parar y levantar el `.cmd` a mano tras cada `git pull`; la otra PC quedaba con código viejo |
| 2026-10-01 | **Timeout de 70 s** para `send`/`launch`/`attach` entre PCs (antes 5 s) | un envío tarda hasta 60 s en teclear; con 5 s aparecía como «sin conexión» aunque se hubiera tecleado |
| 2026-10-01 | **Tarjeta fantasma**: si la otra PC dice «sesion desconocida», el server la saca del tablero y pide el estado de nuevo | los envíos a una tarjeta que ya no existía rebotaban para siempre |
| 2026-10-01 | **Reintento solo si el pedido no llegó** (conexión rechazada); un timeout NO se reintenta | reintentar tras un corte a mitad podría teclear el texto dos veces |
| 2026-10-01 | **Log de reenvíos que fallan** (`→ <pc> POST …`) | no quedaba rastro de nada en el origen; no se podía saber si el pedido había salido |
| 2026-10-01 | `coordinar.enviar_seguro`: verifica que la tarjeta tomó el encargo y se recupera de 404/503 | un `200` solo dice que el server aceptó, no que se tecleó |
| 2026-10-02 | `enviar_seguro` **rechaza caracteres de control** en el texto | una ruta `D:\apps` sin escapar llegó como `D:<BEL>pps` y el server borró el carácter sin avisar: 4 codas buscaron rutas que no existían |
| 2026-10-01 | `coordinar.reubicar`: sigue a una tarjeta cuando cambia de id (`pid-NNN` → UUID) | `enviar_seguro` dio un falso negativo con el coda, que cambió de id al engancharse los hooks |
| 2026-10-01 | `coordinar.estancada(s, minutos)`: detecta un agente colgado (pantalla sin cambios y `corriendo`) | el coda quedó 5 min en «Waiting for model» y nadie lo vio |
| 2026-10-01 | `coordinar.capacidad(pc, n)`: mira la memoria libre antes de abrir sesiones | la otra PC tenía 0,76 GB libres con 6 codas abiertos |
| 2026-10-01 | `coordinar.lanzar_y_titular`: devuelve la tarjeta nueva, ya titulada | `lanzar` solo da el 200; hay que adivinar cuál tarjeta es la nueva |
| 2026-10-02 | **Cableado entre PCs**: reglas `on_stop` de los frentes de la otra PC hacia la coordinadora (5 reglas, cruzan PC) | no había nada cableado: la coordinadora tenía que consultar cada frente a mano |
| 2026-10-01 | `SKILL.md`: secciones «Mandar un encargo a otra PC…» y «Repartir en otra PC: lo que ya salió mal una vez» | todo lo anterior, para que la próxima ronda no repita los tropiezos |

## Pendiente (con evidencia)

- **Selección múltiple con Ctrl en el tablero** (pedido del usuario, 2026-10-02): hoy un click elige
  una sola tarjeta (`picked` en `Board.tsx`) y Ctrl+C/V copia trabajo de la elegida. Falta: Ctrl+click
  suma o saca tarjetas de una selección, y poder seleccionar de una vez **todas las de un proyecto**.
  Acciones sobre la selección: enviar un mismo texto a todas, cablear todas a la coordinadora,
  interrumpir, cerrar. Esc la limpia.
- **Latencia entre PCs**: un pedido mínimo a la otra PC tarda ~86 ms (mediana, p95 136 ms) contra 2,5 ms
  local; la pantalla de una tarjeta remota, ~470 ms. Cada pedido abre una conexión TCP nueva y firma
  con HMAC. Idea: conexión persistente (keep-alive) por peer y cachear `screen` unos 500 ms.
- **El SSE del peer se corta y reconecta cada ~15 s** (`peer GET /peer/events` en el log cada 15 s).
  Funciona, porque cada reconexión trae el snapshot entero, pero es tráfico de más y una ventana en
  la que el espejo se reemplaza. Hay que ver si el server corta el stream a propósito.
- **`launch_roots` no se ve desde la otra PC**: `peers.json` no lo trae y no hay forma de saber qué
  carpetas permite un peer sin intentar lanzar. Mostrarlo en `GET /peers`.
- **Log de los reenvíos que andan bien**: hoy solo se loguean los que fallan. Sumar la latencia
  (ms) de cada reenvío ayudaría a ver una PC que se vuelve lenta.
- **Coda no tiene hooks en el lienzo**: nace como tarjeta de barrido (`pid-NNNN`, sin título ni
  transcripción), cambia de id, y su estado no refleja que está trabajando. Un hook de coda daría
  título, estado y `last_reply` confiables.
- **Un solo modelo para todos los codas**: Qwen en el DGX atiende de a poco; con 5 codas a la vez
  todos quedan en «Waiting for model». El coordinador tiene que escalonar el trabajo, no repartirlo
  en paralelo sin límite. `capacidad` mide RAM, no el cupo del modelo.
- **Traspasar un encargo entre PCs**: copiar y pegar trabajo entre tarjetas funciona dentro de una
  PC; entre PCs no hay forma de mover un encargo a una tarjeta de la otra.
- **Persistir las reglas cruzadas si la otra PC reinicia**: una regla vive en la PC del `from`; si
  esa PC reinicia el lienzo, hay que ver que sobreviva (hoy se guardan en `~/.lienzo`, falta probarlo
  con un reinicio real).
- **Pruebas reales pendientes** (solo se probaron con transportes simulados): recuperación cuando una
  tarjeta remota ya no existe, y el reintento ante conexión rechazada.

## Ideas

- Un panel «PCs» con la latencia y la memoria libre de cada una en vivo, y la cola del DGX.
- `coordinar.repartir(proyecto, modulos, pcs)`: reparto automático según `capacidad`.
- Aviso en el tablero cuando una tarjeta lleva N minutos `corriendo` sin que cambie su pantalla.
