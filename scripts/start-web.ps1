param(
    [ValidateRange(1024, 65535)][int]$Port = 15001,
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
$url = "http://127.0.0.1:$Port"
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project .venv not found. Create it and install requirements.txt first.'
}
$expectedInstance = (& $python -X utf8 -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path(sys.argv[1]) / 'backend')); from video_parser.core.paths import instance_id; print(instance_id(Path(sys.argv[1])))" $root | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $expectedInstance -notmatch '^[a-f0-9]{12}$') { throw 'Cannot identify this project instance.' }
$connection = New-Object System.Net.Sockets.TcpClient
$occupied = $false
try { $connection.Connect('127.0.0.1', $Port); $occupied = $true }
catch [System.Net.Sockets.SocketException] { }
finally { $connection.Dispose() }
if ($occupied) {
    try {
        $health = Invoke-RestMethod "$url/health" -TimeoutSec 3
        $config = Invoke-RestMethod "$url/api/workspace/config" -TimeoutSec 3
        if ($health.status -eq 'healthy' -and $health.instance -eq $expectedInstance -and $config.PSObject.Properties.Name -contains 'transcription_ready') {
            Write-Host "Video Parser is already running: $url"
            if ($OpenBrowser) { Start-Process $url }
            return
        }
    }
    catch { }
    throw "Port $Port is occupied by another service. No process was stopped."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js >=22.12 and npm are required to build the React frontend.'
}
$browserJob = $null
Push-Location -LiteralPath $root
try {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\node_modules\.bin\vite.cmd'))) {
        & npm.cmd --prefix frontend ci --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend typecheck or build failed.' }
    Write-Host "Video Parser: $url"
    Write-Host 'Keep this window open while using the workspace. Ctrl+C stops the server.'
    if ($OpenBrowser) {
        $browserJob = Start-Job -ArgumentList $url, $expectedInstance -ScriptBlock {
            param($address, $expectedInstance)
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                try {
                    $health = Invoke-RestMethod "$address/health" -TimeoutSec 1
                    $config = Invoke-RestMethod "$address/api/workspace/config" -TimeoutSec 1
                    if ($health.status -eq 'healthy' -and $health.instance -eq $expectedInstance -and $config.PSObject.Properties.Name -contains 'transcription_ready') {
                        Start-Process $address
                        return
                    }
                }
                catch { }
                Start-Sleep -Milliseconds 500
            }
        }
    }
    & $python -X utf8 -m uvicorn video_parser.web.app:app --host 127.0.0.1 --port $Port --no-proxy-headers
    if ($LASTEXITCODE -ne 0) { throw 'Web server failed. Check the port and Python dependencies.' }
}
finally {
    if ($browserJob) { Stop-Job $browserJob; Remove-Job $browserJob }
    Pop-Location
}
