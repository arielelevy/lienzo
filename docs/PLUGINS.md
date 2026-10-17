# Plugins y catálogo de Lienzo

Referencia consolidada el 2026-10-16. Describe el mecanismo, el contrato uniforme y sus límites.
La dirección de producto está en [Producto](PRODUCTO.md).

## Conceptos

Una tool es una herramienta para una tarea concreta, como RTK o Anatomy.
Un plugin es una extensión de Lienzo que puede integrar sistemas, incorporar una forma de trabajo
o aportar herramientas. Puede combinar capacidades y puede no aportar ninguna tool.
Un skill describe cómo trabajar; puede formar parte de una herramienta o de un plugin.
La integración local con Stepwise es el ejemplo existente de integración entre sistemas.

## Mecanismo existente

El cargador `lienzo/plugins.py` descubre módulos Python en `lienzo/extensiones/`.
Los nombres admiten minúsculas, números y guion bajo, empezando por letra.
Un módulo que no carga deja su error en el log y no impide cargar los demás.

Todos estos puntos de extensión son opcionales:

| Punto | Contrato actual |
|---|---|
| Inicio | `iniciar()`, llamado al iniciar los plugins |
| Lectura HTTP | `get(partes, query) -> (codigo, cuerpo)` bajo `/ext/<nombre>/...` |
| Escritura HTTP | `post(partes, cuerpo, ctx) -> (codigo, cuerpo)`; `ctx` incluye autor |
| Procesos externos | `RUNNERS_EXTERNOS: dict[str, str]`, ejecutable a clase de proceso |
| Vista | Exportación por defecto de un componente en `web/src/extensiones/*.tsx` |

Las rutas pasan por autenticación y protección CSRF del servidor según su método.
La vista recibe `toast` mediante `PluginProps` y se incorpora por el glob de Vite.
Agregar una vista requiere reconstruir el frontend; copiar el archivo no implica recarga dinámica.
El backend carga módulos al arrancar. No hay hot reload ni desinstalación; la parada es opcional.

El plugin ejecuta Python dentro del proceso del servidor. El cargador no es un sandbox
ni aplica los permisos declarados en el manifiesto. No se presentan como una protección.

## Distribución local

Las carpetas de extensiones del backend y frontend están excluidas de Git.
Una entrada del catálogo puede apuntar a una integración local sin URL pública.
El núcleo debe funcionar sin esos plugins. Su disponibilidad depende de cada PC.
No se asume réplica automática del paquete, su configuración, sus credenciales ni su estado.

Stepwise se conserva local. El commit `720cab2` documentó que su e2e no entra a la suite
portable del núcleo porque depende de binarios y fixtures de esta PC.
El origen local no lo exime de sus propias pruebas y revisión.

## Catálogo actual

`lienzo/tools/` contiene el catálogo estático de tools. `GET /tools` y el panel de
Mejoras muestran origen, versión declarada, costo, modos y disponibilidad.
Ese catálogo y el cargador de plugins son mecanismos distintos.
El código del catálogo enumera respuestas breves, RTK, Jev, pruebas agénticas, REA, Anatomy,
y Commit. Las fichas incluyen formato, compatibilidad y limitaciones.
No instala ni autoriza consumo por mostrar una entrada.
Anatomy reutiliza su integración existente y comprueba presencia del kit, sin certificar render.
Los plugins locales, cargados o no, se inventarían por separado en el panel de Mejoras, sin
invocarlos ni exigirles tools. Cargado no significa conectado ni sano.

## Better Claude

Ariel instaló Image Preview, Sub Meter y Commit en Claude Code, pero sólo Commit es ficha de Lienzo
(decisión del 2026-10-17): los otros dos son mejoras de la terminal, no parte de Lienzo.
Se distribuyen como plugins de Claude Code. No son extensiones
Python de Lienzo ni se inyectan en Codex, Pi o CODA.

