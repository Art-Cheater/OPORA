#Requires -Version 5.1
<#
.SYNOPSIS
  Дожидается Docker и поднимает контейнеры OPORA (web + db), без пересборки.
  Данные PostgreSQL не трогает. Безопасно вызывать повторно (watchdog).
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$dockerBin = @(
    "${env:ProgramFiles}\Docker\Docker\resources\bin",
    "${env:ProgramFiles}\Docker\Docker\resources"
) | Where-Object { Test-Path $_ }
if ($dockerBin) {
    $env:Path = ($dockerBin -join ";") + ";" + $env:Path
}

$LogDir = Join-Path $RepoRoot "instance"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "ensure-up.log"

function Write-Log {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }
    docker info 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Start-DockerDesktopIfNeeded {
    if (Test-DockerReady) { return }

    $dockerExe = @(
        "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($dockerExe) {
        Write-Log "Запуск Docker Desktop: $dockerExe"
        Start-Process -FilePath $dockerExe | Out-Null
    }
}

function Wait-Docker {
    param([int]$TimeoutSec = 180)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerReady) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    Write-Log "Нет .env — выход"
    throw "Файл .env не найден в $RepoRoot"
}

Start-DockerDesktopIfNeeded
if (-not (Wait-Docker)) {
    Write-Log "Docker не ответил за отведённое время"
    throw "Docker не запустился. Включите Docker Desktop и «Start when you sign in»."
}

Write-Log "docker compose up -d"
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Log "compose up завершился с кодом $LASTEXITCODE"
    throw "docker compose up -d не удался"
}

Write-Log "Контейнеры подняты"
