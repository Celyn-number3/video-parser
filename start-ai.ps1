param(
    [ValidateRange(1024, 65535)][int]$Port = 8888,
    [switch]$CheckOnly,
    [switch]$VerifyFiles
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$modelId = 'Qwen3-VL-8B-Instruct-Q4_K_M'
$server = Join-Path $root 'runtimes\llama.cpp\b11429-cuda12.4\llama-server.exe'
$model = Join-Path $root 'models\qwen3-vl-8b-instruct\Qwen3VL-8B-Instruct-Q4_K_M.gguf'
$vision = Join-Path $root 'models\qwen3-vl-8b-instruct\mmproj-Qwen3VL-8B-Instruct-F16.gguf'
$settingsPath = Join-Path $root '.local\ai\settings.json'
if ($env:VIDEO_PARSER_AI_SETTINGS) { $settingsPath = $env:VIDEO_PARSER_AI_SETTINGS }
$baseUrl = "http://127.0.0.1:$Port/v1"

foreach ($file in @($server, $model, $vision, $settingsPath)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required local file missing: $file" }
}
if ((Get-Item -LiteralPath $model).Length -ne 5027784800 -or (Get-Item -LiteralPath $vision).Length -ne 1159029824) {
    throw 'Model files are incomplete or do not match the pinned Qwen3-VL 8B deployment.'
}
if ($VerifyFiles) {
    if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash -ne '67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2') { throw 'Main model SHA256 mismatch.' }
    if ((Get-FileHash -LiteralPath $vision -Algorithm SHA256).Hash -ne 'ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38') { throw 'Vision component SHA256 mismatch.' }
}
$settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($settings.provider -ne 'llamacpp' -or $settings.base_url -ne $baseUrl -or $settings.model -ne $modelId) {
    throw 'AI settings do not match this local Qwen3-VL deployment. No settings were changed.'
}
if ([string]::IsNullOrWhiteSpace($settings.api_key)) { throw 'A local API token must be configured before starting the model.' }

$serverArgs = @(
    '--model', $model, '--mmproj', $vision,
    '--host', '127.0.0.1', '--port', "$Port", '--alias', $modelId,
    '--n-gpu-layers', '99', '--ctx-size', '32768', '--parallel', '1',
    '--flash-attn', 'on', '--batch-size', '512', '--ubatch-size', '256',
    '--image-max-tokens', '1024', '--n-predict', '4096', '--no-webui'
)
if ($CheckOnly) {
    Write-Host "Preflight OK: $modelId; CUDA; context=32768; image_max_tokens=1024; $baseUrl"
    return
}

function Get-LocalModels {
    $request = [System.Net.HttpWebRequest]::Create("$baseUrl/models")
    $request.Proxy = $null
    $request.Timeout = 5000
    $request.ReadWriteTimeout = 5000
    $request.Headers.Add('Authorization', 'Bearer ' + $settings.api_key)
    $response = $request.GetResponse()
    try {
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        try { return ($reader.ReadToEnd() | ConvertFrom-Json) }
        finally { $reader.Dispose() }
    }
    finally { $response.Dispose() }
}

$connection = New-Object System.Net.Sockets.TcpClient
$occupied = $false
try { $connection.Connect('127.0.0.1', $Port); $occupied = $true }
catch [System.Net.Sockets.SocketException] { }
finally { $connection.Dispose() }
if ($occupied) {
    try {
        $models = Get-LocalModels
        if (@($models.data | Where-Object { $_.id -eq $modelId }).Count -gt 0) {
            Write-Host "Qwen3-VL is already running: $baseUrl"
            return
        }
    }
    catch { }
    throw "Port $Port is occupied or the model is still loading. No process was stopped."
}

Write-Host "Starting $modelId with its visual encoder on CUDA."
Write-Host "Local API: $baseUrl. Keep this terminal open; Ctrl+C stops the model."
$previousKey = $env:LLAMA_API_KEY
try {
    # The token stays on this machine and is never placed on the process command line.
    $env:LLAMA_API_KEY = [string]$settings.api_key
    & $server @serverArgs
    if ($LASTEXITCODE -ne 0) { throw "llama-server exited with code $LASTEXITCODE. See its output above." }
}
finally { $env:LLAMA_API_KEY = $previousKey }
