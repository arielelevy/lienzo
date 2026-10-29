# Revisión: cuotas desde otras PCs

Alcance: módulo de cuotas federadas, ruta firmada de peers, UI y contratos.
Se reutiliza el transporte firmado; `/peer/cuotas` devuelve sólo la lectura local para impedir recursión.
Cada PC conserva sus credenciales. No se suman saldos y la lectura local válida prevalece.
Una PC caída no se consulta y una versión remota sin la ruta deja el error explícito en `remote_errors`.
La sugerencia de lanzamiento sigue basada en la lectura local: una lectura remota no acredita la cuenta de un proceso local.

Verificación inicial: 32 pruebas focales exitosas. La otra PC está conectada y su checkout estaba limpio,
pero todavía no admite `/peer/cuotas`; hace falta desplegar allí los archivos del servidor y reiniciarlo.
