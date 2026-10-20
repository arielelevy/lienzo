# Revisión 0.5.2: recuperar novedades durante el avance

Alcance: Updates.tsx, Updates.css, updates.spec.ts, documentación y versionado. Revisión de código
y recorrido de pruebas-agenticas en la misma sesión, sin agentes adicionales.

Pedido final de Ariel: menú derecho Actualizar inicia; la ventana central muestra novedades y
avance detallado como antes. No hay un segundo botón. Se descarta la interpretación inicial de
reponer confirmación manual, aclarada por el usuario antes de modificar el comportamiento.

Se conserva toda la lógica de 0.5.1: espera Git, target fijado, reapertura, errores y timeout.
Sólo vuelve el contenido explicativo (PC, versiones, consulta, changelog) y un encabezado neutral.
Tipografía, colores y espacios usan el sistema existente; progreso gris de 3 px, sin porcentaje
inventado. El CSS corregido usa --dim real del tema, no una variable inexistente.

Verificación: 12 pruebas Chromium contra build aislado, con escrituras bloqueadas. Incluyen
detalle durante building, menú remoto con inicio directo, ausencia de segundo botón y vista
390 px sin scroll horizontal. Capturas desktop y móvil inspeccionadas. ESLint y TypeScript
código 0; compilación aislada código 0, con aviso conocido de bundle >500 kB.
Runner aprobado de frontend-lint y frontend-unit: código 0, igual al baseline.

Sin hallazgos bloqueantes en el alcance revisado. No cambia backend ni se agrega dependencia.
La actualización iniciada por Ariel terminó en 0.5.1 antes de escribir fuentes de esta mejora.
No se publicó web/dist ni se aplicó 0.5.2. No se fijó baseline ni se acredita PASS global.
