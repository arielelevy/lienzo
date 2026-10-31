# Revisión de Denegar en las tarjetas

Alcance: API y envío en `lienzo/server.py`, acuse en `lienzo/sessions.py`,
`web/src/api.ts`, `web/src/hooks/useCardActions.ts`, `web/src/components/CardNeeds.tsx`
y sus regresiones. Revisión estática secuencial de los cambios autorizados.

Denegar envía `deniega_denegado`, nunca `autoriza_denegado`. El mensaje conserva el rechazo
y prohíbe reintentar. La confirmación de acciones graves sigue vigente para Autorizar.
Ambos botones se desactivan durante el envío. El cache de avisos resueltos no concede permisos.
No se actuó sobre el aviso desaparecido de openSeec.

Hallazgos corregidos:

- Una excepción al guardar el acuse dejaba la tarjeta modificada. Se restaura su snapshot
  antes de propagar el error. La prueba negativa reprodujo el problema antes del arreglo.
- Una excepción de transporte en `accion_send` dejaba oculto el aviso sin entregar la
  decisión. Se revierte el acuse y `sin_aviso` tanto ante código de error como ante excepción;
  ésta se propaga. Dos pruebas negativas, para Autorizar y Denegar, fallaron antes del arreglo.
  La primera verificación posterior detectó una diferencia de fixture None/False en la bandera
  de autorización: el fixture se inicializa explícitamente sin autorización activa.

Evidencia: `pruebas-agenticas/resultados/release-0.6.19-20261031/denegar/`.
`excepcion-rojo.log`: 2 fallos esperados. `excepcion-verde-final.log`: 120 passed en 36,78 s.
Fuentes verificadas y reemplazadas por archivo de forma atómica tras AST, Ruff check y format.
Frontend global: 355 passed y 16 skipped; recorrido focal: 8 passed.
Captura móvil revisada: `denegar-celular.png`; ambos controles caben en 390 px.

Límites: recorridos UI con fixtures; no se inyectaron decisiones en sesiones reales.
El primer setup móvil falló y quedó conservado antes de corregir la preparación del viewport.
No hay mutaciones nuevas aprobadas de Denegar. No se certifica el release: la otra PC conserva
dos regresiones de rendimiento fallidas. No se reinició el servidor ni se publicó esta tanda.
