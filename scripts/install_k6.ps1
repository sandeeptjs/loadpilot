param([string]$Version = 'v1.6.1')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^v\d+\.\d+\.\d+$') { throw 'Use an exact k6 release version.' }
$ToolDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) '.tools\k6'
New-Item -ItemType Directory -Force -Path $ToolDirectory | Out-Null
$ArchiveName = "k6-$Version-windows-amd64.zip"
$ArchivePath = Join-Path $ToolDirectory $ArchiveName
$ReleaseUrl = "https://github.com/grafana/k6/releases/download/$Version"
Invoke-WebRequest "$ReleaseUrl/$ArchiveName" -OutFile $ArchivePath
$Checksums = (Invoke-WebRequest "$ReleaseUrl/k6-$Version-checksums.txt").Content
if ($Checksums -is [byte[]]) { $Checksums = [System.Text.Encoding]::UTF8.GetString($Checksums) }
$Checksums = $Checksums -replace "`r", ''
$Expected = (($Checksums -split "`n" | Where-Object { $_ -match ([regex]::Escape($ArchiveName) + '$') }) -split '\s+')[0]
$Actual = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
if (-not $Expected -or $Expected -ne $Actual) { throw 'k6 archive checksum verification failed.' }
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ToolDirectory -Force
$Binary = Join-Path $ToolDirectory "k6-$Version-windows-amd64\k6.exe"
& $Binary version
Write-Host "Verified k6 installed at $Binary"
