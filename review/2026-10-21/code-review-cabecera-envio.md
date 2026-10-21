# Revisión de cabecera durante un envío

Alcance: agrupamiento de repo/rama en `Card.tsx` y dos selectores de `styles.css`, después
de la global del commit239b0f5.
La global conserva su FAIL:2939 backend aprobadas/10 omitidas y138 UI aprobadas/1 fallida.
El caso vigente `tarjeta.spec.ts:146` midió153px sin envío y176,5px con «enviando…».
El cambio anterior permitía que todo el grupo derecho saltara debajo del repo/rama.

Repo y rama comparten un grupo flexible de base0, con sus recortes y títulos originales.
El agente queda fuera, sin encogerse. El grupo derecho conserva su tamaño intrínseco, wrap
interno y ancho máximo; puede pasar a otra fila si él solo no entra. La decisión de wrap
ya no usa el ancho natural de repo/rama como si fuera irreducible. No hay excepciones por
agente o por estado de envío, ni cambios de semántica o teclado.

Se reutilizan los oráculos originales de tarjeta, tablero, flechas y PCs. La revisión contrasta
selectores y especificidad: los hijos del nuevo grupo conservan min-width0 y recorte; las
reglas de repo y rama conservan su prioridad de encogido. Badge queda fuera del grupo para
no quedar oculto cuando la identidad recibe poco ancho. Se conservan overflow visible en
las acciones, etiquetas de estado y contornos de foco. Las cabeceras de tarjetas libres o
desconectadas conservan su DOM: no muestran este indicador de envío. No se debilita ninguna aserción.

Explorer: FAIL global preservado. Analyser: salto de23,5px por wrap exterior. Designer: ceder
ancho de repo/rama antes de distribuir controles. Un primer ajuste sólo CSS pasó46 controles
pero dejó la tarjeta en171,5px y se descartó. La sonda de cajas con el fixture confirmó la causa.
Executor:47 pruebas originales aprobadas, rc0,33,8s, contra Vite7393 con output exclusivo;
ESLint focal rc0. Detective: altura estable y regresión Antigravity conservada, con teclado,
flechas, cambios de ancho y390px. Logs completos de ambos intentos en `.temp/coordinacion/2026-10-21/`.
La nueva global queda pendiente; evidencia posterior en `.temp` y en la release.
E revisó independientemente el delta contra239b0f5 sin identificar otro bloqueante concreto.
Contrastó selectores, títulos, badge, acciones y foco; no corrió navegador ni pruebas.
Su informe y hashes están en `.temp/resultados/E-review-card-20261021/`.
No hay PASS global ni aceptación de baseline. No se marcan tareas completadas.
