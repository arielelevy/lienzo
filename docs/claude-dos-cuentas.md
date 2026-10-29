# Cuotas de dos cuentas Claude

La cuota de Claude que se usa al lanzar se lee del perfil habitual de Claude Code (`CLAUDE_CONFIG_DIR`, o `~/.claude`). Lienzo muestra la organización informada en la configuración local cuando está disponible. La cuota SmartBI se lee aparte de `~/.claude-smartbi`, o del directorio indicado por `LIENZO_CLAUDE_SMARTBI_DIR` en el entorno del servidor. La lectura de SmartBI no participa en la sugerencia automática.

## Cuenta al lanzar según la carpeta

Por defecto, Lienzo lanza Claude con el perfil de siempre. Con `claude_config_dirs` en `~/.lienzo/config.json`, el lanzamiento usa la cuenta que corresponde a la carpeta:

```json
"claude_config_dirs": [{"root": "D:/Apps", "dir": "~/.claude-smartbi"}]
```

Si varias raíces contienen al `cwd`, gana la más larga. El `.cmd` pone `CLAUDE_CONFIG_DIR` antes de abrir Claude. Si la regla aplica pero el `dir` falta, no existe o tiene caracteres inseguros para cmd, Lienzo no lanza. Nunca usa otra cuenta en silencio. Con WSL o `claude_pipe`, una regla que aplica rechaza el lanzamiento, porque esos caminos todavía no la soportan. Al restaurar una sesión que sólo está guardada en el perfil de siempre, se retoma ahí y la respuesta lo avisa. Codex, Pi, Coda y los demás agentes no cambian. La regla se lee en cada lanzamiento.

Para iniciar SmartBI por primera vez, abrir una terminal PowerShell nueva y ejecutar:

```powershell
$env:CLAUDE_CONFIG_DIR = "$env:USERPROFILE\.claude-smartbi"
claude
```

Iniciar sesión en SmartBI en esa terminal. Después, actualizar las cuotas en Lienzo. El perfil mantiene sus propias credenciales y configuración. No copiar credenciales entre perfiles.
