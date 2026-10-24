param([switch]$DownloadModel, [switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
# Native uv emits UTF-8 even under Windows PowerShell 5.1. Restore host state below.
$SavedConsoleEncoding = [Console]::OutputEncoding
$SavedOutputEncoding = $OutputEncoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
function Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program (exit $LASTEXITCODE)" }
}
$Names = @('UV_PYTHON_INSTALL_DIR','UV_PYTHON_BIN_DIR','UV_CACHE_DIR','PLAYWRIGHT_BROWSERS_PATH','PLAYWRIGHT_SKIP_BROWSER_GC')
$Saved = @{}
foreach ($Name in $Names) { $Saved[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process') }
Push-Location $Root
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'runtimes/python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $Root 'runtimes/bin'
    $LegacyCache = Join-Path $Root 'cache'
    $OldVarCache = Join-Path $Root 'var/cache'
    $CurrentCache = Join-Path $Root '.local/work/cache'
    $ExistingCaches = @(@($LegacyCache, $OldVarCache, $CurrentCache) | Where-Object { Test-Path $_ })
    if ($ExistingCaches.Count -gt 1) { throw 'Multiple cache trees exist; complete or roll back the directory migration first.' }
    $CacheRoot = if ($ExistingCaches.Count -eq 1) { $ExistingCaches[0] } else { $CurrentCache }
    $env:UV_CACHE_DIR = Join-Path $CacheRoot 'uv'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root 'runtimes/browsers'
    $env:PLAYWRIGHT_SKIP_BROWSER_GC = '1'
    $Python = Join-Path $Root 'runtimes/python/cpython-3.12-windows-x86_64-none/python.exe'
    if (!(Test-Path $Python)) {
        Checked 'uv' @('python','install','3.12.13')
        $Found = & uv python find --managed-python 3.12.13
        if ($LASTEXITCODE -ne 0) { throw 'Managed Python lookup failed.' }
        $Python = [IO.Path]::GetFullPath(($Found | Select-Object -Last 1).Trim())
        $ManagedRoot = [IO.Path]::GetFullPath($env:UV_PYTHON_INSTALL_DIR).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (!$Python.StartsWith($ManagedRoot, [StringComparison]::OrdinalIgnoreCase) -or !(Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Managed Python must be inside this project runtime directory.' }
    }
    Checked $Python @('-c','import sys; assert sys.version_info[:3] == (3,12,13)')
    $Main = Join-Path $Root '.venv/Scripts/python.exe'
    $Whisper = Join-Path $Root 'runtimes/whisper/Scripts/python.exe'
    if (!(Test-Path $Main)) { Checked 'uv' @('venv','.venv','--python',$Python,'--seed') }
    if (!(Test-Path $Whisper)) { Checked 'uv' @('venv','runtimes/whisper','--python',$Python,'--seed') }
    # A copied virtual environment is not portable. Never silently overwrite it.
    Checked $Main @('-c',"import pathlib,sys; assert pathlib.Path(sys.prefix).resolve()==(pathlib.Path.cwd()/'.venv').resolve(), 'Recreate the moved main venv'")
    Checked $Whisper @('-c',"import pathlib,sys; assert pathlib.Path(sys.base_prefix).resolve().is_relative_to(pathlib.Path.cwd()), 'Recreate the moved Whisper venv'")
    Checked $Main @('-X','utf8','scripts/check-main-lock.py')
    Checked 'uv' @('pip','install','--python',$Main,'-r','configs/requirements/windows-main.lock.txt','--index-url','https://pypi.org/simple')
    Checked 'uv' @('pip','install','--python',$Main,'--no-deps','-e','.','--index-url','https://pypi.org/simple')
    Checked 'uv' @('pip','install','--python',$Whisper,'-r','configs/requirements/windows-whisper.lock.txt','--index-url','https://pypi.org/simple')
    Checked $Main @('-m','playwright','install','chromium')
    if ($DownloadModel) {
        Checked $Whisper @('-X','utf8','scripts/verify-whisper-model.py','--download')
    } else {
        Write-Output 'Optional Whisper model skipped. Use -DownloadModel before local transcription.'
    }
    Checked $Main @('-m','pip','check')
    Checked $Whisper @('-m','pip','check')
    if (!$SkipFrontend) {
        Push-Location (Join-Path $Root 'frontend')
        try { Checked 'npm.cmd' @('ci'); Checked 'npm.cmd' @('run','build') } finally { Pop-Location }
    }
    Write-Output 'Unified local tools ready. Start with start-web.cmd or python -m video_parser.'
} finally {
    Pop-Location
    [Console]::OutputEncoding = $SavedConsoleEncoding
    $OutputEncoding = $SavedOutputEncoding
    foreach ($Name in $Names) { [Environment]::SetEnvironmentVariable($Name, $Saved[$Name], 'Process') }
}
