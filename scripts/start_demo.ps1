<#
Starts the sandbox target and the LoadPilot API for a local product demo.
Press Ctrl+C in this terminal to stop both services.
#>
param(
    [int]$ApiPort = 8000,
    [int]$TargetPort = 8080
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$WebDirectory = Join-Path $ProjectRoot 'web'
$DemoDatabase = Join-Path $ProjectRoot 'artifacts\demo.db'
$K6Binary = Join-Path $ProjectRoot '.tools\k6\k6-v2.1.0-windows-amd64\k6.exe'

if (-not (Test-Path $Python)) {
    throw 'Python environment not found. Run: uv sync --extra dev'
}
if (-not (Test-Path $K6Binary)) {
    throw 'The bundled k6 executable was not found. Install k6 or restore .tools\k6.'
}

function Test-TcpPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $client.Connect('127.0.0.1', $Port)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

if (Test-TcpPort $ApiPort) { throw "Port $ApiPort is already in use. Choose another -ApiPort." }
if (Test-TcpPort $TargetPort) { throw "Port $TargetPort is already in use. Choose another -TargetPort." }

Push-Location $WebDirectory
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed.' }
}
finally {
    Pop-Location
}

$target = Start-Job -Name 'loadpilot-demo-target' -ScriptBlock {
    param($WorkingDirectory, $PythonPath, $Port)
    Set-Location $WorkingDirectory
    & $PythonPath -m uvicorn sandbox_target.app:app --host 127.0.0.1 --port $Port
} -ArgumentList $ProjectRoot, $Python, $TargetPort

$api = Start-Job -Name 'loadpilot-demo-api' -ScriptBlock {
    param($WorkingDirectory, $PythonPath, $Port, $Database, $K6Path, $TargetPort)
    Set-Location $WorkingDirectory
    $env:LOADPILOT_DB = $Database
    $env:LOADPILOT_K6_BIN = $K6Path
    $env:LOADPILOT_TARGET_METRICS_URL = "http://127.0.0.1:$TargetPort/metrics"
    & $PythonPath -m uvicorn loadpilot.api:app --host 127.0.0.1 --port $Port
} -ArgumentList $ProjectRoot, $Python, $ApiPort, $DemoDatabase, $K6Binary, $TargetPort

try {
    $deadline = (Get-Date).AddSeconds(20)
    do {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 2
        } catch { Start-Sleep -Milliseconds 250 }
    } until ($health.status -eq 'ok' -or (Get-Date) -gt $deadline)

    if ($health.status -ne 'ok') {
        Receive-Job $target, $api
        throw 'The demo services did not become ready within 20 seconds.'
    }

    Write-Host ''
    Write-Host "LoadPilot demo ready: http://127.0.0.1:$ApiPort" -ForegroundColor Green
    Write-Host "Sandbox API:          http://127.0.0.1:$TargetPort/docs"
    Write-Host 'Choose New test, keep the supplied OpenAPI URL, then Generate plan.'
    Write-Host 'Press Ctrl+C to stop the demo.'
    Wait-Job $target, $api | Out-Null
}
finally {
    Stop-Job $target, $api -ErrorAction SilentlyContinue
    Remove-Job $target, $api -Force -ErrorAction SilentlyContinue
}
