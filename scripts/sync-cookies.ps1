# YouTube cookies.txt dosyasini sunucuya yukler (Windows PowerShell).
#
# Kurulum:
#   copy scripts\sync-cookies.env.example scripts\sync-cookies.env
#   # sync-cookies.env duzenle
#
# Kullanim:
#   .\scripts\sync-cookies.ps1
#   .\scripts\sync-cookies.ps1 -CookiesPath "C:\Downloads\cookies.txt"

param(
    [string]$CookiesPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$ConfigFile = Join-Path $ScriptDir "sync-cookies.env"

$Remote = $env:REMOTE
$RemotePath = $env:REMOTE_PATH
$RestartCmd = $env:RESTART_CMD
$LocalCookies = $CookiesPath

if (Test-Path $ConfigFile) {
    Get-Content $ConfigFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            switch ($name) {
                "REMOTE" { if (-not $Remote) { $Remote = $value } }
                "REMOTE_PATH" { if (-not $RemotePath) { $RemotePath = $value } }
                "RESTART_CMD" { if (-not $RestartCmd) { $RestartCmd = $value } }
                "LOCAL_COOKIES" { if (-not $LocalCookies) { $LocalCookies = $value } }
            }
        }
    }
}

if (-not $Remote) {
    Write-Host "HATA: REMOTE ayarlanmamis. scripts/sync-cookies.env dosyasini duzenleyin."
    exit 1
}

if (-not $RemotePath) {
    $RemotePath = "/root/videocutter/videocutter/cookies.txt"
}

if (-not $LocalCookies) {
    $LocalCookies = Join-Path $ProjectDir "cookies.txt"
}

if (-not (Test-Path $LocalCookies)) {
    Write-Host "HATA: Cookie dosyasi bulunamadi: $LocalCookies"
    Write-Host "Chrome: 'Get cookies.txt LOCALLY' eklentisi ile youtube.com'dan export edin."
    exit 1
}

Write-Host "Yukleniyor: $LocalCookies -> ${Remote}:$RemotePath"
scp $LocalCookies "${Remote}:${RemotePath}"

if ($RestartCmd) {
    Write-Host "Uygulama yeniden baslatiliyor..."
    ssh $Remote $RestartCmd
}

Write-Host "Tamam."
