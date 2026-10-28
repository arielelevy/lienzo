# Cuotas de dos cuentas Claude

La cuota de Claude que se usa al lanzar se lee del perfil habitual de Claude Code (`CLAUDE_CONFIG_DIR`, o `~/.claude`). Lienzo muestra la organización informada en la configuración local cuando está disponible. La cuota SmartBI se lee aparte de `~/.claude-smartbi`, o del directorio indicado por `LIENZO_CLAUDE_SMARTBI_DIR` en el entorno del servidor. La lectura de SmartBI no cambia la cuenta con la que Lienzo lanza Claude ni participa en la sugerencia automática.

Para iniciar SmartBI por primera vez, abrir una terminal PowerShell nueva y ejecutar:

```powershell
$env:CLAUDE_CONFIG_DIR = "$env:USERPROFILE\.claude-smartbi"
claude
```

Iniciar sesión en SmartBI en esa terminal. Después, actualizar las cuotas en Lienzo. El perfil mantiene sus propias credenciales y configuración. No copiar credenciales entre perfiles.