| Ficha | Capacidad | Límite relevante |
|---|---|---|
| [Image Preview](https://github.com/midudev/better-claude/tree/main/plugins/image-preview) | Vista previa de imágenes pegadas | Hover con fullscreen; el autor aún no acredita ejecución en Windows |
| [Sub Meter](https://github.com/midudev/better-claude/tree/main/plugins/sub-meter) | Cuota de suscripción de 5 horas y semanal | Sin suscripción no muestra cuota; no integra métricas al scheduler |
| [Commit](https://github.com/midudev/better-claude/tree/main/plugins/commit) | Agrupación de commits y opciones de publicación | No interactivo hace commit y push; rama nueva también hace push; consume modelo/cuota de la cuenta |

El estado lee el registro de instalación y enabledPlugins de Claude Code, comprueba archivos,
nombre del manifiesto y scope de usuario, y muestra la versión instalada que dice el registro. Las instalaciones de proyecto requieren contexto propio;
no se presentan como disponibles globalmente. Una instalación Windows no acredita WSL.
Un archivo corrupto muestra el motivo; consultar no modifica archivos ni ejecuta instaladores.
Instalado y habilitado no acredita compatibilidad del mod ni que una sesión abierta lo haya cargado.

Contraste con upstream (`midudev/better-claude` a817804, 2026-10-16): el marketplace se llama
`better-claude` y los manifiestos declaran `image-preview` 0.1.1, `sub-meter` 0.1.0 y `commit` 0.2.0.
Las fichas los reconocen con un registro de prueba con ese formato. Instalados en esta PC el
2026-10-17 por pedido de Ariel (scope user); el catálogo vivo los muestra habilitados con esas versiones.

Las instrucciones de instalación se muestran como texto. Este cambio no instala Better Claude,
no cambia hooks/settings y no ejecuta /commit. El servidor activo todavía mostraba las cinco fichas
anteriores en la observación real; los cambios de backend requieren activación coordinada.
Verificación del área: runner catalogo-comunidad.json, contratos backend y siete recorridos UI
con API fixture. La compuerta y la aceptación se informan con sus artefactos; no se fija baseline solo.

## Contrato uniforme (versión 1)

Implementado en `lienzo/plugin_manifest.py` y aplicado por `lienzo/plugins.py`. El manifiesto es
`lienzo/extensiones/<id>.plugin.json`, junto al módulo. Se valida antes de importar el código.

| Área | Clave | Obligatoria |
|---|---|---|
| Identidad | `id` (igual al archivo), `nombre`, `version`; `descripcion` y `responsable` | Sí, salvo las dos últimas |
| Compatibilidad | `compatibilidad.contrato` (entero o lista) y `plataformas` (`windows`, `linux`, `macos`) | Sí |
| Permisos | `permisos` con `lectura`, `escritura`, `ejecucion`, `red`, `efectos_externos` | Sí; listas vacías válidas |
| Origen | `origen.tipo` (`local`, `privado`, `publico`) y `origen.url` https | No; público exige url |
| Capacidades | `integracion`, `forma-de-trabajo`, `tools`, `documentacion`, `evaluacion` | No |
| Puntos | `get`, `post`, `runners_externos`, `vista` | No |
| Ciclo de vida | `iniciar`, `salud`, `detener` | No |
| Configuración | `configuracion.campos`: `clave`, `tipo`, `obligatorio`, `descripcion` | No |
| Evidencia | `logs`, `eventos`, `pruebas`, `resultados` | No |
| Relaciones | `relaciones.tools` y `relaciones.sistemas` | No |

Ejemplo mínimo, una forma de trabajo sin código, tools, endpoints ni interfaz:

```json
{"id": "notas", "nombre": "Notas de ronda", "version": "1.0.0",
 "compatibilidad": {"contrato": 1}, "permisos": {}, "capacidades": ["forma-de-trabajo"]}
```

Reglas de carga:

- Manifiesto inválido: el módulo no se importa; la ficha queda `error` con cada motivo.
- Contrato o plataforma incompatibles: no se importa; estado `incompatible`.
- Nombre en `plugins_deshabilitados` de `~/.lienzo/config.json`: no se importa; estado `deshabilitado`.
  Tiene precedencia: un manifiesto roto de un plugin apagado no se informa como error.
- Con manifiesto, lo exportado debe coincidir con `puntos` y `ciclo_de_vida`. Si sobra o falta algo,
  el módulo ya ejecutó su import pero no se registra: sin rutas ni procesos externos.
- Manifiesto sin `.py`: plugin declarativo, estado `declarado`. No puede declarar puntos de código.
- Módulo sin manifiesto: carga legacy igual que antes. La ficha dice `manifiesto: ausente` y
  `permisos: null`; no se infieren permisos. Stepwise sigue así.
- Una `vista` declarada sin `web/src/extensiones/<id>.tsx`, o al revés, es una advertencia.
- Claves desconocidas y relaciones con tools fuera del catálogo son advertencias, no errores.

La configuración vive en `config.json["plugins"][<id>]`, separada de las claves propias de Lienzo. Un campo `secreto` guarda el nombre de una variable
de entorno: se comprueba que exista, nunca se lee ni se devuelve su valor. Un secreto en claro es un
error de configuración. Con campos obligatorios faltantes, el módulo carga y la ficha dice
`sin-configurar` con lo que falta.

Estados de la ficha: `cargado`, `declarado`, `sin-configurar`, `deshabilitado`, `incompatible` y
`error`. Ninguno significa conectado ni sano. La salud es aparte y sólo a pedido:
`GET /ext/<id>/_salud` llama a `salud()` si el manifiesto la declara, con límite de 5 s.
Mientras una comprobación colgada no termina, otra contesta 409 en vez de apilar hilos.
La ruta `_salud` sólo se reserva para plugins con manifiesto; un legacy la recibe como siempre.
`plugins.detener()` llama a `detener()` de quienes lo declaran, en orden y a modo de mejor esfuerzo.
El server lo invoca antes de salir (reinicio, recarga, Ctrl+C) con 3 s de tope total: un plugin colgado
no traba la salida, pero los que vienen después de él pueden quedar sin parar.
Si `iniciar()` falla en un plugin con manifiesto, sus rutas `/ext/<id>/...` contestan 503.
Un legacy conserva el comportamiento anterior.

El panel de Mejoras muestra cada ficha: estado, manifiesto, capacidades, versión, origen, mecanismos,
configuración faltante, errores, advertencias y permisos con el texto «declarados, no aplicados por
Lienzo». El botón «Comprobar salud» aparece sólo en plugins cargados que declaran salud.

El manifiesto no es un sandbox. Lienzo no aplica los permisos declarados; el plugin sigue corriendo
Python con los permisos del server. Validarlo acredita estructura y coherencia, no seguridad,
calidad ni utilidad. Tampoco autoriza instalación, consumo ni cambios.

## Incorporación

1. Registrar el paquete y su manifiesto, con el origen real.
2. Validar compatibilidad, configuración y capacidades declaradas.
3. Mostrar la entrada y sus requisitos en el catálogo.
4. Presentar permisos y efectos concretos antes de habilitar lo que los requiera.
5. Ejecutar sus comprobaciones y conservar resultados, errores y limitaciones.
6. Habilitar según la decisión de Ariel y el alcance autorizado.

## Límites y decisiones pendientes

Queda por decidir: controles efectivos de permisos, rango de versiones del contrato,
llamada a `detener()` al cerrar el server, recuperación ante fallos, distribución entre PCs,
formato de eventos y manifiesto propio de Stepwise (versión y responsable los decide Ariel).
El catálogo puede relacionar plugins y tools, pero no debe exigir esa relación ni duplicar
una tool por cada forma de empaquetarla. Las tareas se mantienen en [Pendientes](../PENDIENTES.md).
