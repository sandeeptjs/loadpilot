param([int]$ApiPort = 8000, [int]$TargetPort = 8080)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $ProjectRoot 'web')
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed; run npm ci in web first.' }
} finally { Pop-Location }
Push-Location $ProjectRoot
try { uv run python scripts/start_demo.py --api-port $ApiPort --target-port $TargetPort }
finally { Pop-Location }
