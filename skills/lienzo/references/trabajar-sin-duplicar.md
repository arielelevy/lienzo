# Trabajar sin duplicar esfuerzo

Parte de la skill `lienzo` (se lee desde `SKILL.md`). Vale para toda coordinadora y todo frente, en cualquier
repo. Texto autorizado por Ariel el 2026-10-25, escrito primero en el `AGENTS.md` de OpenSyync y generalizado
acá como fuente única. Un repo puede sumar reglas propias en su `AGENTS.md`, pero no copiar estas: enlazar.
No reemplaza las reglas de aprobación, baselines y gates de cada repo, ni los requisitos ya comprometidos.

- Optimizar tiempo hasta una entrega verificada y tokens por resultado útil.
  Mantener calidad, seguridad, accesibilidad y sincronización; no llenar sesiones
  con trabajo artificial para aparentar ocupación.
- Antes de encargar, revisar o ejecutar, consultar entregas y evidencia existentes.
  Registrar qué requisito cubren, fuentes/dependencias, configuración, resultado
  y límites. Reutilizarlas mientras esas condiciones sigan vigentes.
- Repetir una comprobación sólo por un cambio que la invalide, un fallo, una duda
  concreta no resuelta o una exigencia explícita del gate. Explicar el motivo.
  Un hash nuevo del módulo completo no exige repetir todos sus ensayos: revisar
  el delta y sus dependencias; conservar el sello histórico sin presentarlo como
  prueba del árbol nuevo. Revalidar lo afectado y los fingerprints exigidos.
- Probar por impacto: documentación o estilo reversible, verificación focal;
  lógica, regresiones y casos adversariales pertinentes; integración y UI,
  contratos y recorridos afectados. La suite global, frontend y localidad se
  coordinan una vez con fuentes congeladas; repetir sólo lo invalidado después.
- Mantener los cinco roles y el code-review obligatorios con evidencia suficiente
  y proporcional. Consolidar la revisión por delta funcional; una revisión nueva
  debe cubrir un riesgo distinto o verificar una corrección, no repetir otra
  por rutina. No crear informes equivalentes ni resellar resultados antiguos.
- Asignar frentes de punta a punta con archivos, dependencias, oráculos y criterio
  de entrega claros. Preparar el siguiente paso útil dentro del encargo para evitar
  rondas de microasignaciones. No fragmentar una función entre varios escritores.
- La coordinadora integra y verifica entregas por lotes, mantiene un registro
  común de gates y resuelve bloqueos concretos. Verificar recepción real de los
  encargos; un envío encolado no prueba trabajo en marcha. Antes de reenviar,
  revisar pantalla o transcript para no duplicar el pedido.
- Distinguir trabajo activo, espera evitable, dependencia, permiso y pausa.
  Las esperas legítimas se explican y revisan al cambiar su condición; las
  evitables se resuelven asignando trabajo autorizado o liberando recursos.
  No esperar a que Ariel detecte sesiones olvidadas.
- Congelar el alcance al entrar al cierre. Mantener las obligaciones ya aceptadas;
  propuestas nuevas e investigación avanzada siguen su fase acordada y no agregan
  gates retroactivos. No recortar requisitos comprometidos para acelerar.
- Los acuses y métricas de coordinación deben ser baratos, agrupados y sin bucles.
  No despertar modelos para confirmar mensajes ni repetir consultas de estado
  cuando hay callbacks fiables. Acusar y verificar las entregas que lo requieran.

## Lo que el lienzo ya hace por estas reglas

- **Esperas clasificadas y sesiones olvidadas**: la auditoría cada 5 min (`lienzo/auditoria.py`) separa trabajo
  activo, espera evitable, entrega sin leer, envío no tomado, permiso, dependencia y pausa, y avisa a la
  coordinadora una sola vez por evidencia, sin despertar modelos. Un `ESTADO: bloqueado` vence según su categoría.
- **Recepción real**: un envío no confirmado en 25 s pasa a «sin enviar» y la auditoría lo avisa; los envíos a una
  sesión salen de a uno. Antes de reenviar, mirar su pantalla (`GET /sessions/<sid>/screen`) o el transcript.
- **Acuses baratos**: `c.enviar(s, texto, sin_aviso=True)` y `c.cablear(solo_si="ESTADO:")` (ver «Rondas largas»
  en `SKILL.md`).
- **Consumo por entrega útil**: `c.trabajo(proyecto)` mide esperas y avisos repetidos; los tokens por turno salen
  de los transcripts de cada PC (la memoria del proyecto todavía no los guarda).
