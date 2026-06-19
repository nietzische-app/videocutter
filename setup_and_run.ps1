param(
    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [string]$OutputVideo = "outputs\clip_vertical.mp4",
    [double]$ClipSeconds = 30,
    [string]$OpenAiApiKey = $env:OPENAI_API_KEY
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

function Get-PythonCommand {
    $candidates = @("python", "py", "python3")
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }

        $versionOutput = ""
        try {
            $versionOutput = & $candidate --version 2>&1
        }
        catch {
            continue
        }

        if ($LASTEXITCODE -eq 0 -and "$versionOutput" -match "Python 3") {
            return $candidate
        }
    }
    return $null
}

$python = Get-PythonCommand
if (-not $python) {
    Write-Host "Python bulunamadi."
    Write-Host "Python'u https://www.python.org/downloads/windows/ adresinden kurun."
    Write-Host "Kurulumda 'Add python.exe to PATH' secenegini isaretleyin, sonra PowerShell'i kapatip acin."
    exit 1
}

if (-not $OpenAiApiKey -or $OpenAiApiKey -eq "sk-...") {
    Write-Host "OPENAI_API_KEY ayarlanmamis."
    Write-Host 'Ornek: $env:OPENAI_API_KEY="sk-..."'
    exit 1
}

$env:OPENAI_API_KEY = $OpenAiApiKey

Write-Host "Python kullaniliyor: $python"
Write-Host "Paketler kuruluyor..."
& $python -m ensurepip --upgrade
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

Write-Host "Video isleniyor..."
& $python video_cutter.py $InputVideo -o $OutputVideo --clip-seconds $ClipSeconds
