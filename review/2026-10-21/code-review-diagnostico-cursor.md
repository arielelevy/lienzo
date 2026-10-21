# Diagnóstico de posición del cursor

Alcance: browser_window.Windows.position_mouse y pruebas de ventana.
La observación real de0.6.3 informó una posición distinta y bloqueó entrada.
Ese mensaje no identificaba las coordenadas ni separaba un GetCursorPos fallido.

Se conserva un solo SetCursorPos y una comprobación inmediata. Si la lectura falla,
se informa que no pudo comprobarse la posición. Si difiere, se informa pedido y
observado, y se consulta GetClipCursor sólo para obtener el área permitida.
Si no se puede leer esa área se informa su indisponibilidad. Todos esos errores
cortan antes de send_mouse; no se reintenta ni se permite hacer clic fuera de lugar.
No se llama ClipCursor ni se cambia el foco, DPI, permisos o restricciones.

Los límites consultados después del mismatch son contexto posterior, no prueba
de que el recorte causó el fallo. Un usuario u otro programa podría haber movido
el cursor; el texto nuevo no atribuye causa a partir de la diferencia.

Explorer: evento real conservado en native-flow-live-063.json y contrato Win32.
Analyser: separar lectura inválida, coordenada distinta y causa no medida.
Designer: mismatch con límites válidos/no disponibles y GetCursorPos fallido;
verificar coordenadas negativas, un solo movimiento y ningún clic/retry.
Executor:3rojas previas;68pruebas window/stream/remote aprobadas, Ruffcheck/format0.
Detective: revisión independiente E sin nuevos bloqueantes en el delta; no
ejecutó pruebas. No se observó todavía este diagnóstico en la otra PC.

[GetClipCursor](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getclipcursor)
documenta lectura del área y dimensiones de pantalla cuando no hay confinamiento.
No se deduce de ello quién configuró el área ni se la modifica para pasar una prueba.

Evidencia ignorada: cursor-diagnostic-{red,green}.log bajo
.temp/coordinacion/2026-10-21/ e informe .temp/resultados/E-cursor-diagnostic-review.md.
Sin PASS global, baselines nuevos, nuevas ventanas AGY ni pruebas de clic real.
Cambio local todavía no desplegado.
