# Encargo O: recorrido de interfaz de Kiro (auto-aprobado en la tarjeta, aviso del navegador por un
# diálogo de TUI sin duplicar el de un permiso). Levanta un Vite propio en 7358 sobre el `web` de
# `-Raiz` (el árbol de trabajo, o una copia de HEAD para el rojo), corre la spec con tablero fijo
# contra ese Vite y lo baja. No toca el 7321 ni web/dist.
param([string]$Raiz = (Resolve-Path "$PSScriptRoot\.."), [int]$Puerto = 7358)
$ErrorActionPreference = "Stop"
$web = Join-Path $Raiz "web"
$vite = Start-Process node -ArgumentList "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", $Puerto, "--strictPort" -WorkingDirectory $web -PassThru -WindowStyle Hidden
try {
    $listo = $false
    for ($i = 0; $i -lt 60 -and -not $listo; $i++) {
        try { Invoke-WebRequest "http://127.0.0.1:$Puerto/" -UseBasicParsing -TimeoutSec 2 | Out-Null; $listo = $true } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $listo) { Write-Output "Vite no levantó en $Puerto"; exit 3 }
    $env:LIENZO_URL = "http://127.0.0.1:$Puerto"
    Push-Location $web
    try {
        node node_modules/@playwright/test/cli.js test --config tests-ui/playwright.config.ts tests-ui/kiro-avisos.spec.ts --workers=1
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    exit $code
} finally {
    Stop-Process -Id $vite.Id -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$($vite.Id)" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
