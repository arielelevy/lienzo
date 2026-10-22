# Caso etapas-e2e (encargo L, 2026-10-22, decisión 15): una copia del código con su propio web/dist en
# $env:TEMP, un server real en 7356 con LIENZO_HOME limpio. Siembra encargos en cada etapa
# (etapas_sembrar.py), recorre la vista Etapas sin fixtures (etapas-real.spec.ts) y corre la spec con
# fixtures (etapas.spec.ts) contra el mismo bundle. Si el Knowledge.tsx del repo todavía no monta la
# vista, la copia la monta con etapas_montar.py. Nunca toca el 7321, ~/.lienzo ni el web/dist del repo.
$ErrorActionPreference = 'Stop'
$raiz = Split-Path $PSScriptRoot
$T = "$env:TEMP\lienzo-L-inst"; $puerto = 7356

function Parar {
    if (-not (Test-Path "$T\pid")) { return }
    $padre = [int](Get-Content "$T\pid")
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$padre" |
        Where-Object { $_.CommandLine -match 'lienzo-L-inst' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Stop-Process -Id $padre -Force -ErrorAction SilentlyContinue
}

Parar
if (Test-Path "$T\web\node_modules") { (Get-Item "$T\web\node_modules").Delete() }  # el junction, no su destino
Remove-Item -Recurse -Force $T -ErrorAction SilentlyContinue
New-Item -ItemType Directory "$T\web", "$T\home" | Out-Null
robocopy (Join-Path $raiz 'lienzo') "$T\lienzo" /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
foreach ($x in 'src', 'public', 'index.html', 'package.json', 'tsconfig.json', 'vite.config.ts', 'tests-ui') {
    Copy-Item -Recurse (Join-Path $raiz "web\$x") "$T\web\"
}
New-Item -ItemType Junction -Path "$T\web\node_modules" -Target (Join-Path $raiz 'web\node_modules') | Out-Null
py -I (Join-Path $PSScriptRoot 'etapas_montar.py') "$T\web\src\components\Knowledge.tsx"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Push-Location "$T\web"
try {
    npx vite build --logLevel error
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $env:LIENZO_HOME = "$T\home"; $env:CLAUDE_CONFIG_DIR = "$T\claude"; $env:CODEX_HOME = "$T\codex"; $env:CODA_HOME = "$T\coda"
    $env:PYTHONIOENCODING = 'utf-8'
    py -I (Join-Path $PSScriptRoot 'etapas_sembrar.py') "$T\lienzo"
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $p = Start-Process -FilePath py -ArgumentList @("$T\lienzo\server.py", '--port', $puerto, '--no-sweep', '--peer-port', 17356) `
        -WorkingDirectory $T -RedirectStandardOutput "$T\out.log" -RedirectStandardError "$T\err.log" -PassThru -WindowStyle Hidden
    $p.Id | Set-Content "$T\pid"
    $arriba = $false
    foreach ($i in 1..60) {
        try { Invoke-WebRequest "http://127.0.0.1:$puerto/" -TimeoutSec 2 -UseBasicParsing | Out-Null; $arriba = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $arriba) { Get-Content "$T\err.log" -Tail 20; exit 2 }
    $env:LIENZO_URL = "http://127.0.0.1:$puerto"; $env:LIENZO_DEMO_L = 'etapas'
    npx playwright test --config tests-ui/playwright.config.ts tests-ui/etapas-real.spec.ts tests-ui/etapas.spec.ts
    exit $LASTEXITCODE
} finally {
    Pop-Location
    Parar
}
