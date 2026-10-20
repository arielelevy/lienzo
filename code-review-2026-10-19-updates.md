# Revisión de cambios: actualizador visual y API

Alcance autorizado: actualizaciones por PC sin reinicio manual, entrada visual y API; plan de
Prolog revisado por CLI Claude. Revisión estática focal del delta, secuencial, por Codex.

## Hallazgos corregidos

- Preparación aislada antes de modificar el checkout: worktree con target fijado, compilación,
  comprobación final de HEAD y árbol limpio, fast-forward sin stash ni reset.
- No confiar en «versión semántica distinta»: comparar commits y detectar también un checkout
  ya descargado que el proceso todavía no cargó.
- GET con caché, Git no interactivo con plazos, operación exclusiva, diario persistido y
  error visible. Sin exposición de stderr/URLs de credenciales.
- Target de aplicar debe coincidir con el consultado y con el remoto al preparar; sin goals,
  comandos ni rutas arbitrarios en la API. Rutas por túnel bloqueadas; peers firmados existentes.
- Preparación restringida al repositorio antes de limpiar el worktree; sin eliminar archivos
  fuera del área temporal. Assets viejos conservados, index publicado al final.
- Cambio de PC aborta lectura anterior y no mezcla resultados. Botón deshabilitado por bloqueo,
  error de consulta u operación activa. Estado de versiones anteriores explícito.
- El plan Prolog incorpora crítica semántica de una CLI Claude real: evidencia sin estado,
  relaciones reales y BFS ya existente. No se conecta el prototipo incompatible.

## Validación y límites

Resultados finales en la evidencia ignorada `pruebas-agenticas/resultados/updates/` y en los
logs del runner. Git real en repositorios temporales; build, lint y navegación con fixtures que
interceptan escrituras. API viva sólo para consultar y recarga explícita del servidor; no se
actualiza a una release ficticia ni se reinicia la otra PC para simular éxito.

La batería global anterior agotó su timeout backend y no es PASS. Esta entrega requiere
informar la validación focal y el veredicto real de compuerta, sin aprobar baseline o mutaciones.

Límites materiales: no hay rollback automático después del fast-forward si falla publicar o
recargar; el error queda visible. Dependencias Python nuevas requieren instalación revisada.
La recarga del proceso usa el supervisor existente: no es cambio de módulos Python en caliente.
Una PC antigua requiere bootstrap convencional para poder usar esta API. El build conserva
el aviso de bundle mayor a 500 kB; no se modificó la política de división del frontend.

Todas las tareas siguen pendientes de veredicto humano.

## Menú de cada PC (pedido posterior de Ariel)

Revisión focal de `PcStrip.tsx`, `Updates.tsx` y su recorrido UI: botón derecho consulta el
estado de la PC elegida; muestra Actualizar si hay versión pendiente y Al día deshabilitado
sólo ante estado current/applied sin error. Una consulta pendiente o fallida no se presenta
como Al día. PC desconectada no habilita acciones. El diálogo arranca en esa PC; cerrar
restaura foco a su tarjeta. El backend mantiene su comprobación del target antes de aplicar.
El menú abre la consulta, no dispara una actualización por botón derecho.

Sin cambios al backend ni al aprendizaje que desarrolla Claude. Build y lint verificados;
recorrido UI incluye menú remoto, destino seleccionado y local al día sin acción.
La primera invocación de UI coincidió con Vite reconstruyendo dist y encontró 503 en la
precondición; se esperó el build y se ejecutó de nuevo, sin alterar oráculos ni baselines.
