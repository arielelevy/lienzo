# Caso aprendizaje-por-proyecto-e2e (encargo Q, 2026-10-22): una copia del código con su propio web/dist en
# $env:TEMP, un server real en 7362 con LIENZO_HOME limpio y el motor SWI-Prolog real. Siembra el ciclo de J
# (checklist_motor_sembrar.py) y el de Q (aprendizaje_sembrar_Q.py: sesión viva por el hook real, propuesta
# propia y de proceso de Lienzo) y recorre la UI sin fixtures (checklist-motor-real y aprendizaje-real).
# Con -IaReal, también el texto libre con Claude real (una llamada corta de haiku, sin guardar nada).
# Nunca toca el server de 7321, ~/.lienzo ni el web/dist del repo. Sale con el primer código no cero.
param([switch]$IaReal)
$ErrorActionPreference = 'Stop'
$raiz = Split-Path $PSScriptRoot
$T = "$env:TEMP\lienzo-Q-inst"; $H = "$env:TEMP\lienzo-Q-home"; $puerto = 7362
$motor = if ($env:LIENZO_PROLOG_ENGINE) { $env:LIENZO_PROLOG_ENGINE } else { Join-Path (Split-Path $raiz) 'motor-logico\main.pl' }

function Parar {
    if (-not (Test-Path "$H\pid")) { return }
    $padre = [int](Get-Content "$H\pid")
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$padre" |
        Where-Object { $_.CommandLine -match 'lienzo-Q-inst' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Stop-Process -Id $padre -Force -ErrorAction SilentlyContinue
}

$previas = @{}
foreach ($v in 'LIENZO_HOME', 'LIENZO_PROLOG_ENGINE', 'LIENZO_URL', 'LIENZO_DEMO_J', 'LIENZO_DEMO_Q', 'LIENZO_IA_REAL', 'PYTHONIOENCODING') { $previas[$v] = [Environment]::GetEnvironmentVariable($v) }

Parar
Remove-Item -Recurse -Force $T, $H -ErrorAction SilentlyContinue
New-Item -ItemType Directory "$T\web", $H | Out-Null
robocopy (Join-Path $raiz 'lienzo') "$T\lienzo" /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
Push-Location (Join-Path $raiz 'web')
try {
    npx vite build --outDir "$T\web\dist" --emptyOutDir --logLevel error
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $env:LIENZO_HOME = $H; $env:LIENZO_PROLOG_ENGINE = $motor; $env:PYTHONIOENCODING = 'utf-8'
    $p = Start-Process -FilePath py -ArgumentList @("$T\lienzo\server.py", '--port', $puerto, '--no-sweep', '--peer-port', 7363) `
        -WorkingDirectory $T -RedirectStandardOutput "$H\out.log" -RedirectStandardError "$H\err.log" -PassThru -WindowStyle Hidden
    $p.Id | Set-Content "$H\pid"
    $arriba = $false
    foreach ($i in 1..60) {
        try { Invoke-WebRequest "http://127.0.0.1:$puerto/" -TimeoutSec 2 -UseBasicParsing | Out-Null; $arriba = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $arriba) { Get-Content "$H\err.log" -Tail 20; exit 2 }
    $env:LIENZO_URL = "http://127.0.0.1:$puerto"
    py -I (Join-Path $PSScriptRoot 'checklist_motor_sembrar.py')
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    py -I (Join-Path $PSScriptRoot 'aprendizaje_sembrar_Q.py') "$T\lienzo" "$T\demo-q"
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $env:LIENZO_DEMO_J = 'demo-j'; $env:LIENZO_DEMO_Q = 'demo-q'
    if ($IaReal) { $env:LIENZO_IA_REAL = '1' }
    npx playwright test --config tests-ui/playwright.config.ts tests-ui/checklist-motor-real.spec.ts tests-ui/aprendizaje-real.spec.ts --workers=1
    exit $LASTEXITCODE
} finally {
    Pop-Location
    Parar
    foreach ($v in $previas.Keys) { [Environment]::SetEnvironmentVariable($v, $previas[$v]) }
}
