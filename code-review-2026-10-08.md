# Chrome remoto: apertura, entrada y popups

Alcance: cambios en `browser_window.py`, `RemoteBrowser.tsx`, sus pruebas y uso de PowerShell 7 en el runner. Revisión estática de los cambios, sin auditoría global de dependencias.

## Hallazgos corregidos

- La captura principal no incluía ventanas propiedad de Chrome: se componen los popups visibles del mismo proceso y de la ventana seleccionada, en orden de pintura. No se captura el escritorio ni otras aplicaciones. Los popups quedan recortados al área de la ventana compartida.
- `mouse_event` no informa si Windows acepta el clic: se usa `SendInput` y se comprueba su resultado. La selección de ventana y la comprobación de posición permanecen vigentes.
- Las actualizaciones de imagen cambiaban el callback de error y reiniciaban la cola de entrada. El callback se guarda en una referencia y la cola conserva su ciclo de vida.
- Un arrastre táctil se traducía en selección: ahora el toque envía presionar/soltar y el arrastre envía rueda, sin botón presionado.
- El cursor local permanecía como flecha: el worker transmite cambios de cursor del sistema, incluso sin cambios de imagen; la interfaz acepta sólo formas conocidas.
- Los modificadores se sincronizan antes de una tecla ordinaria, para conservar combinaciones como Ctrl+A aunque falte el evento inicial de Control.
- La apertura automática espera perfiles y catálogo de ventanas; abre sólo cuando ese catálogo está vacío. Recuerda el perfil por PC, cancela resultados tardíos y muestra error si Chrome no abre una ventana.

## Verificación

- 45 pruebas de ventana y canal: código 0.
- Seis recorridos de UI con Chrome y peer simulados: código 0; incluyen perfil recordado, recarga sin duplicar apertura, PC caída, modo por pestañas, canal de ventana, toque, arrastre táctil y cursor de enlace.
- Build TypeScript/Vite y lint de cambios: correctos. Vite conserva el aviso existente de bundle mayor a 500 kB.
- Runner agéntico de build/lint: comandos correctos, pero código 1 por baseline ausente. No se fijó baseline ni se declaró PASS certificado.

## Límites y pendientes

Falta comprobar la composición de popups con Chrome real después del despliegue. El parpadeo informado en el modo por pestañas no tiene una causa reproducida. La reparación del runtime de Codex permitió ejecutar comandos nuevamente, pero no modifica el binario de Codex ni garantiza que su bug de permisos no reaparezca.
